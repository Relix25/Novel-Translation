"""Explicit human-requested recovery: preserve successes, retry prior errors once.

This is a separate experiment, never an automatic restart. Further errors in
this run retain the ordinary no-retry policy. No credentials or app DB changes.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import configure_codex_logging, continuation, corpus, execute, save, sha


def prepare(previous, baseline):
    previous = Path(previous).resolve()
    recorded = json.loads((previous / "results.json").read_text("utf-8"))
    planned = copy.deepcopy(json.loads((previous / "plan.json").read_text("utf-8")))
    manifest, texts = corpus()
    if manifest != planned["corpus"]:
        raise ValueError("Frozen corpus changed; recovery refused.")
    dependencies = continuation(previous, planned, texts, preserve_failures=False)
    meta = planned["manual_continuation"]
    meta.update(
        cumulative_prior_known_tokens=recorded["known_tokens_total"],
        budget_quota_initial=baseline,
        blocked_cells=[],
        original_results_sha256=sha((previous / "results.json").read_bytes()),
        explicit_human_authorization="Explicit manual recovery invocation; retain original attempts and evidence.",
        quota_reset_note="Prior and current quota snapshots stay separate. Reset gaps are unknown; actual ceilings belong to the explicit invocation.",
    )
    planned["execution_policy"] = {
        "all_independent_cells": True,
        "on_error": "Human requested one new attempt for previously unsuccessful cells; no automatic retry after a further error.",
    }
    return planned, texts, dependencies


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--quota-baseline", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--max-delta-pp", type=float, required=True)
    parser.add_argument(
        "--unlimited-tokens",
        action="store_true",
        help="Explicit human request: remove aggregate token and quota spending ceilings; finite frozen matrix and operational watchdogs remain.",
    )
    parser.add_argument("--partition-index", type=int, default=0)
    parser.add_argument("--partition-count", type=int, default=1)
    parser.add_argument(
        "--unprocessed-only",
        action="store_true",
        help="Manual administrative continuation: preserve every recorded slot and do not retry any prior failure.",
    )
    parser.add_argument("--codex-log-dir", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.max_tokens < 1000 or args.max_delta_pp <= 0:
        parser.error("New output and positive bounded budgets required.")
    if args.partition_count < 1 or not 0 <= args.partition_index < args.partition_count:
        parser.error("Valid partition required.")
    if args.partition_count > 1 and not args.unlimited_tokens:
        parser.error(
            "Parallel partitions need an explicitly approved unbounded run; separate guards cannot enforce one shared spending ceiling."
        )
    baseline = json.loads(args.quota_baseline.read_text("utf-8"))
    planned, texts, dependencies = prepare(args.previous, baseline)
    if args.unprocessed_only:
        recorded = json.loads((args.previous / "results.json").read_text("utf-8"))

        def entry_key(t):
            return tuple(t[k] for k in ("model", "effort", "source", "target", "repeat", "kind"))

        def cell_key(t):
            return tuple(t[k] for k in ("model", "effort", "source", "target", "kind"))

        processed = {entry_key(t) for t in recorded["trials"]}
        planned["entries"] = [e for e in planned["entries"] if entry_key(e) not in processed]
        blocked = {}
        for t in recorded["trials"]:
            if t["state"] in ("failed", "interrupted"):
                blocked[cell_key(t)] = t["trial"]
            elif t["state"] == "draft":
                blocked.pop(cell_key(t), None)
        planned["manual_continuation"]["blocked_cells"] = [
            {"key": list(k), "trial": v} for k, v in blocked.items()
        ]
        planned["execution_policy"]["on_error"] = (
            "Manual administrative continuation of never-recorded slots only; latest failed cells stay excluded; no inference restart."
        )
    configurations = sorted({(e["model"], e["effort"]) for e in planned["entries"]})
    selected = set(configurations[args.partition_index :: args.partition_count])
    planned["master_entries"] = copy.deepcopy(planned["entries"])
    planned["entries"] = [e for e in planned["entries"] if (e["model"], e["effort"]) in selected]
    planned["execution_policy"].update(
        unlimited_token_budget=args.unlimited_tokens,
        partition_index=args.partition_index,
        partition_count=args.partition_count,
        measurement_mode=("concurrent partitions (%d workers)" % args.partition_count)
        if args.partition_count > 1
        else "sequential",
    )
    if args.unlimited_tokens:
        planned["manual_continuation"]["quota_reset_note"] = (
            "18 percentage points observed before reset; unobserved gap unknown. The human subsequently removed aggregate token/quota ceilings; actual limits are None, with finite planned slots and operational watchdogs."
        )
    configure_codex_logging(args.codex_log_dir)
    if args.plan_only:
        args.output.mkdir(parents=True)
        save(args.output / "plan.json", planned)
        print("Prepared remaining slots:", len(planned["entries"]))
    else:
        result = execute(
            args.output,
            planned,
            texts,
            len(planned["entries"]),
            None if args.unlimited_tokens else args.max_tokens,
            None if args.unlimited_tokens else args.max_delta_pp,
            dependencies,
            True,
        )
        print("Stop:", result["stop_reason"], "New known tokens:", result["known_tokens_total"])
