"""Reporting safeguards for missing metrics and partial full-matrix coverage."""

import unittest

from tools.benchmark_global import all_rows, cells, configuration_totals, coverage
from tools.benchmark_quality_full import batches, prompt


class GlobalBenchmarkTests(unittest.TestCase):
    def test_unknown_usage_and_unassessed_quality_are_not_zero(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "ja",
            "target": "en",
            "repeat": 1,
            "kind": "matched",
            "state": "failed",
            "usage": None,
        }
        rows = all_rows({"trials": [entry]}, [])
        self.assertIsNone(rows[0]["tokens_known"])
        self.assertIsNone(rows[0]["major"])
        summary = cells({"entries": [entry, {**entry, "repeat": 2}]}, rows)[0]
        self.assertEqual(summary["attempts_with_unknown_usage"], 1)
        self.assertEqual(summary["slots_planned"], 2)
        self.assertIsNone(summary["successful_tokens_median"])
        self.assertIsNone(summary["major_mean"])

    def test_final_tokens_do_not_double_count_cache_or_reasoning(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "ja",
            "target": "fr",
            "repeat": 1,
            "kind": "matched",
            "state": "draft",
            "seconds": 10,
            "usage": {
                "inputTokens": 100,
                "outputTokens": 20,
                "cachedInputTokens": 50,
                "reasoningOutputTokens": 15,
            },
        }
        rows = all_rows({"trials": [entry]}, [])
        self.assertEqual(rows[0]["tokens_known"], 120)
        self.assertEqual(cells({"entries": [entry]}, rows)[0]["successful_tokens_median"], 120)

    def test_chain_findings_do_not_overwrite_return_leg_fidelity(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "fr",
            "target": "en",
            "kind": "roundtrip",
            "repeat": 1,
            "state": "draft",
        }
        counts = {"critical": 0, "major": 0, "minor": 0, "uncertain": 0}
        quality = [
            {
                "trial": 1,
                "audit_kind": "translation_fidelity",
                "blind_id": "B001",
                "verdict": "clean",
                "counts": counts,
            },
            {
                "trial": 1,
                "audit_kind": "end_to_end_chain",
                "blind_id": "B002",
                "verdict": "errors",
                "counts": {**counts, "major": 2},
            },
        ]
        row = all_rows({"trials": [entry]}, quality)[0]
        self.assertEqual(row["major"], 0)
        self.assertEqual(row["quality_status"], "clean")

    def test_review_batches_are_bounded_and_second_pass_only_has_selected_cases(self):
        cases = [
            {"blind_id": "B%03d" % n, "source": "x" * 1000, "translation": "y" * 1000}
            for n in range(25)
        ]
        groups = batches(cases, size=12, max_characters=10000)
        self.assertEqual(sum(map(len, groups)), 25)
        self.assertTrue(all(len(g) <= 12 for g in groups))
        second = prompt([cases[0]], 2, [{"blind_id": "B000", "verdict": "uncertain"}])
        self.assertIn("B000", second)
        self.assertNotIn("B001", second)

    def test_retry_keeps_costs_but_counts_one_successful_planned_slot(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "ja",
            "target": "fr",
            "repeat": 1,
            "kind": "matched",
            "state": "failed",
            "usage": {"inputTokens": 10, "outputTokens": 1},
        }
        succeeded = {
            **entry,
            "trial": 2,
            "state": "draft",
            "seconds": 2,
            "usage": {"inputTokens": 20, "outputTokens": 2},
        }
        newest = {
            **succeeded,
            "trial": 3,
            "seconds": 3,
            "usage": {"inputTokens": 30, "outputTokens": 3},
        }
        rows = all_rows({"trials": [entry, succeeded, newest]}, [])
        plan = {"entries": [entry, {**entry, "repeat": 2}]}
        observed = coverage(plan, rows)
        self.assertEqual(observed["successful_slots"], 1)
        self.assertEqual(observed["successful_calls"], 2)
        self.assertEqual(observed["unresolved_slots"], 1)
        self.assertEqual(observed["additional_retry_records"], 2)
        cell = cells(plan, rows)[0]
        self.assertEqual(cell["slots_recorded"], 1)
        self.assertEqual(cell["completed"], 1)
        self.assertEqual(cell["completed_calls"], 2)
        self.assertEqual(cell["known_tokens_all_attempts"], 66)
        self.assertEqual(cell["successful_tokens_median"], 33)
        self.assertEqual(cell["successful_tokens_n"], 1)
        self.assertEqual([r["selected_for_summary"] for r in rows], [False, False, True])

    def test_quota_windows_with_different_reset_identity_are_not_merged(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "ja",
            "target": "fr",
            "repeat": 1,
            "kind": "matched",
            "state": "draft",
            "usage": {"inputTokens": 10, "outputTokens": 1},
        }
        observation = {
            "bucket": "codex",
            "window": "primary",
            "duration_minutes": 10080,
            "resets_at": 100,
            "delta_pp": 2,
        }
        rows = all_rows(
            {
                "trials": [
                    {**entry, "quota_delta": [observation]},
                    {
                        **entry,
                        "trial": 2,
                        "repeat": 2,
                        "quota_delta": [{**observation, "resets_at": 200, "delta_pp": 3}],
                    },
                ]
            },
            [],
        )
        total = configuration_totals(rows)[0]
        self.assertEqual(len(total["quota_observations"]), 2)
        self.assertEqual(
            [w["sum_comparable_intervals_pp"] for w in total["quota_observations"]], [2, 3]
        )
        self.assertEqual([w["resets_at"] for w in total["quota_observations"]], [100, 200])

    def test_explicit_null_partial_counters_do_not_break_report(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "ja",
            "target": "en",
            "repeat": 1,
            "kind": "matched",
            "state": "interrupted",
            "usage": {"inputTokens": 12, "outputTokens": None},
        }
        row = all_rows({"trials": [entry]}, [])[0]
        self.assertEqual(row["tokens_lower_bound"], 12)
        self.assertIsNone(row["tokens_known"])

    def test_concurrent_measurement_metadata_and_overlap_warning_are_preserved(self):
        entry = {
            "trial": 1,
            "model": "gpt-6-luna",
            "effort": "low",
            "source": "ja",
            "target": "fr",
            "repeat": 1,
            "kind": "matched",
            "state": "draft",
            "measurement_mode": "concurrent",
            "measurement_phase": "worker0",
            "quota_shared_concurrent": True,
            "usage": {"inputTokens": 10, "outputTokens": 1},
            "quota_delta": [
                {
                    "bucket": "codex",
                    "window": "primary",
                    "duration_minutes": 10080,
                    "resets_at": 100,
                    "delta_pp": 2,
                }
            ],
        }
        rows = all_rows({"trials": [entry]}, [])
        self.assertEqual(rows[0]["measurement_mode"], "concurrent")
        self.assertEqual(rows[0]["measurement_phase"], "worker0")
        self.assertTrue(
            configuration_totals(rows)[0]["quota_observations"][0][
                "sum_may_double_count_concurrent_usage"
            ]
        )


if __name__ == "__main__":
    unittest.main()
