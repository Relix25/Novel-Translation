"""Combination preserves retry provenance and cross-run return dependencies."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import EFFORTS, MODELS, corpus, plan, save, sha
from tools.benchmark_combine import combine
from tools.benchmark_quality_full import frozen_cases


class CombineBenchmarkTests(unittest.TestCase):
    def test_latest_finish_and_quota_follow_time_not_partition_order(self):
        temporary_root = Path(__file__).resolve().parents[1] / "local-benchmark-research"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            root = Path(temporary)
            directories = []
            for index, finished in enumerate(("2026-10-13T03:00:00Z", "2026-10-13T02:00:00Z")):
                directory = root / str(index)
                directory.mkdir()
                directories.append(directory)
                save(directory / "plan.json", {"corpus": {"synthetic": True}, "entries": []})
                save(
                    directory / "results.json",
                    {
                        "started_at": "2026-10-13T00:00:00Z",
                        "finished_at": finished,
                        "quota_initial": {},
                        "quota_final": {"synthetic_index": index},
                        "stop_reason": "finished",
                        "trials": [],
                    },
                )

            def fake_report(directory, result):
                result["known_tokens_total"] = 0
                save(directory / "results.json", result)

            with (
                patch("tools.benchmark_combine.report", side_effect=fake_report),
                patch("tools.benchmark_combine.build"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                combine(root / "combined", directories)
            result = json.loads((root / "combined/results.json").read_text("utf-8"))
            self.assertEqual(result["finished_at"], "2026-10-13T03:00:00Z")
            self.assertEqual(result["quota_final"], {"synthetic_index": 0})
            self.assertEqual(result["quota_final_run"], str(directories[0].resolve()))

    def test_nested_snapshot_and_two_partitions_keep_master_plan_and_dependencies(self):
        catalogue = [
            {
                "model": model,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": effort}
                    for effort in EFFORTS
                    if model != "gpt-6-luna" or effort != "ultra"
                ],
            }
            for model in MODELS
        ]
        master = plan(catalogue, mode="full", repetitions=3)
        master["corpus"] = {"fixture": "synthetic corpus identity"}
        master["execution_policy"] = {
            "all_independent_cells": True,
            "measurement_mode": "sequential",
        }
        self.assertEqual(len(master["entries"]), 408)
        temporary_root = Path(__file__).resolve().parents[1] / "local-benchmark-research"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            root = Path(temporary)
            current = root / "current"
            worker0 = root / "worker0"
            worker1 = root / "worker1"
            output = root / "final"
            base = {
                "model": "gpt-6-luna",
                "effort": "high",
                "source": "en",
                "target": "fr",
                "repeat": 1,
                "kind": "matched",
                "state": "draft",
                "usage": {"inputTokens": 100, "outputTokens": 10},
            }

            def fixture(directory, entries, planned, prior=None):
                directory.mkdir()
                for trial in entries:
                    trial_dir = directory / ("trial-%03d" % trial["trial"])
                    trial_dir.mkdir()
                    (trial_dir / "translation.txt").write_text(
                        "Synthetic " + str(trial["trial"]), encoding="utf-8"
                    )
                save(directory / "plan.json", planned)
                save(
                    directory / "results.json",
                    {
                        "started_at": "2026-10-13T00:00:00Z",
                        "finished_at": "2026-10-13T01:00:00Z",
                        "quota_initial": {},
                        "quota_final": {},
                        "stop_reason": "finished",
                        "trials": entries,
                        "runs": prior or [],
                    },
                )

            prior = [{"directory": "historical-phase4", "results_sha256": "historical-hash"}]
            fixture(
                current,
                [
                    {
                        **base,
                        "trial": 1,
                        "original_trial": 101,
                        "original_directory": "historical-phase4/trial-101",
                    },
                    {**base, "trial": 2, "source": "ko", "target": "en", "state": "failed"},
                ],
                master,
                prior,
            )
            partition_policy = {
                "all_independent_cells": True,
                "measurement_mode": "concurrent partitions",
            }
            partition = {
                **master,
                "entries": master["entries"][:2],
                "execution_policy": partition_policy,
            }
            fixture(
                worker0,
                [
                    {**base, "trial": 1, "source": "ko", "target": "en"},
                    {**base, "trial": 2, "repeat": 2},
                ],
                partition,
            )
            fixture(
                worker1,
                [
                    {
                        **base,
                        "trial": 1,
                        "source": "fr",
                        "target": "en",
                        "kind": "roundtrip",
                        "dependency_trial": 1,
                        "dependency_directory": str(current / "trial-001"),
                    },
                    {
                        **base,
                        "trial": 2,
                        "source": "fr",
                        "target": "en",
                        "kind": "roundtrip",
                        "repeat": 2,
                        "dependency_trial": 2,
                        "dependency_directory": str(worker0 / "trial-002"),
                    },
                ],
                partition,
            )

            def fake_report(directory, result):
                result["known_tokens_total"] = sum(
                    t["usage"]["inputTokens"] + t["usage"]["outputTokens"] for t in result["trials"]
                )
                save(directory / "results.json", result)

            with (
                patch("tools.benchmark_combine.report", side_effect=fake_report),
                patch("tools.benchmark_combine.build", return_value=output / "REPORT.html"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                combine(output, [current, worker0, worker1])
            result = json.loads((output / "results.json").read_text("utf-8"))
            preserved = json.loads((output / "plan.json").read_text("utf-8"))
            self.assertEqual(preserved, master)
            self.assertEqual(len(result["trials"]), 6)
            self.assertEqual(len(result["pending_cells"]), 403)
            self.assertEqual(result["runs"][0]["prior_runs"], prior)
            self.assertEqual(result["trials"][0]["prior_provenance"]["original_trial"], 101)
            self.assertEqual(
                result["trials"][4]["dependency_directory"], str((output / "trial-001").resolve())
            )
            self.assertEqual(
                result["trials"][5]["dependency_directory"], str((output / "trial-004").resolve())
            )
            self.assertEqual(
                result["trials"][4]["original_dependency_directory"],
                str((current / "trial-001").resolve()),
            )
            self.assertEqual(result["trials"][0]["measurement_mode"], "sequential")
            self.assertFalse(result["trials"][0]["quota_shared_concurrent"])
            self.assertEqual(result["trials"][2]["measurement_mode"], "concurrent partitions")
            self.assertTrue(result["trials"][2]["quota_shared_concurrent"])
            self.assertEqual(result["known_tokens_total"], 660)

    def test_explicit_snapshot_excludes_active_rows_and_freezes_closed_artifacts(self):
        catalogue = [
            {
                "model": model,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": effort}
                    for effort in EFFORTS
                    if model != "gpt-6-luna" or effort != "ultra"
                ],
            }
            for model in MODELS
        ]
        master = plan(catalogue, mode="full", repetitions=3)
        manifest, texts = corpus()
        master["corpus"] = manifest
        master["execution_policy"] = {
            "all_independent_cells": True,
            "measurement_mode": "sequential",
        }
        temporary_root = Path(__file__).resolve().parents[1] / "local-benchmark-research"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            root = Path(temporary)
            current = root / "current"
            worker0 = root / "worker0"
            worker1 = root / "worker1"
            output = root / "snapshot"
            base = {
                "model": "gpt-6-luna",
                "effort": "high",
                "source": "en",
                "target": "fr",
                "repeat": 1,
                "kind": "matched",
                "state": "draft",
                "usage": {"inputTokens": 100, "outputTokens": 10},
                "source_sha256": sha(texts["en"].encode()),
            }

            def fixture(directory, entries, active=False):
                directory.mkdir()
                for trial in entries:
                    trial_dir = directory / ("trial-%03d" % trial["trial"])
                    trial_dir.mkdir()
                    if trial["state"] == "draft":
                        candidate = directory.name + " synthetic translation"
                        (trial_dir / "translation.txt").write_text(candidate, encoding="utf-8")
                        trial["translation_sha256"] = sha(candidate.encode())
                        save(
                            trial_dir / "raw-response.json",
                            {"response": {"segments": [{"id": "segment", "text": candidate}]}},
                        )
                    else:
                        (trial_dir / "call.json").write_text("{}", encoding="utf-8")
                save(
                    directory / "plan.json",
                    {
                        **master,
                        "execution_policy": {
                            "all_independent_cells": True,
                            "measurement_mode": "concurrent partitions" if active else "sequential",
                        },
                    },
                )
                save(
                    directory / "results.json",
                    {
                        "started_at": "2026-10-13T00:00:00Z",
                        "finished_at": None if active else "2026-10-13T01:00:00Z",
                        "quota_initial": {},
                        "quota_final": {},
                        "stop_reason": None if active else "finished",
                        "trials": entries,
                    },
                )

            fixture(current, [{**base, "trial": 1}])
            fixture(
                worker0,
                [
                    {**base, "trial": 1, "repeat": 2},
                    {
                        **base,
                        "trial": 2,
                        "repeat": 3,
                        "state": "starting",
                        "usage": {"inputTokens": 11},
                    },
                ],
                True,
            )
            parent_text = (current / "trial-001" / "translation.txt").read_text("utf-8")
            fixture(
                worker1,
                [
                    {
                        **base,
                        "trial": 1,
                        "source": "fr",
                        "target": "en",
                        "kind": "roundtrip",
                        "dependency_trial": 1,
                        "dependency_directory": str(current / "trial-001"),
                        "source_sha256": sha(parent_text.encode()),
                    },
                    {
                        **base,
                        "trial": 2,
                        "source": "ko",
                        "target": "fr",
                        "state": "failed",
                        "usage": None,
                    },
                    {
                        **base,
                        "trial": 3,
                        "source": "ja",
                        "target": "en",
                        "state": "inprogress",
                        "usage": None,
                    },
                ],
                True,
            )
            original_hashes = {
                str(path): sha(path.read_bytes())
                for directory in (current, worker0, worker1)
                for path in directory.rglob("*")
                if path.is_file()
            }

            def fake_report(directory, result):
                result["known_tokens_total"] = sum(
                    sum((t.get("usage") or {}).get(k, 0) for k in ("inputTokens", "outputTokens"))
                    for t in result["trials"]
                )
                save(directory / "results.json", result)

            with (
                patch("tools.benchmark_combine.report", side_effect=fake_report),
                patch("tools.benchmark_combine.build") as legacy_build,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(ValueError, "finished"):
                    combine(root / "unsafe", [current, worker0, worker1])
                combine(output, [current, worker0, worker1], snapshot=True)
                legacy_build.assert_not_called()
            result = json.loads((output / "results.json").read_text("utf-8"))
            self.assertIsNone(result["finished_at"])
            self.assertEqual(result["stop_reason"], "immutable_partial_snapshot_of_active_campaign")
            self.assertTrue(result["snapshot_frozen_at"])
            self.assertEqual(
                [t["state"] for t in result["trials"]], ["draft", "draft", "draft", "failed"]
            )
            self.assertIsNone(result["trials"][3]["usage"])
            self.assertEqual(result["known_tokens_total"], 330)
            self.assertEqual(
                [run["omitted_active_row_count"] for run in result["active_runs"]], [1, 1]
            )
            self.assertEqual(
                result["active_runs"][0]["omitted_active_rows"][0]["state"], "starting"
            )
            self.assertEqual(
                result["active_runs"][1]["omitted_active_rows"][0]["state"], "inprogress"
            )
            self.assertEqual(
                result["active_runs"][0]["results_sha256"],
                original_hashes[str(worker0 / "results.json")],
            )
            self.assertEqual(
                result["trials"][2]["dependency_directory"], str((output / "trial-001").resolve())
            )
            self.assertEqual(json.loads((output / "plan.json").read_text("utf-8")), master)
            self.assertEqual(len(result["pending_cells"]), 404)
            self.assertEqual(
                original_hashes, {path: sha(Path(path).read_bytes()) for path in original_hashes}
            )
            for relative, digest in result["snapshot_artifact_sha256"].items():
                self.assertEqual(sha((output / relative).read_bytes()), digest)
            reviewed, cases, key, duplicates = frozen_cases(output)
            self.assertEqual(len(key), 4)  # Three step readings plus the return-chain reading.
            self.assertEqual(len(reviewed["trials"]), 4)
            bad = {**result, "snapshot_frozen_at": None}
            save(output / "results.json", bad)
            with self.assertRaisesRegex(ValueError, "explicitly frozen"):
                frozen_cases(output)
            save(output / "results.json", result)
            (output / "trial-001" / "translation.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                frozen_cases(output)


if __name__ == "__main__":
    unittest.main()
