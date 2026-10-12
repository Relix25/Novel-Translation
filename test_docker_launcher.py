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
    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell 5.1 only')
    def test_bomless_utf8_japanese_source_path_survives_launcher(self):
        with tempfile.TemporaryDirectory(prefix='novel-launcher-test-') as folder:
            root = Path(folder)
            source = root / '負けヒロインが多すぎる！'
            source.mkdir()
            settings = root / 'docker-data' / 'settings.json'
            settings.parent.mkdir()
            settings.write_text(json.dumps({'sources': str(source)}, ensure_ascii=False), encoding='utf-8')
            launcher = root / 'docker-novel.ps1'
            shutil.copyfile(Path(__file__).parent / 'docker-novel.ps1', launcher)
            env = {**os.environ, 'NOVEL_TEST_LAUNCHER': str(launcher)}
            command = "function global:docker { $global:LASTEXITCODE=0; 'Docker stub: no real daemon access' }; & $env:NOVEL_TEST_LAUNCHER Status; if (-not $?) { exit 1 }"
            run = subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-Command', command], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8', errors='replace'))
            saved = json.loads(settings.read_text(encoding='utf-8-sig'))
            self.assertEqual(Path(saved['sources']), source)


if __name__ == '__main__':unittest.main()
