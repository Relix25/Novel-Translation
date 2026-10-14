"""Recover completed audit evidence without rewriting findings or adding third passes."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_quality_full import FakeReviewBridge, snapshot
from test_benchmark_quality_reuse import evidence, judgment

from benchmark import save, sha
from tools.benchmark_quality_full import prompt, reuse_review, run


def completed_invalid_batch(folder):
    folder.mkdir()
    cases = [evidence("B%03d" % n, "target %d" % n) for n in range(10)]
    keys = [
        {
            "blind_id": c["blind_id"],
            "trial": n + 1,
            "audit_kind": c["audit_kind"],
            "source_sha256": sha(c["source"].encode()),
            "translation_sha256": sha(c["translation"].encode()),
        }
        for n, c in enumerate(cases)
    ]
    save(folder / "input.json", cases)
    save(folder / "blind-key.json", keys)
    usage = {"inputTokens": 27000, "outputTokens": 4091}
    native = [judgment(c["blind_id"]) for c in cases]
    for j in native:
        j.pop("batch")
        j.pop("last_pass")
    native[0].update(
        verdict="errors",
        findings=[
            {
                "severity": "major",
                "category": "meaning",
                "source_quote": "source",
                "translation_quote": "invented quotation",
                "explanation": "Synthetic only.",
                "suggested_edit": "",
            }
        ],
    )
    error = "Quality finding does not quote its translation exactly."
    save(
        folder / "quality.json",
        {
            "finished_at": "finished",
            "model": "gpt-6.1-sol",
            "effort": "high",
            "max_passes_per_batch": 2,
            "known_tokens": 31091,
            "usage_complete": True,
            "status": "shared_transport_failed_without_restart",
            "identical_case_reuse": {},
            "batches": [[c["blind_id"] for c in cases]],
            "cases": [],
            "failures": [{"batch": 1, "pass": 1, "error": error}],
            "calls": [
                {
                    "batch": 1,
                    "pass": 1,
                    "case_ids": [c["blind_id"] for c in cases],
                    "state": "failed",
                    "call_state": "completed",
                    "model": "gpt-6.1-sol",
                    "effort": "high",
                    "error": error,
                    "token_usage": usage,
                }
            ],
        },
    )
    directory = folder / "batch-001-pass-1"
    directory.mkdir()
    text = prompt(cases, 1)
    (directory / "prompt.txt").write_text(text, encoding="utf-8")
    save(
        directory / "call.json",
        {
            "state": "completed",
            "finished_at": "finished",
            "usage": usage,
            "prompt_sha256": sha(text.encode()),
            "thread": {"id": "native-thread", "ephemeral": True},
            "turn_acknowledgement": {"id": "native-turn"},
            "turn_request": {"model": "gpt-6.1-sol", "effort": "high"},
        },
    )
    save(
        directory / "raw-response.json",
        {
            "model": "gpt-6.1-sol",
            "effort": "high",
            "thread_id": "native-thread",
            "turn_id": "native-turn",
            "ephemeral": True,
            "token_usage": usage,
            "response": {"cases": native, "limitations": "Synthetic only."},
        },
    )
    return cases, keys


class ValidationRecoveryTests(unittest.TestCase):
    def setUp(self):
        FakeReviewBridge.instances = []
        FakeReviewBridge.input_ids = []
        FakeReviewBridge.used = 29
        FakeReviewBridge.invalid_first = False

    def execute(self, root, prior, cases, keys):
        folder = root / "experiment"
        folder.mkdir()
        save(folder / "results.json", {})
        translation = {
            "known_tokens_total": 100000,
            "quota_initial": snapshot(),
            "quota_final": snapshot(),
        }
        with (
            patch(
                "tools.benchmark_quality_full.frozen_cases",
                return_value=(translation, cases, keys, {}),
            ),
            patch("tools.benchmark_quality_full.TrialBridge", FakeReviewBridge),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return run(
                folder,
                root / "quality",
                12000000,
                50,
                reuse_review_folder=prior,
                resolve_invalid_first_pass=True,
            )

    def test_nine_valid_cases_salvaged_unchanged_only_bad_case_gets_final_pass_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases, keys = completed_invalid_batch(root / "prior")
            before = (root / "prior" / "batch-001-pass-1" / "raw-response.json").read_bytes()
            report = self.execute(root, root / "prior", cases, keys)
            self.assertEqual(FakeReviewBridge.input_ids, [["B000"]])
            self.assertEqual(report["batch_initial_passes"], [2])
            self.assertEqual(
                len(report["prior_review_reuse"]["salvaged_valid_first_pass_case_ids"]), 9
            )
            self.assertEqual(
                set(report["prior_review_reuse"]["invalid_first_pass_resolution"]), {"B000"}
            )
            self.assertEqual(len(report["cases"]), 10)
            self.assertEqual(report["known_tokens"], 32591)
            self.assertEqual(report["prior_review_known_tokens"], 31091)
            self.assertTrue(report["usage_complete"])
            self.assertTrue(
                all(
                    c["last_pass"] == 1 and c["verdict"] == "clean"
                    for c in report["cases"]
                    if c["blind_id"] != "B000"
                )
            )
            preserved = report["prior_review_reuse"]["invalid_first_pass_resolution"]["B000"][
                "invalid_native_case"
            ]
            self.assertEqual(preserved["findings"][0]["translation_quote"], "invented quotation")
            self.assertEqual(
                before, (root / "prior" / "batch-001-pass-1" / "raw-response.json").read_bytes()
            )

    def test_bad_second_pass_is_not_given_a_third_pass_or_invented_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases, keys = completed_invalid_batch(root / "prior")
            FakeReviewBridge.invalid_first = True
            report = self.execute(root, root / "prior", cases, keys)
            self.assertEqual(len(report["cases"]), 9)
            self.assertEqual(FakeReviewBridge.input_ids, [["B000"]])
            metadata, calls, reused, attempted = reuse_review(
                root / "quality", cases, resolve_invalid_first_pass=True
            )
            self.assertEqual(metadata["invalid_first_pass_resolution"], {})
            self.assertEqual(len(reused), 9)
            self.assertNotIn("B000", reused)

    def test_changed_native_thread_proof_or_usage_prevents_recovery(self):
        for obstruction in ("thread", "usage"):
            with self.subTest(obstruction=obstruction), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                cases, keys = completed_invalid_batch(root / "prior")
                path = root / "prior" / "batch-001-pass-1" / "raw-response.json"
                raw = json.loads(path.read_text("utf-8"))
                if obstruction == "thread":
                    raw["thread_id"] = "wrong-native-thread"
                else:
                    raw["token_usage"]["inputTokens"] = 1
                save(path, raw)
                metadata, calls, reused, attempted = reuse_review(
                    root / "prior", cases, resolve_invalid_first_pass=True
                )
                self.assertEqual(metadata["salvaged_valid_first_pass_case_ids"], [])
                self.assertEqual(metadata["invalid_first_pass_resolution"], {})
                self.assertEqual(reused, {})


if __name__ == "__main__":
    unittest.main()
