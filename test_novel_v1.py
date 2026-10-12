"""Synthetic fixtures only. No real novel or translation is included.
Run: python -m unittest -v test_novel_v1.py
"""
import copy
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
from unittest.mock import patch
import tempfile
import unittest
from novel_v1 import Novel, digest


class WorkflowTests(unittest.TestCase):
    def test_cli_unicode_json_when_redirected(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name('novel_v1.py')),
                 '--root', folder, 'init', '--title', '小说 — Épreuve',
                 '--source-language', '中文', '--target-language', 'français',
                 '--style', 'Fidèle'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.decode('utf-8'))['title'], '小说 — Épreuve')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "series"
        self.novel = Novel(self.root)
        self.novel.init("Synthetic test", "en", "fr", "Faithful and fluent")
        self.source = "The Azure Gate opens.\n\nMira enters."
        self.novel.import_chapter(1, "Synthetic chapter", self.source)

    def tearDown(self):
        self.novel.close()
        self.temporary.cleanup()

    def response(self, number=1):
        packet = self.novel.packet(number)
        return {"chapter": number, "source_hash": packet["source_hash"],
                "packet_hash": packet["packet_hash"],
                "segments": [{"id": item["id"], "text": "Texte de test " + item["source"]}
                             for item in packet["segments"]]}

    def approved(self):
        response = self.response()
        result = self.novel.submit(1, response)
        self.novel.review(1, result["translation_hash"], "Synthetic review fixture")
        return response, result

    def test_reimport_and_reopen_preserve_original(self):
        result = self.novel.import_chapter(1, "Synthetic chapter", self.source)
        self.assertTrue(result["unchanged"])
        with self.assertRaises(ValueError):
            self.novel.import_chapter(1, "Synthetic chapter", self.source + "\nChanged")
        self.novel.close()
        self.novel = Novel(self.root)
        self.assertEqual(self.novel.chapter(1)["source"], self.source)
        self.assertEqual(len(self.novel.status()), 1)

    def test_missing_duplicate_or_reordered_ids_do_not_commit(self):
        response = self.response()
        wrong = copy.deepcopy(response)
        wrong["segments"].pop()
        with self.assertRaises(ValueError):
            self.novel.submit(1, wrong)
        wrong = copy.deepcopy(response)
        wrong["segments"][1]["id"] = wrong["segments"][0]["id"]
        with self.assertRaises(ValueError):
            self.novel.submit(1, wrong)
        wrong = copy.deepcopy(response)
        wrong["segments"].reverse()
        with self.assertRaises(ValueError):
            self.novel.submit(1, wrong)
        self.assertIsNone(self.novel.chapter(1)["translation"])

    def test_context_change_rejects_old_response(self):
        old_response = self.response()
        self.novel.term("Azure Gate", "Porte azur", 1)
        with self.assertRaisesRegex(ValueError, "Stale context"):
            self.novel.submit(1, old_response)
        self.assertEqual(self.novel.chapter(1)["state"], "imported")

    def test_future_glossary_and_summary_excluded(self):
        before = self.novel.packet(1)["packet_hash"]
        self.novel.term("Mira", "Révélation future", 2)
        self.assertEqual(self.novel.packet(1)["packet_hash"], before)
        self.assertEqual(self.novel.packet(1)["glossary"], [])
        self.novel.import_chapter(2, "Future synthetic chapter", "A future event.")
        response = self.response(2)
        saved = self.novel.submit(2, response)
        self.novel.review(2, saved["translation_hash"], "Future synthetic review")
        summary = {"chapter": 2, "translation_hash": saved["translation_hash"],
                   "text": "Future synthetic fact", "evidence": [response["segments"][0]["id"]]}
        saved_summary = self.novel.summary(2, summary)
        self.novel.review_summary(2, saved_summary["summary_hash"], "Future summary review")
        self.assertEqual(self.novel.packet(1)["previous_summaries"], [])
        self.assertEqual(self.novel.packet(1)["packet_hash"], before)

    def test_review_hash_and_repeated_submit(self):
        response, result = self.approved()
        with self.assertRaises(ValueError):
            self.novel.review(1, "wrong-hash", "Reviewed")
        repeated = self.novel.submit(1, response)
        self.assertTrue(repeated["unchanged"])
        self.assertEqual(repeated["state"], "approved")
        self.assertEqual(result["translation_hash"], repeated["translation_hash"])

    def test_glossary_change_requires_new_review(self):
        self.approved()
        self.novel.term("Azure Gate", "Porte azur", 1)
        self.assertEqual(self.novel.chapter(1)["state"], "needs_review")
        with self.assertRaises(ValueError):
            self.novel.export()
        with self.assertRaises(ValueError):
            self.novel.term("Azure Gate", "Autre porte", 1)
        self.novel.term("Azure Gate", "Autre porte", 1, replace=True)

    def test_summary_evidence_and_human_approval(self):
        _, result = self.approved()
        chapter = self.novel.chapter(1)
        segment_id = json.loads(chapter["segments"])[0]["id"]
        response = {"chapter": 1, "translation_hash": result["translation_hash"],
                    "text": "Résumé synthétique réservé au test.", "evidence": ["future:invalid"]}
        with self.assertRaises(ValueError):
            self.novel.summary(1, response)
        response["evidence"] = [segment_id]
        saved = self.novel.summary(1, response)
        path = self.novel.export()["file"]
        self.assertNotIn("Résumé synthétique réservé au test.", Path(path).read_text(encoding="utf-8"))
        self.novel.review_summary(1, saved["summary_hash"], "Evidence checked; no later facts")
        self.assertIn("Résumé synthétique réservé au test.",
                      Path(self.novel.export()["file"]).read_text(encoding="utf-8"))

    def test_translation_update_invalidates_summary(self):
        response, result = self.approved()
        segment_id = response["segments"][0]["id"]
        summary = {"chapter": 1, "translation_hash": result["translation_hash"],
                   "text": "Synthetic summary", "evidence": [segment_id]}
        saved = self.novel.summary(1, summary)
        self.novel.review_summary(1, saved["summary_hash"], "Synthetic review")
        response["segments"][0]["text"] += " changed"
        new = self.novel.submit(1, response)
        self.novel.review(1, new["translation_hash"], "Revised text reviewed")
        self.assertEqual(self.novel.chapter(1)["summary_state"], "stale")
        with self.assertRaises(ValueError):
            self.novel.review_summary(1, saved["summary_hash"], "Old review")

    def test_backup_and_html_escaping(self):
        response = self.response()
        response["segments"][0]["text"] = '<script>alert("test")</script>'
        saved = self.novel.submit(1, response)
        self.novel.review(1, saved["translation_hash"], "Escaping test")
        exported = Path(self.novel.export()["file"]).read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", exported)
        self.assertNotIn('<script>alert("test")</script>', exported)
        backup = Path(self.temporary.name) / "backup.sqlite"
        self.novel.backup(backup)
        with sqlite3.connect(backup) as db:
            source = db.execute("SELECT source FROM chapters WHERE number=1").fetchone()[0]
        db.close()
        self.assertEqual(source, self.source)
        with self.assertRaises(ValueError):
            self.novel.backup(backup)
        # Restore into a fresh series and reopen it through the application.
        restored_root = Path(self.temporary.name) / "restored"
        restored_root.mkdir()
        shutil.copy2(backup, restored_root / "novel.sqlite")
        restored = Novel(restored_root)
        try:
            self.assertEqual(restored.chapter(1)["source"], self.source)
            self.assertEqual(restored.chapter(1)["translation_hash"], saved["translation_hash"])
            self.assertEqual(restored.chapter(1)["state"], "approved")
            self.assertIn("&lt;script&gt;",
                          Path(restored.export()["file"]).read_text(encoding="utf-8"))
            self.assertEqual(restored.packet(1), self.novel.packet(1))
        finally:
            restored.close()
        # Simulate a destination appearing after the initial existence check.
        concurrent = Path(self.temporary.name) / "concurrent.sqlite"
        concurrent.write_bytes(b"Existing backup must survive")
        original_exists = Path.exists
        def stale_exists(path):
            return False if path == concurrent else original_exists(path)
        with patch.object(Path, "exists", stale_exists):
            with self.assertRaises(FileExistsError):
                self.novel.backup(concurrent)
        self.assertEqual(concurrent.read_bytes(), b"Existing backup must survive")
        self.assertEqual(list(concurrent.parent.glob(".novel-backup-*")), [])

    def test_packet_and_draft_survive_restart(self):
        prepared = self.novel.prepare(1)
        packet = json.loads((Path(prepared["folder"]) / "context.json").read_text(encoding="utf-8"))
        saved = self.novel.submit(1, self.response())
        self.novel.close()
        self.novel = Novel(self.root)
        self.assertEqual(self.novel.chapter(1)["translation_hash"], saved["translation_hash"])
        self.assertEqual(self.novel.packet(1)["packet_hash"], packet["packet_hash"])
        self.assertEqual(self.novel.chapter(1)["state"], "draft")


if __name__ == "__main__":
    unittest.main()

