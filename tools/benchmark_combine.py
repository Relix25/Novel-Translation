"""Combine completed local experiments while retaining all attempts and provenance."""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import report, save, sha
from job_tracking import now
from tools.benchmark_report import build


def finalized(trial):
    return trial.get("state") in ("draft", "failed", "interrupted") or str(
        trial.get("state", "")
    ).startswith("not_run")


def artifact_hashes(directory):
    return {
        str(path.relative_to(directory)): sha(path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def combine(output, directories, *, snapshot=False):
    output = Path(output)
    if output.exists():
        raise ValueError("Use a new output directory; existing reports are preserved.")
    loaded = []
    for directory in map(Path, directories):
        recorded = (directory / "results.json").read_bytes()
        result = json.loads(recorded.decode("utf-8"))
        planned = json.loads((directory / "plan.json").read_text("utf-8"))
        if not result.get("finished_at") and not snapshot:
            raise ValueError("Every run must have finished before combination.")
        loaded.append((directory.resolve(), result, planned, sha(recorded)))
    first = loaded[0][2]
    if any(p["corpus"] != first["corpus"] for _, _, p, _ in loaded):
        raise ValueError("Do not combine different corpus versions.")
    output.mkdir(parents=True)
    latest = max(loaded, key=lambda item: item[1].get("finished_at") or item[1]["started_at"])
    combined = {
        "started_at": loaded[0][1]["started_at"],
        "finished_at": None if snapshot else latest[1]["finished_at"],
        "quota_initial": loaded[0][1]["quota_initial"],
        "quota_final": latest[1]["quota_final"],
        "quota_final_run": str(latest[0]),
        "stop_reason": "manual_continuation_completed",
        "trials": [],
        "runs": [],
        "note": "Every attempt is retained, including the initial interruption. Different runner versions are recorded per run; production generation modules are unchanged.",
    }
    if snapshot:
        combined.update(
            snapshot_started_at=now(),
            snapshot_frozen_at=None,
            active_runs=[],
            snapshot_artifact_sha256={},
            stop_reason="immutable_partial_snapshot_of_active_campaign",
            note="Immutable copy of finalized trial artifacts only. Active calls are omitted, not assigned zero usage. Parent workers may continue; this snapshot does not claim campaign completion.",
        )
    copied_directories = {}
    for directory, result, planned, recorded_sha in loaded:
        combined["runs"].append(
            {
                "directory": str(directory),
                "results_sha256": recorded_sha,
                "code_sha256": result.get("code_sha256"),
                "stop_reason": result.get("stop_reason"),
                "limits": result.get("limits"),
                "prior_runs": result.get("runs", []),
                "execution_policy": planned.get("execution_policy", {}),
            }
        )
        if snapshot and not result.get("finished_at"):
            omitted = [
                {
                    k: trial.get(k)
                    for k in (
                        "trial",
                        "model",
                        "effort",
                        "source",
                        "target",
                        "repeat",
                        "kind",
                        "state",
                    )
                }
                for trial in result["trials"]
                if not finalized(trial)
            ]
            combined["active_runs"].append(
                {
                    "directory": str(directory),
                    "results_sha256": recorded_sha,
                    "started_at": result.get("started_at"),
                    "finished_at": result.get("finished_at"),
                    "observed_trial_rows": len(result["trials"]),
                    "omitted_active_rows": omitted,
                    "omitted_active_row_count": len(omitted),
                }
            )
        for trial in result["trials"]:
            if snapshot and not finalized(trial):
                continue
            number = len(combined["trials"]) + 1
            old_directory = directory / ("trial-%03d" % trial["trial"])
            new_directory = output / ("trial-%03d" % number)
            before = artifact_hashes(old_directory) if snapshot else None
            shutil.copytree(old_directory, new_directory)
            if snapshot:
                copied = artifact_hashes(new_directory)
                if before != copied or before != artifact_hashes(old_directory):
                    raise ValueError(
                        "Finalized trial artifacts changed while freezing a snapshot; discard this partial output."
                    )
                combined["snapshot_artifact_sha256"].update(
                    {
                        str(new_directory.relative_to(output) / name): digest
                        for name, digest in copied.items()
                    }
                )
            copied_directories[str(old_directory.resolve())] = new_directory.resolve()
            copy = {
                **trial,
                "trial": number,
                "original_trial": trial["trial"],
                "original_directory": str(old_directory),
            }
            if trial.get("original_directory"):
                copy["prior_provenance"] = {
                    "original_directory": trial["original_directory"],
                    "original_trial": trial.get("original_trial"),
                    "prior_provenance": trial.get("prior_provenance"),
                }
            copy.setdefault(
                "measurement_mode",
                planned.get("execution_policy", {}).get("measurement_mode", "sequential"),
            )
            copy.setdefault("measurement_phase", directory.name)
            copy.setdefault("quota_shared_concurrent", copy["measurement_mode"] != "sequential")
            if trial.get("dependency_trial") is not None:
                parent = (
                    Path(trial["dependency_directory"])
                    if trial.get("dependency_directory")
                    else directory / ("trial-%03d" % trial["dependency_trial"])
                )
                if str(parent.resolve()) not in copied_directories:
                    raise ValueError(
                        "Return leg parent must be preserved before its dependent call."
                    )
                copy["original_dependency_directory"] = str(parent.resolve())
                copy["dependency_directory"] = str(copied_directories[str(parent.resolve())])
            combined["trials"].append(copy)

    def key(trial):
        return tuple(trial[k] for k in ("model", "effort", "source", "target", "repeat", "kind"))

    completed = {key(t) for t in combined["trials"] if t["state"] == "draft"}
    processed = {key(t) for t in combined["trials"]}
    pending = [
        e
        for e in first["entries"]
        if key(e)
        not in (
            processed
            if first.get("execution_policy", {}).get("all_independent_cells")
            else completed
        )
    ]
    combined["pending_cells"] = pending
    if pending and not snapshot:
        combined["stop_reason"] = "manual_continuation_incomplete"
    if snapshot:
        combined["snapshot_frozen_at"] = now()
    save(output / "plan.json", first)
    report(output, combined)
    path = output / "results.json" if snapshot else build(output)
    print(path)
    print(
        "Known tokens:",
        combined["known_tokens_total"],
        "Attempts:",
        len(combined["trials"]),
        "Pending cells:",
        len(pending),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Freeze finalized trial artifacts from active runs; do not claim campaign completion.",
    )
    args = parser.parse_args()
    combine(args.output, args.runs, snapshot=args.snapshot)
