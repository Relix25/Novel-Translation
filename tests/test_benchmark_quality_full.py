"""Synthetic review safety checks; no real model, credentials or quota are used."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import corpus, save, sha
from tools.benchmark_quality_full import frozen_cases, run


def snapshot(used=29):
    return {
        "available": True,
        "buckets": [
            {
                "id": "codex",
                "windows": [
                    {
                        "key": "primary",
                        "used_percent": used,
                        "remaining_percent": 100 - used,
                        "duration_minutes": 10080,
                        "resets_at": 2000000000,
                        "stale": False,
                        "observed_at": "2026-10-13T00:00:00+00:00",
                    }
                ],
            }
        ],
    }


class FakeReviewBridge:
    instances = []
    input_ids = []
    used = 29
    invalid_first = False

    def __init__(self, directory):
        self.current = None
        self.instances.append(self)

    def quota(self):
        return snapshot(self.used)

    def connection(self):
        return {"connected": True}

    def close(self):
        pass

    def generate(self, prompt, schema, model, effort, directory, timeout, on_event):
        data = json.loads(prompt.split("\nData: ", 1)[1])
        ids = [c["blind_id"] for c in data["cases"]]
        self.input_ids.append(ids)
        usage = {"inputTokens": 1000, "outputTokens": 500}
        self.current = {"usage": usage, "seconds": 1}
        on_event({"kind": "usage", "usage": usage})
        cases = []
        for case in data["cases"]:
            uncertain = case["blind_id"] == "B000" and "prior_uncertainties" not in data
            findings = (
                [
                    {
                        "severity": "uncertain",
                        "category": "meaning",
                        "source_quote": "source",
                        "translation_quote": "target",
                        "explanation": "Synthetic uncertainty.",
                        "suggested_edit": "",
                    }
                ]
                if uncertain
                else []
            )
            if self.invalid_first and len(self.input_ids) == 1:
                findings = [
                    {
                        "severity": "major",
                        "category": "meaning",
                        "source_quote": "invented quotation",
                        "translation_quote": "target",
                        "explanation": "Synthetic invalid citation.",
                        "suggested_edit": "",
                    }
                ]
            cases.append(
                {
                    "blind_id": case["blind_id"],
                    "verdict": "uncertain" if uncertain else ("errors" if findings else "clean"),
                    "findings": findings,
                    "fluency": "natural",
                    "register": "preserved",
                    "assessment": "Synthetic test assessment.",
                }
            )
        return {
            "response": {"cases": cases, "limitations": "Synthetic test only."},
            "token_usage": usage,
            "ephemeral": True,
        }


class FullReviewTests(unittest.TestCase):
    def setUp(self):
        FakeReviewBridge.instances = []
        FakeReviewBridge.input_ids = []
        FakeReviewBridge.used = 29
        FakeReviewBridge.invalid_first = False

    def exercise(self, used=29, invalid=False):
        FakeReviewBridge.used = used
        FakeReviewBridge.invalid_first = invalid
        cases = [
            {
                "blind_id": "B%03d" % n,
                "source": "source " + str(n),
                "translation": "target " + str(n),
            }
            for n in range(13)
        ]
        key = [
            {"blind_id": c["blind_id"], "trial": n + 1, "audit_kind": "translation_fidelity"}
            for n, c in enumerate(cases)
        ]
        translations = {
            "known_tokens_total": 100000,
            "quota_initial": snapshot(),
            "quota_final": snapshot(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "experiment"
            folder.mkdir()
            (folder / "results.json").write_text("{}", encoding="utf-8")
            with (
                patch(
                    "tools.benchmark_quality_full.frozen_cases",
                    return_value=(translations, cases, key, {}),
                ),
                patch("tools.benchmark_quality_full.TrialBridge", FakeReviewBridge),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                return run(folder, root / "quality", 12000000, 50)

    def test_second_pass_contains_only_uncertain_cases(self):
        result = self.exercise()
        self.assertEqual([len(ids) for ids in FakeReviewBridge.input_ids], [12, 1, 1])
        self.assertEqual(FakeReviewBridge.input_ids[1], ["B000"])
        self.assertEqual(result["known_tokens"], 4500)
        self.assertEqual(result["combined_known_tokens"], 104500)
        self.assertEqual(result["status"], "assessed")

    def test_global_account_budget_prevents_any_review_inference(self):
        result = self.exercise(used=79)
        self.assertEqual(FakeReviewBridge.input_ids, [])
        self.assertEqual(result["status"], "budget_or_quota_guard_reached")
        self.assertEqual(result["known_tokens"], 0)

    def test_invalid_quotes_are_not_retried_or_given_invented_verdicts(self):
        result = self.exercise(invalid=True)
        self.assertEqual([len(ids) for ids in FakeReviewBridge.input_ids], [12, 1])
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["calls"][0]["state"], "failed")
        self.assertEqual(result["known_tokens"], 3000)
        self.assertFalse(result["usage_complete"])
        self.assertEqual(result["status"], "partially_assessed_with_failures")

    def test_return_and_end_to_end_cases_preserve_distinct_sources_and_ids(self):
        manifest, texts = corpus()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            entries = []
            for index, source, target, kind, text, translated, segment in [
                (
                    1,
                    "en",
                    "fr",
                    "matched",
                    texts["en"],
                    "Synthetic French intermediate.",
                    "original-en-id",
                ),
                (
                    2,
                    "fr",
                    "en",
                    "roundtrip",
                    "Synthetic French intermediate.",
                    "Synthetic returned English.",
                    "generated-fr-id",
                ),
            ]:
                directory = folder / ("trial-%03d" % index)
                directory.mkdir()
                (directory / "translation.txt").write_text(translated, encoding="utf-8")
                save(
                    directory / "raw-response.json",
                    {"response": {"segments": [{"id": segment, "text": translated}]}},
                )
                entries.append(
                    {
                        "trial": index,
                        "source": source,
                        "target": target,
                        "kind": kind,
                        "state": "draft",
                        "source_sha256": sha(text.encode()),
                        "translation_sha256": sha(translated.encode()),
                        "dependency_trial": 1 if index == 2 else None,
                    }
                )
            save(folder / "plan.json", {"corpus": manifest})
            save(folder / "results.json", {"finished_at": "finished", "trials": entries})
            result, cases, key, duplicates = frozen_cases(folder)
            self.assertEqual(len(cases), 3)
            chain = next(c for c in cases if c["audit_kind"] == "end_to_end_chain")
            direct_return = next(
                c
                for c in cases
                if c["audit_kind"] == "translation_fidelity" and c["source_language"] == "fr"
            )
            self.assertEqual(chain["source"], texts["en"])
            self.assertEqual(chain["source_segment_id"], "original-en-id")
            self.assertEqual(direct_return["source"], "Synthetic French intermediate.")
            self.assertEqual(direct_return["source_segment_id"], "generated-fr-id")
            self.assertEqual(chain["translation"], direct_return["translation"])


if __name__ == "__main__":
    unittest.main()
