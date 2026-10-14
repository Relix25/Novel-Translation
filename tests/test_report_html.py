"""Offline reporting must preserve evidence and never invent account readings."""

import tempfile
import unittest
from pathlib import Path

from benchmark import save, sha
from tools.benchmark_conclusions import analyze
from tools.benchmark_global import render
from tools.report_html import document, figure, findings, table


class ReportTests(unittest.TestCase):
    def test_evidence_is_escaped_and_unknown_is_distinct_from_zero(self):
        body = table(
            ["Evidence", "Unknown", "Measured zero"], [["<script>private</script>", None, 0]]
        )
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("<td>—</td>", body)
        self.assertIn("<td>0</td>", body)
        self.assertNotIn("<script>private</script>", document("Synthetic", body))
        self.assertIn('lang="en"', document("Synthetic", body))
        cited = findings(
            [{"trial": 1, "findings": [{"source_quote": "<img onerror='x'>", "severity": "major"}]}]
        )
        self.assertNotIn("<img onerror", cited)
        self.assertIn("&lt;img", cited)

    def test_figure_links_only_existing_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(figure(root, "sample", "Sample"), "")
            (root / "sample.svg").write_text("<svg/>", "utf-8")
            result = figure(root, "sample", "Sample")
            self.assertIn('href="sample.svg"', result)
            self.assertNotIn('href="sample.pdf"', result)

    def test_new_campaign_does_not_inherit_unrecorded_historical_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save(root / "results.json", {"trials": [], "known_tokens_total": 0})
            save(root / "plan.json", {"entries": []})
            save(root / "blind-key.json", [])
            save(
                root / "quality.json",
                {
                    "input_results_sha256": sha((root / "results.json").read_bytes()),
                    "cases": [],
                    "known_tokens": 0,
                },
            )
            data = analyze(root, root / "quality.json")
            self.assertEqual(data["historical_pilot"], {})
            self.assertIsNone(data["historical_known_tokens_separate"])
            render(
                root,
                {"trials": [], "report_snapshot_at": "synthetic UTC"},
                {"entries": []},
                [],
                [],
                [],
            )
            html = (root / "GLOBAL.html").read_text("utf-8")
            self.assertIn("No quality assessment is available", html)
            self.assertNotIn("configuration-cost.svg", html)
