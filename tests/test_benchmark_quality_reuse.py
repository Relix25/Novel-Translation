"""Exact evidence reuse safety tests: synthetic fixtures, no model calls."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_quality_full import FakeReviewBridge, snapshot

from benchmark import save, sha
from tools.benchmark_quality_full import case_fingerprint, reuse_review, run


def evidence(identity="B001", translated="target", kind="translation_fidelity"):
    return {
        "blind_id": identity,
        "audit_kind": kind,
        "source_language": "en",
        "target_language": "fr",
        "source_segment_id": "original-segment",
        "source": "source",
        "translation": translated,
        "institutional_reference": "reference",
        "roundtrip_reference_is_diagnostic_only": False,
    }


def judgment(identity="B001", uncertain=False):
    finding = {
        "severity": "uncertain",
        "category": "meaning",
        "source_quote": "source",
        "translation_quote": "target",
        "explanation": "Synthetic uncertainty.",
        "suggested_edit": "",
    }
    return {
        "blind_id": identity,
        "verdict": "uncertain" if uncertain else "clean",
        "findings": [finding] if uncertain else [],
        "fluency": "natural",
        "register": "preserved",
        "assessment": "Synthetic only.",
        "batch": 1,
        "last_pass": 2 if uncertain else 1,
    }


def write_prior(folder, *, uncertain=False, failed=False):
    folder.mkdir()
    case = evidence()
    save(folder / "input.json", [case])
    save(
        folder / "blind-key.json",
        [
            {
                "blind_id": "B001",
                "trial": 1,
                "source_sha256": sha(case["source"].encode()),
                "translation_sha256": sha(case["translation"].encode()),
            }
        ],
    )
    report = {
        "finished_at": "finished",
        "model": "gpt-6.1-sol",
        "effort": "high",
        "max_passes_per_batch": 2,
        "input_results_sha256": "synthetic-result-hash",
        "status": "partially_assessed_with_failures" if failed else "assessed",
        "known_tokens": 1500,
        "usage_complete": not failed,
        "identical_case_reuse": {},
        "calls": [
            {
                "batch": 1,
                "pass": 2 if uncertain else 1,
                "case_ids": ["B001"],
                "state": "failed" if failed else "completed",
                "call_state": "failed" if failed else "completed",
                "token_usage": {"inputTokens": 1000, "outputTokens": 500},
            }
        ],
        "cases": [] if failed else [judgment(uncertain=uncertain)],
    }
    save(folder / "quality.json", report)


def never_started_prior(folder):
    write_prior(folder, failed=True)
    path = folder / "quality.json"
    report = json.loads(path.read_text("utf-8"))
    report.update(
        calls=[],
        known_tokens=0,
        batches=[["B001"]],
        failures=[{"batch": 1, "pass": 1, "error": "workspace routing discovery timed out"}],
    )
    save(path, report)
    (folder / "batch-001-pass-1").mkdir()
    (folder / "review-runner-source.py").write_text(
        "# Synthetic frozen runner fixture", encoding="utf-8"
    )


class QualityReuseTests(unittest.TestCase):
    def setUp(self):
        FakeReviewBridge.instances = []
        FakeReviewBridge.input_ids = []
        FakeReviewBridge.used = 29
        FakeReviewBridge.invalid_first = False

    def test_fingerprint_ignores_only_display_and_segment_identifiers(self):
        case = evidence()
        equivalent = {**case, "blind_id": "B222", "source_segment_id": "new-id"}
        self.assertEqual(case_fingerprint(case), case_fingerprint(equivalent))
        for field in (
            "source",
            "translation",
            "institutional_reference",
            "audit_kind",
            "target_language",
        ):
            changed = {**case, field: case[field] + " changed"}
            self.assertNotEqual(case_fingerprint(case), case_fingerprint(changed))

    def test_resolved_and_uncertain_prior_cases_get_no_more_passes(self):
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_prior(root / "prior", uncertain=uncertain)
                current = {**evidence("B777"), "source_segment_id": "new-id"}
                metadata, calls, cases, attempted = reuse_review(root / "prior", [current])
                self.assertEqual(attempted, {"B777"})
                self.assertEqual(cases["B777"]["last_pass"], 2 if uncertain else 1)
                self.assertEqual(calls[0]["case_ids"], ["B777"])
                self.assertEqual(calls[0]["review_provenance"]["original_case_ids"], ["B001"])
                self.assertEqual(metadata["known_tokens"], 1500)
                self.assertEqual(
                    set(metadata["immutable_file_sha256"]),
                    {"input.json", "blind-key.json", "quality.json"},
                )

    def test_failed_attempt_is_carried_as_unassessed_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior", failed=True)
            metadata, calls, cases, attempted = reuse_review(root / "prior", [evidence("B777")])
            self.assertEqual(cases, {})
            self.assertEqual(attempted, {"B777"})
            self.assertEqual(metadata["unassessed_attempted_case_ids"], ["B777"])
            self.assertFalse(metadata["usage_complete"])
            self.assertEqual(calls[0]["state"], "failed")

    def test_changed_candidate_and_distinct_chain_type_are_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior")
            metadata, calls, cases, attempted = reuse_review(
                root / "prior",
                [evidence("B222", "different target"), evidence("B333", kind="end_to_end_chain")],
            )
            self.assertEqual(cases, {})
            self.assertEqual(attempted, set())
            self.assertEqual(metadata["known_tokens"], 1500)

    def test_connection_failure_before_call_record_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior", failed=True)
            path = root / "prior" / "quality.json"
            report = json.loads(path.read_text("utf-8"))
            report.update(
                calls=[],
                known_tokens=0,
                batches=[["B001"]],
                failures=[{"batch": 1, "pass": 1, "error": "Synthetic connection failure"}],
            )
            save(path, report)
            metadata, calls, cases, attempted = reuse_review(root / "prior", [evidence("B777")])
            self.assertEqual(attempted, {"B777"})
            self.assertEqual(metadata["failed_batches"][0]["pass"], 1)
            self.assertEqual(calls, [])

    def test_manual_continuation_allows_only_proven_never_started_first_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            never_started_prior(root / "prior")
            metadata, calls, cases, attempted = reuse_review(root / "prior", [evidence("B777")])
            self.assertEqual(attempted, {"B777"})
            self.assertEqual(metadata["continuable_unstarted_case_ids"], ["B777"])
            metadata, calls, cases, attempted = reuse_review(
                root / "prior", [evidence("B777")], continue_unstarted=True
            )
            self.assertEqual(attempted, set())
            self.assertEqual(cases, {})
            self.assertEqual(calls, [])
            self.assertEqual(metadata["continued_unstarted_case_ids"], ["B777"])
            self.assertEqual(metadata["unstarted_failure_proofs"][0]["directory_entries"], [])
            self.assertEqual(metadata["known_tokens"], 0)

    def test_manual_continuation_rejects_artifacts_unknown_error_or_later_pass(self):
        for obstruction in (
            "call_artifact",
            "prompt_artifact",
            "missing_directory",
            "wrong_error",
            "second_pass",
            "missing_runner",
        ):
            with self.subTest(obstruction=obstruction), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                never_started_prior(root / "prior")
                batch = root / "prior" / "batch-001-pass-1"
                if obstruction == "call_artifact":
                    save(batch / "call.json", {"state": "starting"})
                elif obstruction == "prompt_artifact":
                    (batch / "prompt.txt").write_text(
                        "Possible attempted generation", encoding="utf-8"
                    )
                elif obstruction == "missing_directory":
                    batch.rmdir()
                elif obstruction == "missing_runner":
                    (root / "prior" / "review-runner-source.py").unlink()
                else:
                    path = root / "prior" / "quality.json"
                    report = json.loads(path.read_text("utf-8"))
                    if obstruction == "wrong_error":
                        report["failures"][0]["error"] = "Unknown generation failure"
                    else:
                        report["failures"][0]["pass"] = 2
                    save(path, report)
                metadata, calls, cases, attempted = reuse_review(
                    root / "prior", [evidence("B777")], continue_unstarted=True
                )
                self.assertEqual(attempted, {"B777"})
                self.assertEqual(metadata["continued_unstarted_case_ids"], [])

    def test_manual_continuation_never_retries_actual_failed_call_or_uncertain_case(self):
        for failed in (True, False):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_prior(root / "prior", failed=failed, uncertain=not failed)
                path = root / "prior" / "quality.json"
                report = json.loads(path.read_text("utf-8"))
                report.update(
                    batches=[["B001"]],
                    failures=[
                        {"batch": 1, "pass": 1, "error": "workspace routing discovery timed out"}
                    ],
                )
                save(path, report)
                (root / "prior" / "batch-001-pass-1").mkdir()
                (root / "prior" / "review-runner-source.py").write_text(
                    "# Synthetic runner", encoding="utf-8"
                )
                metadata, calls, cases, attempted = reuse_review(
                    root / "prior", [evidence("B777")], continue_unstarted=True
                )
                self.assertEqual(attempted, {"B777"})
                self.assertEqual(metadata["continued_unstarted_case_ids"], [])

    def test_tampered_quotes_key_cost_or_unfinished_prior_are_rejected(self):
        for corruption in ("quote", "key", "cost", "unfinished"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_prior(root / "prior", uncertain=True)
                report = json.loads((root / "prior" / "quality.json").read_text("utf-8"))
                if corruption == "quote":
                    report["cases"][0]["findings"][0]["source_quote"] = "invented"
                elif corruption == "cost":
                    report["known_tokens"] = 3000
                elif corruption == "unfinished":
                    report.pop("finished_at")
                else:
                    key = json.loads((root / "prior" / "blind-key.json").read_text("utf-8"))
                    key[0]["source_sha256"] = "tampered"
                    save(root / "prior" / "blind-key.json", key)
                save(root / "prior" / "quality.json", report)
                with self.assertRaises(ValueError):
                    reuse_review(root / "prior", [evidence("B777")])

    def execute(
        self, root, prior, cases, duplicates=None, budget=12000000, continue_unstarted=False
    ):
        folder = root / "experiment"
        folder.mkdir(exist_ok=True)
        save(folder / "results.json", {})
        duplicates = duplicates or {}
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
        by_id = {entry["blind_id"]: entry for entry in key}
        key += [
            {**by_id[original], "blind_id": duplicate, "trial": 99}
            for duplicate, original in duplicates.items()
        ]
        translations = {
            "known_tokens_total": 100000,
            "quota_initial": snapshot(),
            "quota_final": snapshot(),
        }
        with (
            patch(
                "tools.benchmark_quality_full.frozen_cases",
                return_value=(translations, cases, key, duplicates),
            ),
            patch("tools.benchmark_quality_full.TrialBridge", FakeReviewBridge),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return run(
                folder,
                root / "quality",
                budget,
                50,
                reuse_review_folder=prior,
                continue_unstarted=continue_unstarted,
            )

    def test_integration_only_new_cases_are_judged_and_cost_counted_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior", uncertain=True)
            report = self.execute(
                root,
                root / "prior",
                [evidence("B777"), evidence("B888", "target new")],
                {"B999": "B777"},
            )
            self.assertEqual(FakeReviewBridge.input_ids, [["B888"]])
            self.assertEqual(report["prior_review_known_tokens"], 1500)
            self.assertEqual(report["new_review_known_tokens"], 1500)
            self.assertEqual(report["known_tokens"], 3000)
            self.assertEqual(report["combined_known_tokens"], 103000)
            self.assertEqual(len(report["cases"]), 3)
            self.assertEqual(report["status"], "assessed")

    def test_reuse_only_run_makes_no_connection_or_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior")
            report = self.execute(root, root / "prior", [evidence("B777")], {"B999": "B777"})
            self.assertEqual(FakeReviewBridge.instances, [])
            self.assertEqual(report["known_tokens"], 1500)
            self.assertEqual(report["new_review_known_tokens"], 0)
            self.assertEqual(len(report["cases"]), 2)

    def test_budget_guard_includes_previous_review_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior")
            report = self.execute(
                root,
                root / "prior",
                [evidence("B777"), evidence("B888", "target new")],
                budget=117000,
            )
            self.assertEqual(FakeReviewBridge.input_ids, [])
            self.assertEqual(report["status"], "budget_or_quota_guard_reached")
            self.assertEqual(report["known_tokens"], 1500)

    def test_chained_reuse_counts_previous_calls_only_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_prior(root / "prior")
            first = self.execute(
                root, root / "prior", [evidence("B777"), evidence("B888", "target new")]
            )
            next_root = root / "next"
            next_root.mkdir()
            second = self.execute(
                next_root, root / "quality", [evidence("B101"), evidence("B102", "target new")]
            )
            self.assertEqual(FakeReviewBridge.input_ids, [["B888"]])
            self.assertEqual(second["known_tokens"], first["known_tokens"])
            self.assertEqual(second["new_review_known_tokens"], 0)
            self.assertEqual(len(second["calls"]), 2)
            self.assertEqual(second["combined_known_tokens"], 103000)

    def test_manual_continuation_first_submission_has_explicit_zero_prior_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            never_started_prior(root / "prior")
            report = self.execute(root, root / "prior", [evidence("B777")], continue_unstarted=True)
            self.assertEqual(FakeReviewBridge.input_ids, [["B777"]])
            self.assertEqual(report["calls"][0]["pass"], 1)
            self.assertEqual(report["prior_review_known_tokens"], 0)
            self.assertEqual(report["new_review_known_tokens"], 1500)
            self.assertEqual(report["prior_review_reuse"]["continued_unstarted_case_ids"], ["B777"])


if __name__ == "__main__":
    unittest.main()
