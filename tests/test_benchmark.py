"""Structural benchmark safeguards; never a real-model access claim."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from benchmark import (
    BenchmarkControl,
    budget_ready,
    continuation,
    corpus,
    execute,
    plan,
    quota_delta,
    report,
    save,
    sha,
)


def snapshot(used=20, reset=2000000000, duration=10080, stale=False):
    return {
        "buckets": [
            {
                "id": "codex",
                "windows": [
                    {
                        "key": "primary",
                        "used_percent": used,
                        "resets_at": reset,
                        "duration_minutes": duration,
                        "stale": stale,
                    }
                ],
            }
        ]
    }


class BenchmarkTests(unittest.TestCase):
    def exercise_quota_execution_guard(self, ceiling, missing_initial=False, exhausted=False):
        manifest, texts = corpus()
        entry = {
            "model": "gpt-6-luna",
            "effort": "high",
            "source": "ja",
            "target": "fr",
            "repeat": 1,
            "kind": "matched",
        }
        planned = {"corpus": manifest, "entries": [entry]}
        fresh = snapshot()
        fresh["available"] = True
        fresh["buckets"][0]["windows"][0]["remaining_percent"] = 80
        missing = {"available": False, "buckets": [], "error": "Synthetic quota HTTP failure."}
        control = Mock()
        control.connection.return_value = {"connected": True}
        control.quota.side_effect = [missing if missing_initial else fresh, missing, missing]
        if exhausted:
            empty = copy.deepcopy(fresh)
            empty["buckets"][0]["windows"][0]["remaining_percent"] = 0
            control.quota.side_effect = [fresh, empty]
        bridge = Mock()
        bridge.current = {
            "usage": {"inputTokens": 1000, "outputTokens": 200},
            "seconds": 1,
            "prompt_sha256": "synthetic",
            "thread": {"ephemeral": True},
            "state": "completed",
        }
        library = Mock()
        library.create.return_value = "synthetic-series"
        library.queue_job.return_value = "synthetic-job"
        library.run_job.side_effect = lambda job, selected: selected.generate()
        library.db.execute.return_value.fetchone.return_value = {
            "state": "draft",
            "error": None,
            "result": json.dumps(
                {"response": {"segments": [{"id": "source-id", "text": "Synthetic French."}]}}
            ),
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            with (
                patch("benchmark.BenchmarkControl", return_value=control),
                patch("benchmark.TrialBridge", return_value=bridge),
                patch("benchmark.Library", return_value=library),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = execute(
                    Path(temporary) / "run",
                    planned,
                    texts,
                    max_calls=1,
                    max_tokens=None,
                    max_delta_pp=ceiling,
                    all_cells=True,
                )
        return result, bridge

    def test_explicit_unlimited_run_records_unavailable_quota_and_continues_inference(self):
        for missing_initial in (False, True):
            with self.subTest(missing_initial=missing_initial):
                result, bridge = self.exercise_quota_execution_guard(None, missing_initial)
                bridge.generate.assert_called_once()
                self.assertEqual(result["stop_reason"], "planned_trials_completed")
                self.assertEqual(result["trials"][0]["state"], "draft")
                self.assertEqual(result["known_tokens_total"], 1200)
                self.assertFalse(result["quota_final"]["available"])
                self.assertIsNone(result["limits"]["max_delta_pp"])

    def test_bounded_run_stops_before_inference_if_quota_is_unavailable(self):
        for missing_initial in (False, True):
            with self.subTest(missing_initial=missing_initial):
                result, bridge = self.exercise_quota_execution_guard(32, missing_initial)
                bridge.generate.assert_not_called()
                self.assertEqual(result["trials"], [])
                self.assertIn(
                    result["stop_reason"],
                    (
                        "quota_unavailable_or_window_changed",
                        "ChatGPT connection and fresh quota required before generation.",
                    ),
                )

    def test_unlimited_run_still_stops_on_observed_actual_account_exhaustion(self):
        result, bridge = self.exercise_quota_execution_guard(None, exhausted=True)
        bridge.generate.assert_not_called()
        self.assertEqual(result["stop_reason"], "quota_reserve_reached")
        self.assertEqual(result["trials"], [])

    def test_quota_recovery_refreshes_only_one_read_transport(self):
        control = BenchmarkControl()
        control.process = Mock()
        control.process.poll.return_value = None
        control.rpc = Mock(side_effect=TimeoutError("Synthetic stale transport."))
        fresh = BenchmarkControl()
        fresh.process = Mock()
        fresh.process.poll.return_value = None
        fresh.rpc = Mock(
            return_value={
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {
                        "usedPercent": 41,
                        "windowDurationMins": 10080,
                        "resetsAt": 2000000000,
                    },
                }
            }
        )
        fresh.connection = Mock(return_value={"connected": True})
        fresh.close = Mock()
        fresh.generate = Mock()
        with patch("benchmark.CodexBridge", return_value=fresh):
            value = control.quota()
        self.assertTrue(value["available"])
        self.assertFalse(value["error"])
        self.assertEqual(value["quota_read_recovery"]["attempts"], 2)
        fresh.rpc.assert_called_once_with("account/rateLimits/read", {}, timeout=30)
        fresh.generate.assert_not_called()
        fresh.close.assert_called_once()

    def test_quota_read_timeout_is_extended_but_failed_reads_remain_stale(self):
        control = BenchmarkControl()
        control.process = Mock()
        control.process.poll.return_value = None
        control.rpc = Mock(
            return_value={
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {
                        "usedPercent": 40,
                        "windowDurationMins": 10080,
                        "resetsAt": 2000000000,
                    },
                }
            }
        )
        value = control._quota_once()
        control.rpc.assert_called_once_with("account/rateLimits/read", {}, timeout=30)
        self.assertTrue(value["available"])
        self.assertFalse(value["buckets"][0]["windows"][0]["stale"])
        control.rpc.side_effect = TimeoutError("Synthetic read timeout.")
        failed = control._quota_once()
        self.assertTrue(failed["buckets"][0]["windows"][0]["stale"])
        self.assertEqual(failed["buckets"][0]["windows"][0]["used_percent"], 40)
        self.assertEqual(failed["error"], "Synthetic read timeout.")

    def test_budget_deadline_jitter_does_not_change_scientific_deltas(self):
        before, after = snapshot(), snapshot(21, reset=2000000001)
        for value in (before, after):
            value["buckets"][0]["windows"][0]["observed_at"] = "2026-10-13T00:00:00+00:00"
        self.assertIsNone(quota_delta(before, after)[0]["delta_pp"])
        delta = quota_delta(before, after, allow_timestamp_jitter=True)[0]
        self.assertEqual(delta["delta_pp"], 1)
        self.assertEqual(delta["status"], "account_observation_with_reset_timestamp_jitter")
        after["buckets"][0]["windows"][0]["used_percent"] = 19
        self.assertIsNone(quota_delta(before, after, allow_timestamp_jitter=True)[0]["delta_pp"])
        after["buckets"][0]["windows"][0]["used_percent"] = 21
        after["buckets"][0]["windows"][0]["duration_minutes"] = 300
        self.assertIsNone(quota_delta(before, after, allow_timestamp_jitter=True)[0]["delta_pp"])

    def test_window_reset_cannot_be_charged(self):
        for after in (
            snapshot(21, reset=2000000001),
            snapshot(21, duration=300),
            snapshot(19),
            snapshot(21, stale=True),
        ):
            self.assertIsNone(quota_delta(snapshot(), after)[0]["delta_pp"])

    def test_zero_display_delta_does_not_claim_free_generation(self):
        delta = quota_delta(snapshot(), snapshot())[0]
        self.assertEqual(delta["delta_pp"], 0)
        self.assertEqual(delta["status"], "below_display_resolution_or_zero")

    def test_missing_window_and_missing_read_fail_closed(self):
        self.assertIsNone(quota_delta(snapshot(), {})[0]["delta_pp"])
        self.assertIsNone(quota_delta(snapshot(reset=None), snapshot())[0]["delta_pp"])
        self.assertIsNone(
            quota_delta({**snapshot(), "error": "network"}, snapshot())[0]["delta_pp"]
        )

    def test_windows_never_summed_or_matched_by_duration_alone(self):
        before = snapshot()
        after = snapshot(22)
        before["buckets"].append(
            {"id": "other", "windows": [{**before["buckets"][0]["windows"][0], "used_percent": 5}]}
        )
        after["buckets"].append(
            {"id": "other", "windows": [{**after["buckets"][0]["windows"][0], "used_percent": 8}]}
        )
        self.assertEqual([x["delta_pp"] for x in quota_delta(before, after)], [2, 3])

    def test_pilot_is_16_calls_and_no_luna_ultra_substitution(self):
        models = [
            {
                "model": m,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": e}
                    for e in ("low", "high", "max", "ultra")
                    if e != "ultra" or m != "gpt-6-luna"
                ],
            }
            for m in ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra")
        ]
        a = plan(models)
        self.assertEqual(len(a["entries"]), 16)
        self.assertEqual(a, plan(models))
        self.assertEqual(a["entries"][-1]["kind"], "roundtrip")
        self.assertIn({"model": "gpt-6-luna", "effort": "ultra"}, a["unsupported"])
        with self.assertRaisesRegex(ValueError, "no substitution"):
            plan(models[:1])

    def test_corpus_hashes_and_source_extent(self):
        manifest, texts = corpus()
        self.assertEqual(set(texts), {"en", "fr", "zh", "ko", "ja"})
        self.assertGreater(len(texts["en"].split()), 300)
        self.assertNotIn("Article 1", texts["en"])
        self.assertTrue(texts["en"].endswith("jurisdiction."))
        self.assertEqual(len(manifest["upstream_commit"]), 40)

    def test_budget_will_not_start_another_known_oversized_context(self):
        evidence = {
            "known_tokens_total": 197064,
            "trials": [{"state": "draft", "usage": {"inputTokens": 16218}}],
        }
        self.assertFalse(budget_ready(evidence, 200000))
        self.assertTrue(budget_ready(evidence, 220000))

    def test_interrupted_usage_is_included_but_never_marked_final(self):
        evidence = {
            "trials": [
                {
                    "trial": 1,
                    "state": "interrupted",
                    "call_state": "failed",
                    "model": "m",
                    "effort": "high",
                    "usage": {"inputTokens": 20, "outputTokens": 5, "reasoningOutputTokens": 3},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            report(Path(directory), evidence)
        group = evidence["configuration_totals"]["m/high"]
        self.assertEqual(group["known_tokens"], 25)
        self.assertFalse(group["usage_complete"])

    def test_manual_continuation_reuses_only_unchanged_drafts_and_roundtrip_parent(self):
        manifest, texts = corpus()
        entry = {
            "model": "gpt-6-luna",
            "effort": "high",
            "source": "en",
            "target": "fr",
            "repeat": 1,
            "kind": "coverage",
        }
        return_leg = {**entry, "source": "fr", "target": "en", "kind": "roundtrip"}
        planned = {
            "mode": "pilot",
            "seed": 73113,
            "repetitions": 1,
            "corpus": manifest,
            "entries": [entry, return_leg],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial = root / "trial-001"
            trial.mkdir()
            file = trial / "translation.txt"
            file.write_text("Synthetic draft.", encoding="utf-8")
            save(root / "plan.json", planned)
            save(
                root / "results.json",
                {
                    "finished_at": "finished",
                    "known_tokens_total": 30,
                    "trials": [
                        {
                            **entry,
                            "trial": 1,
                            "state": "draft",
                            "source_sha256": sha(texts["en"].encode()),
                            "translation_sha256": sha(b"Synthetic draft."),
                        }
                    ],
                },
            )
            resumed = copy.deepcopy(planned)
            parents = continuation(root, resumed, texts)
            self.assertEqual(resumed["entries"], [return_leg])
            self.assertEqual(parents[("gpt-6-luna", "high", 1)]["text"], "Synthetic draft.")
            file.write_text("Altered draft.", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed"):
                continuation(root, copy.deepcopy(planned), texts)

    def test_full_continuation_never_retries_a_failed_cell_and_preserves_budget(self):
        manifest, texts = corpus()
        entry = {
            "model": "gpt-6-luna",
            "effort": "medium",
            "source": "ja",
            "target": "en",
            "repeat": 1,
            "kind": "matched",
        }
        next_repeat = {**entry, "repeat": 2}
        planned = {
            "mode": "full",
            "seed": 73113,
            "repetitions": 3,
            "corpus": manifest,
            "entries": [entry, next_repeat],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root / "plan.json", planned)
            save(
                root / "results.json",
                {
                    "finished_at": "finished",
                    "known_tokens_total": 12345,
                    "budget_prior_known_tokens": 6789,
                    "quota_initial": snapshot(29),
                    "budget_quota_initial": snapshot(27),
                    "trials": [{**entry, "trial": 1, "state": "failed"}],
                },
            )
            resumed = copy.deepcopy(planned)
            continuation(root, resumed, texts, preserve_failures=True)
            self.assertEqual(resumed["entries"], [next_repeat])
            meta = resumed["manual_continuation"]
            self.assertEqual(meta["cumulative_prior_known_tokens"], 19134)
            self.assertEqual(meta["budget_quota_initial"], snapshot(27))
            self.assertEqual(
                meta["blocked_cells"][0]["key"], ["gpt-6-luna", "medium", "ja", "en", "matched"]
            )


if __name__ == "__main__":
    unittest.main()
