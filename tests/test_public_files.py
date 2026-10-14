"""Privacy checks use constructed synthetic values, never real credentials."""

import unittest
from unittest.mock import patch

from tools.check_public_files import blobs, findings


class PublicFileTests(unittest.TestCase):
    def test_local_evidence_and_generated_artifacts_are_rejected(self):
        for name in (
            "local-trial/results.json",
            "tests/local-trial/report.html",
            ".venv/tool.py",
            "appdata/library.sqlite",
            "books/source.epub",
            "db.sqlite-journal",
        ):
            with self.subTest(name=name):
                self.assertIn("private artifact", list(findings(name, b"synthetic")))

    def test_sources_and_documented_environment_example_are_allowed(self):
        for name in ("benchmarks/corpus/ja.txt", ".env.example", "imports/.gitkeep", "app.py"):
            self.assertEqual(list(findings(name, "星の門".encode())), [])

    def test_credentials_and_personal_paths_return_only_categories(self):
        samples = {
            "GitHub token": b"ghp_" + b"a" * 40,
            "OpenAI key": b"sk-" + b"a" * 40,
            "personal Windows path": b"C:/" + b"Users/" + b"synthetic-reader/private/",
        }
        for label, content in samples.items():
            self.assertEqual(list(findings("sample.txt", content)), [label])

    def test_batch_protocol_handles_binary_content_and_deduplicates(self):
        sha = "a" * 40
        content = b"one\x00two\nthree"
        wire = f"{sha} blob {len(content)}\n".encode() + content + b"\n"
        with patch("tools.check_public_files.git", return_value=wire) as git:
            self.assertEqual(blobs([sha, sha]), {sha: content})
            self.assertEqual(git.call_args.kwargs["input"], (sha + "\n").encode())

    def test_batch_protocol_rejects_incomplete_or_missing_objects(self):
        sha = "a" * 40
        for wire in (f"{sha} missing\n".encode(), f"{sha} blob 100\nshort\n".encode()):
            with patch("tools.check_public_files.git", return_value=wire):
                with self.assertRaises(ValueError):
                    blobs([sha])
