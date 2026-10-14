"""Synthetic manual recovery and reset-window checks; no account/model access."""

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_quality_full import FakeReviewBridge, snapshot

from benchmark import EFFORTS, MODELS, corpus, plan, save, sha
from tools.benchmark_quality_full import run
from tools.benchmark_recover import prepare
from tools.benchmark_report import build


def entry_key(entry):
    return tuple(entry[k] for k in ("model", "effort", "source", "target", "repeat", "kind"))


class ManualRecoveryTests(unittest.TestCase):
    def make_experiment(self, root):
        manifest, texts = corpus()
        catalogue = [
            {
                "model": model,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": effort}
                    for effort in EFFORTS
                    if model != MODELS[0] or effort != "ultra"
                ],
            }
            for model in MODELS
        ]
        planned = plan(catalogue, mode="full", repetitions=3)
        planned["corpus"] = manifest
        trials = []
        for number, entry in enumerate(planned["entries"][:154], 1):
            trial = {
                **entry,
                "trial": number,
                "state": "draft"
                if number <= 144
                else ("interrupted" if number == 154 else "failed"),
            }
            if trial["state"] == "draft":
                target = "Synthetic candidate %d." % number
                directory = root / ("trial-%03d" % number)
                directory.mkdir()
                (directory / "translation.txt").write_text(target, encoding="utf-8")
                trial.update(
                    source_sha256=sha(texts[entry["source"]].encode()),
                    translation_sha256=sha(target.encode()),
                    usage={"inputTokens": 1000, "outputTokens": 200},
                )
            trials.append(trial)
        recorded = {
            "finished_at": "finished",
            "trials": trials,
            "known_tokens_total": 2771063,
            "quota_initial": snapshot(29),
            "quota_final": snapshot(47),
        }
        save(root / "plan.json", planned)
        save(root / "results.json", recorded)
        return planned, recorded

    def test_preserves_144_successes_and_retries_only_264_remaining_slots(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            original_plan, recorded = self.make_experiment(root)
            immutable_results = (root / "results.json").read_bytes()
            immutable_plan = (root / "plan.json").read_bytes()
            fresh_baseline = snapshot(0)
            fresh_baseline["buckets"][0]["windows"][0]["resets_at"] += 604800
            recovered, texts, parents = prepare(root, fresh_baseline)
            success_keys = {entry_key(t) for t in recorded["trials"] if t["state"] == "draft"}
            failed_keys = {entry_key(t) for t in recorded["trials"] if t["state"] != "draft"}
            remaining_keys = {entry_key(t) for t in recovered["entries"]}
            self.assertEqual(len(original_plan["entries"]), 408)
            self.assertEqual(len(recovered["entries"]), 264)
            self.assertFalse(success_keys & remaining_keys)
            self.assertTrue(failed_keys <= remaining_keys)
            self.assertEqual(
                success_keys | remaining_keys, {entry_key(t) for t in original_plan["entries"]}
            )
            meta = recovered["manual_continuation"]
            self.assertEqual(meta["completed_cells_reused_without_inference"], 144)
            self.assertEqual(meta["cumulative_prior_known_tokens"], 2771063)
            self.assertEqual(meta["budget_quota_initial"], fresh_baseline)
            self.assertNotEqual(meta["budget_quota_initial"], recorded["quota_initial"])
            self.assertEqual(meta["blocked_cells"], [])
            self.assertIn("unknown", meta["quota_reset_note"])
            self.assertEqual(meta["original_results_sha256"], sha(immutable_results))
            for trial in recorded["trials"]:
                if (
                    trial["state"] == "draft"
                    and trial["source"] == "en"
                    and trial["target"] == "fr"
                ):
                    parent = parents[(trial["model"], trial["effort"], trial["repeat"])]
                    self.assertEqual(parent["trial"], trial["trial"])
                    self.assertEqual(
                        Path(parent["directory"]), root / ("trial-%03d" % trial["trial"])
                    )
                    self.assertEqual(sha(parent["text"].encode()), trial["translation_sha256"])
            self.assertEqual((root / "results.json").read_bytes(), immutable_results)
            self.assertEqual((root / "plan.json").read_bytes(), immutable_plan)

    def test_recovery_rejects_altered_preserved_candidate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            self.make_experiment(root)
            (root / "trial-001" / "translation.txt").write_text("Changed.", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed"):
                prepare(root, snapshot(0))

    def test_recovery_rejects_changed_corpus_and_unfinished_experiment(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            planned, recorded = self.make_experiment(root)
            changed = copy.deepcopy(planned)
            changed["corpus"]["languages"]["en"]["extracted_sha256"] = "changed"
            save(root / "plan.json", changed)
            with self.assertRaisesRegex(ValueError, "corpus changed"):
                prepare(root, snapshot(0))
            save(root / "plan.json", planned)
            recorded.pop("finished_at")
            save(root / "results.json", recorded)
            with self.assertRaisesRegex(ValueError, "finished run"):
                prepare(root, snapshot(0))

    def test_report_retains_unknown_duration_for_failed_call(self):
        manifest, _ = corpus()
        entry = {
            "trial": 1,
            "model": MODELS[0],
            "effort": "high",
            "source": "ko",
            "target": "en",
            "state": "failed",
            "kind": "matched",
            "seconds": None,
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            save(root / "plan.json", {"corpus": manifest, "entries": [entry]})
            save(
                root / "results.json",
                {
                    "finished_at": "finished",
                    "trials": [entry],
                    "stop_reason": "recorded_failure",
                    "known_tokens_total": 0,
                    "quota_total": [],
                    "configuration_totals": {},
                },
            )
            result = build(root).read_text("utf-8")
            self.assertIn("<td>unknown</td>", result)
            self.assertIn("<td>unknown</td>", result)

    def test_administrative_resume_partitions_only_unrecorded_slots_without_retry(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            previous = root / "previous"
            previous.mkdir()
            original, recorded = self.make_experiment(previous)
            # A successful human-requested retry supersedes the earlier rejection.
            cleared = recorded["trials"][144]
            retried = {
                **cleared,
                "trial": 155,
                "state": "draft",
                "source_sha256": sha(corpus()[1][cleared["source"]].encode()),
                "translation_sha256": sha(b"Synthetic successful retry."),
                "usage": {"inputTokens": 1000, "outputTokens": 200},
            }
            candidate = previous / "trial-155"
            candidate.mkdir()
            (candidate / "translation.txt").write_text(
                "Synthetic successful retry.", encoding="utf-8"
            )
            recorded["trials"].append(retried)
            save(previous / "results.json", recorded)
            baseline = root / "baseline.json"
            save(baseline, snapshot(0))
            shards = []
            for index in range(4):
                output = root / ("shard-%d" % index)
                completed = subprocess.run(
                    [
                        sys.executable,
                        "tools/benchmark_recover.py",
                        str(previous),
                        str(output),
                        "--quota-baseline",
                        str(baseline),
                        "--max-tokens",
                        "12000000",
                        "--max-delta-pp",
                        "32",
                        "--unlimited-tokens",
                        "--unprocessed-only",
                        "--partition-count",
                        "4",
                        "--partition-index",
                        str(index),
                        "--plan-only",
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                shards.append(json.loads((output / "plan.json").read_text("utf-8")))
            processed = {entry_key(t) for t in recorded["trials"]}
            expected = {entry_key(t) for t in original["entries"]} - processed
            flattened = [entry_key(t) for shard in shards for t in shard["entries"]]
            self.assertEqual(len(expected), 254)
            self.assertEqual(set(flattened), expected)
            self.assertEqual(len(flattened), len(set(flattened)))
            self.assertFalse(set(flattened) & processed)
            cell = lambda t: tuple(t[k] for k in ("model", "effort", "source", "target", "kind"))
            for shard in shards:
                blocked = {tuple(t["key"]) for t in shard["manual_continuation"]["blocked_cells"]}
                self.assertNotIn(cell(cleared), blocked)
                self.assertIn(cell(recorded["trials"][153]), blocked)
                self.assertTrue(shard["execution_policy"]["unlimited_token_budget"])
                self.assertEqual({entry_key(t) for t in shard["master_entries"]}, expected)


class ReviewResetBaselineTests(unittest.TestCase):
    def setUp(self):
        FakeReviewBridge.instances = []
        FakeReviewBridge.input_ids = []
        FakeReviewBridge.used = 4
        FakeReviewBridge.invalid_first = False

    def exercise(self, override=True, max_tokens=12000000):
        historical = snapshot(29)
        historical["buckets"][0]["windows"][0]["resets_at"] -= 604800
        fresh = snapshot(0)
        translations = {
            "known_tokens_total": 2771063,
            "quota_initial": historical,
            "quota_final": historical,
        }
        cases = [{"blind_id": "B010", "source": "source", "translation": "target"}]
        key = [{"blind_id": "B010", "trial": 1, "audit_kind": "translation_fidelity"}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            folder = root / "experiment"
            folder.mkdir()
            save(folder / "results.json", {})
            with (
                patch(
                    "tools.benchmark_quality_full.frozen_cases",
                    return_value=(translations, cases, key, {}),
                ),
                patch("tools.benchmark_quality_full.TrialBridge", FakeReviewBridge),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                return run(
                    folder,
                    root / "quality",
                    max_tokens,
                    32,
                    quota_baseline=fresh if override else None,
                ), fresh

    def test_explicit_new_window_baseline_allows_review_and_preserves_all_tokens(self):
        result, fresh = self.exercise()
        self.assertEqual(FakeReviewBridge.input_ids, [["B010"]])
        self.assertEqual(result["status"], "assessed")
        self.assertEqual(result["quota_baseline"], fresh)
        self.assertEqual(result["translation_known_tokens"], 2771063)
        self.assertEqual(result["combined_known_tokens"], 2772563)
        self.assertEqual(result["combined_quota_total"][0]["delta_pp"], 4)

    def test_historical_reset_baseline_stops_without_fabricating_delta(self):
        result, _ = self.exercise(override=False)
        self.assertEqual(FakeReviewBridge.input_ids, [])
        self.assertEqual(result["status"], "budget_or_quota_guard_reached")
        self.assertIsNone(result["combined_quota_total"][0]["delta_pp"])
        self.assertEqual(result["combined_known_tokens"], 2771063)

    def test_new_window_does_not_reset_combined_token_budget(self):
        result, _ = self.exercise(max_tokens=2771063 + 15999)
        self.assertEqual(FakeReviewBridge.input_ids, [])
        self.assertEqual(result["status"], "budget_or_quota_guard_reached")
        self.assertEqual(result["combined_known_tokens"], 2771063)


if __name__ == "__main__":
    unittest.main()
