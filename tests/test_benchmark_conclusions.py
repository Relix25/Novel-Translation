"""Analytic conclusions use comparable positions and never invent quality scores."""

import unittest

from tools.benchmark_conclusions import failure_category, matched_efforts, quality_summary
from tools.benchmark_global import all_rows


class ConclusionsTests(unittest.TestCase):
    def test_paired_efforts_require_same_actual_source_mode_and_cache(self):
        base = {
            "model": "gpt-6-luna",
            "source": "ja",
            "target": "fr",
            "kind": "matched",
            "state": "draft",
            "measurement_mode": "concurrent",
            "seconds": 10,
            "usage": {"inputTokens": 100, "outputTokens": 10, "cachedInputTokens": 50},
        }
        entries = []
        for repeat in (1, 2, 3):
            entries.extend(
                [
                    {**base, "trial": repeat * 2 - 1, "repeat": repeat, "effort": "low"},
                    {
                        **base,
                        "trial": repeat * 2,
                        "repeat": repeat,
                        "effort": "high",
                        "seconds": 15,
                        "measurement_mode": "sequential" if repeat == 2 else "concurrent",
                        "usage": {
                            "inputTokens": 200,
                            "outputTokens": 20,
                            "cachedInputTokens": 0 if repeat == 3 else 100,
                        },
                    },
                ]
            )
        rows = all_rows({"trials": entries}, [])
        for row in rows:
            row["source_sha256"] = "shared-source"
        quality = [
            {
                "trial": row["trial"],
                "blind_id": str(row["trial"]),
                "audit_kind": "translation_fidelity",
                "source_sha256": "different-source" if row["trial"] == 6 else "shared-source",
                "counts": {
                    "critical": 0,
                    "major": 1 if row["effort"] == "low" else 0,
                    "minor": 0,
                    "uncertain": 0,
                },
            }
            for row in rows
        ]
        pair = matched_efforts(rows, quality)[0]
        self.assertEqual(pair["quality_pairs"], 2)
        self.assertEqual(pair["major_mean_change"], -1)
        self.assertEqual(pair["major_lower_higher_equal"], [2, 0, 0])
        self.assertEqual(pair["same_mode_cache_final_cost_pairs"], 1)
        self.assertEqual(pair["paired_tokens_percent_median"], 100)
        self.assertEqual(pair["paired_duration_percent_median"], 50)

    def test_chain_readings_stay_separate_and_retry_does_not_add_a_pair(self):
        base = {
            "model": "gpt-6-luna",
            "source": "fr",
            "target": "en",
            "kind": "roundtrip",
            "state": "draft",
            "repeat": 1,
            "measurement_mode": "sequential",
            "seconds": 10,
            "usage": {"inputTokens": 100, "outputTokens": 10, "cachedInputTokens": 0},
        }
        rows = all_rows(
            {
                "trials": [
                    {**base, "trial": 1, "effort": "low"},
                    {**base, "trial": 2, "effort": "high"},
                    {**base, "trial": 3, "effort": "high"},
                ]
            },
            [],
        )
        for row in rows:
            row["source_sha256"] = "different-intermediate-" + str(row["trial"])
        quality = [
            {
                "trial": 1,
                "blind_id": "C1",
                "audit_kind": "end_to_end_chain",
                "source_sha256": "original-en",
                "counts": {"critical": 0, "major": 1, "minor": 0, "uncertain": 0},
            },
            {
                "trial": 3,
                "blind_id": "C3",
                "audit_kind": "end_to_end_chain",
                "source_sha256": "original-en",
                "counts": {"critical": 0, "major": 0, "minor": 0, "uncertain": 0},
            },
        ]
        pairs = matched_efforts(rows, quality)
        self.assertEqual(pairs[0]["audit_kind"], "translation_fidelity")
        self.assertEqual(pairs[0]["quality_pairs"], 0)
        self.assertEqual(pairs[1]["audit_kind"], "end_to_end_chain")
        self.assertEqual(pairs[1]["quality_pairs"], 1)
        self.assertEqual(pairs[1]["same_mode_cache_final_cost_pairs"], 0)

    def test_failures_are_classified_by_explicit_evidence(self):
        self.assertEqual(
            failure_category("regurg plugin blocked the output stream."),
            "content_filter_or_explicit_refusal",
        )
        self.assertEqual(
            failure_category("workspace routing discovery timed out"),
            "transport_or_execution_failure",
        )
        self.assertEqual(failure_category("Unknown failure"), "unclassified_failure")
        self.assertEqual(failure_category(None), "unclassified_failure")

    def test_no_findings_is_not_a_numeric_quality_score(self):
        quality = [
            {
                "blind_id": "B1",
                "verdict": "clean",
                "counts": {s: 0 for s in ("critical", "major", "minor", "uncertain")},
            },
            {
                "blind_id": "B2",
                "verdict": "clean",
                "assessment_reused_from": "B1",
                "counts": {s: 0 for s in ("critical", "major", "minor", "uncertain")},
            },
        ]
        summary = quality_summary(quality)
        self.assertEqual(summary["assessed"], 2)
        self.assertEqual(summary["distinct_judgments"], 1)
        self.assertNotIn("score", summary)


if __name__ == "__main__":
    unittest.main()
