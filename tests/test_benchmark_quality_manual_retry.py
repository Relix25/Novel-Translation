"""Explicit final transport retries: synthetic evidence, never real model calls."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_quality_full import FakeReviewBridge, snapshot
from test_benchmark_quality_reuse import evidence, judgment, write_prior

from benchmark import save, sha
from tools.benchmark_quality_full import prompt, reuse_review, run

IDLE = "Codex is no longer reporting activity; stopped without automatic retry."


def transport_failure(folder, *, error=IDLE, pass_number=1):
    write_prior(folder, failed=True)
    path = folder / "quality.json"
    report = json.loads(path.read_text("utf-8"))
    report.update(
        known_tokens=0,
        batches=[["B001"]],
        failures=[{"batch": 1, "pass": pass_number, "error": error}],
    )
    report["calls"][0].update(
        {
            "model": "gpt-6.1-sol",
            "effort": "high",
            "pass": pass_number,
            "error": error,
            "token_usage": None,
        }
    )
    save(path, report)
    directory = folder / ("batch-001-pass-%d" % pass_number)
    directory.mkdir()
    original_prompt = prompt([evidence()], pass_number)
    (directory / "prompt.txt").write_text(original_prompt, encoding="utf-8")
    save(
        directory / "call.json",
        {
            "state": "failed",
            "finished_at": "finished",
            "error": error,
            "usage": None,
            "prompt_sha256": sha(original_prompt.encode()),
            "thread": {"id": "original-thread", "ephemeral": True},
            "turn_acknowledgement": {"id": "original-turn", "status": "inProgress"},
            "turn_request": {"model": "gpt-6.1-sol", "effort": "high"},
        },
    )


class FailedFinalBridge(FakeReviewBridge):
    def generate(self, prompt, schema, model, effort, directory, timeout, on_event):
        self.current = {"state": "failed", "usage": None, "seconds": 1}
        self.input_ids.append(json.loads(prompt.split("\nData: ", 1)[1])["cases"])
        raise TimeoutError(IDLE)


class ManualRetryTests(unittest.TestCase):
    def setUp(self):
        FakeReviewBridge.instances = []
        FakeReviewBridge.input_ids = []
        FakeReviewBridge.used = 29
        FakeReviewBridge.invalid_first = False

    def execute(self, root, prior, cases, bridge=FakeReviewBridge):
        experiment = root / "experiment"
        experiment.mkdir(exist_ok=True)
        save(experiment / "results.json", {})
        key = [
            {
                "blind_id": c["blind_id"],
                "trial": n + 1,
                "audit_kind": c["audit_kind"],
                "source_sha256": sha(c["source"].encode()),
                "translation_sha256": sha(c["translation"].encode()),
            }
            for n, c in enumerate(cases)
        ]
        translations = {
            "known_tokens_total": 100000,
            "quota_initial": snapshot(),
            "quota_final": snapshot(),
        }
        with (
            patch(
                "tools.benchmark_quality_full.frozen_cases",
                return_value=(translations, cases, key, {}),
            ),
            patch("tools.benchmark_quality_full.TrialBridge", bridge),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return run(
                experiment,
                root / "quality",
                12000000,
                50,
                reuse_review_folder=prior,
                retry_failed_first_pass_once=True,
            )

    def test_default_has_no_retry_but_explicit_flag_proposes_only_pass_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport_failure(root / "prior")
            metadata, calls, cases, blocked = reuse_review(root / "prior", [evidence("B777")])
            self.assertEqual(metadata["manual_final_transport_retry"], {})
            metadata, calls, cases, blocked = reuse_review(
                root / "prior", [evidence("B777")], retry_failed_first_pass_once=True
            )
            retry = metadata["manual_final_transport_retry"]["B777"]
            self.assertEqual(retry["next_and_final_pass"], 2)
            self.assertEqual(retry["recorded_generation_attempts"], 1)
            self.assertIsNone(retry["prior_token_usage"])

    def test_second_pass_success_preserves_unknown_first_cost_and_has_no_third_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport_failure(root / "prior")
            report = self.execute(root, root / "prior", [evidence("B000")])
            self.assertEqual(report["batch_initial_passes"], [2])
            self.assertEqual([c["pass"] for c in report["calls"]], [1, 2])
            self.assertEqual(FakeReviewBridge.input_ids, [["B000"]])
            self.assertEqual(report["cases"][0]["last_pass"], 2)
            self.assertEqual(report["cases"][0]["verdict"], "uncertain")
            self.assertIsNone(report["calls"][0]["token_usage"])
            self.assertFalse(report["usage_complete"])
            self.assertEqual(report["known_tokens"], 1500)
            metadata, calls, cases, blocked = reuse_review(
                root / "quality", [evidence("B999")], retry_failed_first_pass_once=True
            )
            self.assertEqual(metadata["manual_final_transport_retry"], {})
            self.assertEqual(metadata["recorded_generation_counts"]["B999"], 2)

    def test_second_pass_failure_cannot_receive_any_third_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport_failure(root / "prior")
            report = self.execute(root, root / "prior", [evidence("B777")], FailedFinalBridge)
            self.assertEqual([c["pass"] for c in report["calls"]], [1, 2])
            self.assertEqual(report["cases"], [])
            self.assertTrue(all(c["token_usage"] is None for c in report["calls"]))
            self.assertFalse(report["usage_complete"])
            metadata, calls, cases, blocked = reuse_review(
                root / "quality", [evidence("B999")], retry_failed_first_pass_once=True
            )
            self.assertEqual(metadata["manual_final_transport_retry"], {})
            self.assertEqual(metadata["recorded_generation_counts"]["B999"], 2)

    def test_refusals_regurgitation_rerouting_and_second_pass_failure_never_qualify(self):
        for error, pass_number in [
            ("regurgitation guard", 1),
            ("safety blocked", 1),
            ("Model rerouted", 1),
            (IDLE, 2),
        ]:
            with (
                self.subTest(error=error, pass_number=pass_number),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                transport_failure(root / "prior", error=error, pass_number=pass_number)
                metadata, calls, cases, blocked = reuse_review(
                    root / "prior", [evidence("B777")], retry_failed_first_pass_once=True
                )
                self.assertEqual(metadata["manual_final_transport_retry"], {})

    def test_validated_verdict_or_missing_native_proof_cannot_be_retried(self):
        for obstruction in (
            "verdict",
            "validated_file",
            "native_reroute",
            "missing_turn_ack",
            "changed_prompt",
        ):
            with self.subTest(obstruction=obstruction), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                transport_failure(root / "prior")
                directory = root / "prior" / "batch-001-pass-1"
                if obstruction == "verdict":
                    path = root / "prior" / "quality.json"
                    report = json.loads(path.read_text("utf-8"))
                    report["cases"] = [judgment()]
                    save(path, report)
                elif obstruction == "validated_file":
                    save(directory / "validated.json", {})
                elif obstruction == "changed_prompt":
                    (directory / "prompt.txt").write_text("Changed evidence", encoding="utf-8")
                else:
                    path = directory / "call.json"
                    capture = json.loads(path.read_text("utf-8"))
                    if obstruction == "native_reroute":
                        capture["rerouted"] = {"toModel": "wrong"}
                    else:
                        capture.pop("turn_acknowledgement")
                    save(path, capture)
                metadata, calls, cases, blocked = reuse_review(
                    root / "prior", [evidence("B777")], retry_failed_first_pass_once=True
                )
                self.assertEqual(metadata["manual_final_transport_retry"], {})

    def test_new_cases_use_pass_one_while_manual_retry_uses_pass_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport_failure(root / "prior")
            report = self.execute(
                root, root / "prior", [evidence("B777"), evidence("B888", "new target")]
            )
            self.assertEqual(report["batch_initial_passes"], [2, 1])
            self.assertEqual(
                [(c["pass"], c["case_ids"]) for c in report["calls"]],
                [(1, ["B777"]), (2, ["B777"]), (1, ["B888"])],
            )
            self.assertEqual(FakeReviewBridge.input_ids, [["B777"], ["B888"]])

    def test_blind_id_collisions_do_not_substitute_another_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport_failure(root / "prior")
            metadata, calls, cases, blocked = reuse_review(
                root / "prior",
                [evidence("B001", "different target")],
                retry_failed_first_pass_once=True,
            )
            self.assertEqual(metadata["manual_final_transport_retry"], {})
            self.assertEqual(metadata["recorded_generation_counts"]["B001"], 0)

    def test_duplicate_physical_call_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport_failure(root / "prior")
            path = root / "prior" / "quality.json"
            report = json.loads(path.read_text("utf-8"))
            report["calls"].append(dict(report["calls"][0]))
            save(path, report)
            with self.assertRaisesRegex(ValueError, "Duplicate historical call"):
                reuse_review(root / "prior", [evidence("B777")], retry_failed_first_pass_once=True)


if __name__ == "__main__":
    unittest.main()
