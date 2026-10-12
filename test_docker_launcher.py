"""Exercise the actual launcher in Windows PowerShell 5.1 with a harmless Docker stub."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


POWERSHELL = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


class LauncherEncodingTests(unittest.TestCase):
    def guarded_launcher(self, action, state_function):
        with tempfile.TemporaryDirectory(prefix='novel-launcher-guard-') as folder:
            root = Path(folder)
            (root / 'docker-data' / 'library').mkdir(parents=True)
            launcher = root / 'docker-novel.ps1'
            shutil.copyfile(Path(__file__).parent / 'docker-novel.ps1', launcher)
            env = {**os.environ, 'NOVEL_TEST_LAUNCHER': str(launcher)}
            command = (
                "$global:calls=@(); $global:reads=0; "
                "function global:docker { $global:LASTEXITCODE=0; "
                "$global:calls+=($args -join ' '); "
                "if ($args -contains 'version') { 'test' }; "
                "if ($args -contains 'ps') { 'running-container' } }; "
                "function global:Invoke-RestMethod { " + state_function + " }; "
                "try { & $env:NOVEL_TEST_LAUNCHER " + action + "; exit 9 } "
                "catch { $global:calls | ConvertTo-Json -Compress; exit 0 }")
            run = subprocess.run(
                [str(POWERSHELL), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-Command', command], env=env, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            return run.stdout.decode('utf-8', errors='replace')

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell 5.1 only')
    def test_unreachable_running_server_never_builds_restarts_or_stops(self):
        for action in ('Up', 'Restart', 'Stop'):
            with self.subTest(action=action):
                output = self.guarded_launcher(action, "throw 'offline'")
                self.assertNotIn('build novel', output)
                self.assertNotIn('restart novel', output)
                self.assertNotIn('stop novel', output)

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell 5.1 only')
    def test_work_started_during_build_prevents_container_replacement(self):
        output = self.guarded_launcher('Up',
            "$global:reads++; if ($global:reads -eq 1) { "
            "[pscustomobject]@{jobs=@();runs=@()} } else { "
            "[pscustomobject]@{jobs=@([pscustomobject]@{state='running'});runs=@()} }")
        self.assertIn('build novel', output)
        self.assertNotIn('up --detach', output)

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell 5.1 only')
    def test_bomless_utf8_japanese_source_path_survives_launcher(self):
        with tempfile.TemporaryDirectory(prefix='novel-launcher-test-') as folder:
            root = Path(folder)
            source = root / '小説 — Démonstration'
            source.mkdir()
            settings = root / 'docker-data' / 'settings.json'
            settings.parent.mkdir()
            settings.write_text(json.dumps({'sources': str(source)}, ensure_ascii=False), encoding='utf-8')
            launcher = root / 'docker-novel.ps1'
            shutil.copyfile(Path(__file__).parent / 'docker-novel.ps1', launcher)
            env = {**os.environ, 'NOVEL_TEST_LAUNCHER': str(launcher)}
            command = "function global:docker { $global:LASTEXITCODE=0; 'Docker stub: no real daemon access' }; & $env:NOVEL_TEST_LAUNCHER Status; if (-not $?) { exit 1 }"
            run = subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8', errors='replace'))
            saved = json.loads(settings.read_text(encoding='utf-8-sig'))
            self.assertEqual(Path(saved['sources']), source)


if __name__ == '__main__':unittest.main()
