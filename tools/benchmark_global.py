"""Present every recorded route, configuration and repetition without inventing data."""

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import corpus, save, sha
from job_tracking import now

EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
MODELS = ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra")
NAMES = {"gpt-6-luna": "Luna", "gpt-6.1-sol": "Sol 6.1", "gpt-6-astra": "Astra"}
ROUTES = [
    ("en", "fr", "English → French"),
    ("zh", "fr", "Chinese → French"),
    ("zh", "en", "Chinese → English"),
    ("ko", "fr", "Korean → French"),
    ("ko", "en", "Korean → English"),
    ("ja", "fr", "Japanese → French"),
    ("ja", "en", "Japanese → English"),
    ("fr", "en", "Return French → English"),
]


def slot_key(entry):
    """A retry is another attempt at the same preregistered slot."""
    return tuple(entry.get(k) for k in ("model", "effort", "source", "target", "repeat", "kind"))


def selected_successes(rows):
    selected = {}
    for row in rows:
        if row["state"] == "draft":
            selected[slot_key(row)] = row
    return list(selected.values())


def coverage(plan, rows):
    planned = {slot_key(e) for e in plan["entries"]}
    recorded = {slot_key(r) for r in rows} & planned
    successful = {slot_key(r) for r in selected_successes(rows)} & planned
    return {
        "planned_slots": len(planned),
        "recorded_slots": len(recorded),
        "successful_slots": len(successful),
        "unrecorded_slots": len(planned - recorded),
        "unresolved_slots": len(planned - successful),
        "recorded_attempts": len(rows),
        "successful_calls": sum(r["state"] == "draft" for r in rows),
        "additional_retry_records": sum(slot_key(r) in planned for r in rows) - len(recorded),
        "unplanned_records": sum(slot_key(r) not in planned for r in rows),
    }


def quota_identity(window):
    return (
        window["bucket"],
        window["window"],
        window.get("duration_minutes"),
        window.get("resets_at"),
    )


def quota_label(identity):
    bucket, window, duration, reset = identity
    return bucket + "/" + window + " · reset " + str(reset if reset is not None else "unknown")


def token_count(trial):
    usage = trial.get("usage") or {}
    if type(usage.get("inputTokens")) is int and type(usage.get("outputTokens")) is int:
        return usage["inputTokens"] + usage["outputTokens"]
    return None


def all_rows(results, quality):
    assessed = {c["trial"]: c for c in quality if c.get("audit_kind") != "end_to_end_chain"}
    rows = []
    for t in results["trials"]:
        usage = t.get("usage") or {}
        q = assessed.get(t["trial"])
        row = {
            k: t.get(k)
            for k in (
                "trial",
                "model",
                "effort",
                "source",
                "target",
                "repeat",
                "kind",
                "state",
                "seconds",
                "error",
            )
        }
        row.update(
            measurement_mode=t.get("measurement_mode", "unspecified"),
            measurement_phase=t.get("measurement_phase", t.get("phase")),
            quota_shared_concurrent=t.get("quota_shared_concurrent"),
        )
        row.update(
            tokens_known=token_count(t),
            usage_complete=t.get("call_state", t["state"]) in ("completed", "draft")
            and token_count(t) is not None,
            tokens_lower_bound=sum(
                usage[k] for k in ("inputTokens", "outputTokens") if type(usage.get(k)) is int
            ),
            **{
                key: usage.get(key)
                for key in (
                    "inputTokens",
                    "cachedInputTokens",
                    "outputTokens",
                    "reasoningOutputTokens",
                )
            },
            quality_status=q.get("verdict")
            if q
            else ("not_assessed" if t["state"] == "draft" else "no_validated_output"),
            critical=q["counts"]["critical"] if q else None,
            major=q["counts"]["major"] if q else None,
            minor=q["counts"]["minor"] if q else None,
            uncertain=q["counts"]["uncertain"] if q else None,
            fluency=q.get("fluency") if q else None,
            register=q.get("register") if q else None,
            quality_assessment_id=q.get("assessment_reused_from", q.get("blind_id")) if q else None,
            quota_observations=t.get("quota_delta", []),
        )
        rows.append(row)
    selected_ids = {r["trial"] for r in selected_successes(rows)}
    attempts = {}
    for row in rows:
        key = slot_key(row)
        attempts[key] = attempts.get(key, 0) + 1
        row["slot_attempt_number"] = attempts[key]
        row["selected_for_summary"] = row["trial"] in selected_ids
    return rows


def cells(plan, rows):
    keys = sorted(
        {(e["model"], e["effort"], e["source"], e["target"]) for e in plan["entries"]},
        key=lambda k: (
            MODELS.index(k[0]),
            EFFORTS.index(k[1]),
            [(a, b) for a, b, _ in ROUTES].index(k[2:]),
        ),
    )
    output = []
    for model, effort, source, target in keys:
        planned = [
            e
            for e in plan["entries"]
            if (e["model"], e["effort"], e["source"], e["target"])
            == (model, effort, source, target)
        ]
        own = [
            r
            for r in rows
            if (r["model"], r["effort"], r["source"], r["target"])
            == (model, effort, source, target)
        ]
        representative = selected_successes(own)
        good = [r for r in representative if r["usage_complete"]]
        tokens = [r["tokens_known"] for r in good]
        seconds = [r["seconds"] for r in good if r["seconds"] is not None]
        quality = [
            r for r in representative if r["quality_status"] in ("clean", "errors", "uncertain")
        ]
        distinct = coverage({"entries": planned}, own)
        output.append(
            {
                "model": model,
                "effort": effort,
                "source": source,
                "target": target,
                "slots_planned": distinct["planned_slots"],
                "slots_recorded": distinct["recorded_slots"],
                "completed": distinct["successful_slots"],
                "completed_calls": distinct["successful_calls"],
                "attempt_records": len(own),
                "unresolved_slots": distinct["unresolved_slots"],
                "additional_retry_records": distinct["additional_retry_records"],
                "failures": sum(r["state"] in ("failed", "interrupted") for r in own),
                "skipped": sum(r["state"].startswith("not_run") for r in own),
                "known_tokens_all_attempts": sum(r["tokens_lower_bound"] for r in own),
                "cached_input_tokens_known": sum(r["cachedInputTokens"] or 0 for r in own),
                "successful_cold_calls": sum(r["cachedInputTokens"] == 0 for r in good),
                "attempts_with_unknown_usage": sum(
                    r["tokens_known"] is None and r["state"] in ("draft", "failed", "interrupted")
                    for r in own
                ),
                "successful_tokens_median": statistics.median(tokens) if tokens else None,
                "successful_tokens_n": len(tokens),
                "successful_seconds_n": len(seconds),
                "successful_tokens_min": min(tokens) if tokens else None,
                "successful_tokens_max": max(tokens) if tokens else None,
                "successful_seconds_median": statistics.median(seconds) if seconds else None,
                "successful_seconds_min": min(seconds) if seconds else None,
                "successful_seconds_max": max(seconds) if seconds else None,
                "quality_assessed": len(quality),
                "quality_unique_assessments": len({r["quality_assessment_id"] for r in quality}),
                **{
                    s + "_mean": statistics.mean(r[s] for r in quality) if quality else None
                    for s in ("critical", "major", "minor", "uncertain")
                },
            }
        )
    return output


def configuration_totals(rows, plan=None):
    output = []
    configs = {(r["model"], r["effort"]) for r in (plan["entries"] if plan else rows)}
    for model, effort in sorted(configs, key=lambda k: (MODELS.index(k[0]), EFFORTS.index(k[1]))):
        own = [r for r in rows if (r["model"], r["effort"]) == (model, effort)]
        attempts = [r for r in own if r["state"] in ("draft", "failed", "interrupted", "starting")]
        windows = {quota_identity(w) for r in attempts for w in r["quota_observations"]}
        observations = []
        for identity in sorted(windows, key=str):
            bucket, window, duration, reset = identity
            intervals = [
                next((w for w in r["quota_observations"] if quota_identity(w) == identity), None)
                for r in attempts
            ]
            known = [
                w["delta_pp"] for w in intervals if w is not None and w["delta_pp"] is not None
            ]
            observations.append(
                {
                    "bucket": bucket,
                    "window": window,
                    "sum_comparable_intervals_pp": sum(known) if known else None,
                    "duration_minutes": duration,
                    "resets_at": reset,
                    "comparable_intervals": len(known),
                    "attempted_calls": len(attempts),
                    "sum_may_double_count_concurrent_usage": any(
                        r.get("quota_shared_concurrent") for r in attempts
                    ),
                    "note": "Shared-account observation, rounded and possibly delayed; not an exclusive configuration charge.",
                }
            )
        output.append(
            {
                "model": model,
                "effort": effort,
                "attempted_calls": len(attempts),
                "completed": sum(r["state"] == "draft" for r in own),
                "successful_slots": len(selected_successes(own)),
                "slots_skipped": sum(r["state"].startswith("not_run") for r in own),
                "known_tokens_all_attempts": sum(r["tokens_lower_bound"] for r in own)
                if attempts
                else None,
                "incomplete_usage_calls": sum(not r["usage_complete"] for r in attempts),
                "quota_observations": observations,
            }
        )
    return output


def audit_artifacts(folder, results):
    """Check frozen artifacts; requesting an effort is not independent server proof."""
    _, texts = corpus()
    audits = []
    for trial in results["trials"]:
        if trial["state"] != "draft":
            continue
        directory = folder / ("trial-%03d" % trial["trial"])
        flags = []
        try:
            source = texts[trial["source"]]
            if trial["kind"] == "roundtrip":
                parent = (
                    Path(trial["dependency_directory"])
                    if trial.get("dependency_directory")
                    else folder / ("trial-%03d" % trial["dependency_trial"])
                )
                source = (parent / "translation.txt").read_text("utf-8")
            candidate = (directory / "translation.txt").read_text("utf-8")
            call = json.loads((directory / "call.json").read_text("utf-8"))
            raw = json.loads((directory / "raw-response.json").read_text("utf-8"))
            checks = {
                "source_hash": sha(source.encode()) == trial["source_sha256"],
                "translation_hash": sha(candidate.encode()) == trial["translation_sha256"],
                "response_matches_draft": "\n\n".join(
                    s["text"] for s in raw["response"]["segments"]
                )
                == candidate,
                "prompt_hash": sha((directory / "prompt.txt").read_text("utf-8").encode())
                == trial["prompt_sha256"],
                "ephemeral": call.get("thread", {}).get("ephemeral") is True,
                "model_not_rerouted": not call.get("rerouted")
                and call.get("start_model") in (None, trial["model"]),
            }
            if call.get("turn_request"):
                checks["requested_model_and_effort"] = all(
                    call["turn_request"].get(k) == trial[k] for k in ("model", "effort")
                )
            flags = [k for k, v in checks.items() if not v]
        except Exception as error:
            flags = ["artifact_read_error: " + str(error)]
        audits.append(
            {
                "trial": trial["trial"],
                "flags": flags,
                "effort_evidence": "acknowledged per-turn request; no independent effort echo",
            }
        )
    return audits


def build(folder, quality_file=None):
    folder = Path(folder)
    r = json.loads((folder / "results.json").read_text("utf-8"))
    r["report_snapshot_at"] = now()
    account_file = folder / "final-account-observation.json"
    if account_file.exists():
        r["final_account_observation"] = json.loads(account_file.read_text("utf-8"))
    plan = json.loads((folder / "plan.json").read_text("utf-8"))
    quality = []
    if quality_file:
        q = json.loads(Path(quality_file).read_text("utf-8"))
        if "quality" in q:
            if q.get("input_results_sha256") != sha((folder / "results.json").read_bytes()):
                raise ValueError("Quality analysis does not belong to these exact frozen results.")
            quality = q["quality"]
            r["quality_review"] = q.get("quality_review")
        elif "cases" in q:
            if q.get("input_results_sha256") != sha((folder / "results.json").read_bytes()):
                raise ValueError("Quality review does not belong to these exact frozen results.")
            keyfile = Path(quality_file).parent / "blind-key.json"
            if not keyfile.exists():
                keyfile = folder / "blind-key.json"
            key = {k["blind_id"]: k for k in json.loads(keyfile.read_text("utf-8"))}
            quality = [
                {
                    **c,
                    "trial": key[c["blind_id"]]["trial"],
                    "audit_kind": key[c["blind_id"]].get("audit_kind", "translation_fidelity"),
                    "source_segment_id": key[c["blind_id"]].get("source_segment_id"),
                    "source_language": key[c["blind_id"]].get("source_language"),
                    "target_language": key[c["blind_id"]].get("target_language"),
                    "counts": {
                        s: sum(f["severity"] == s for f in c["findings"])
                        for s in ("critical", "major", "minor", "uncertain")
                    },
                }
                for c in q["cases"]
            ]
            r["quality_review"] = {
                k: q.get(k)
                for k in (
                    "status",
                    "known_tokens",
                    "prior_review_known_tokens",
                    "new_review_known_tokens",
                    "usage_complete",
                    "combined_known_tokens",
                    "combined_quota_total",
                    "model",
                    "effort",
                    "calls",
                    "identical_case_reuse",
                    "review_case_counts",
                )
            }
    rows = all_rows(r, quality)
    audits = audit_artifacts(folder, r)
    invalid = {a["trial"] for a in audits if a["flags"]}
    if invalid:
        raise ValueError("Frozen artifact audit failed for trials: " + str(sorted(invalid)))
    grouped = cells(plan, rows)
    mode_groups = [
        {"measurement_mode": mode, **cell}
        for mode in sorted({row["measurement_mode"] for row in rows})
        for cell in cells(plan, [row for row in rows if row["measurement_mode"] == mode])
        if cell["attempt_records"]
    ]
    comparisons = []
    for source, target, label in ROUTES:
        own = [
            t
            for t in r["trials"]
            if (t["source"], t["target"]) == (source, target) and t["state"] == "draft"
        ]
        comparisons.append(
            {
                "source": source,
                "target": target,
                "completed": len(own),
                "visible_prompt_hash_count": len({t.get("prompt_sha256") for t in own}),
                "source_hash_count": len({t.get("source_sha256") for t in own}),
                "same_frozen_input_expected": source != "fr",
                "cold_calls": sum(
                    (t.get("usage") or {}).get("cachedInputTokens") == 0 for t in own
                ),
                "cached_calls": sum(
                    ((t.get("usage") or {}).get("cachedInputTokens") or 0) > 0 for t in own
                ),
            }
        )
    out = folder / "global"
    out.mkdir(exist_ok=True)
    save(
        out / "all-data.json",
        {
            "snapshot_at": r["report_snapshot_at"],
            "phase_finished": bool(r.get("finished_at")),
            "stop_reason": r.get("stop_reason"),
            "snapshot_frozen_at": r.get("snapshot_frozen_at"),
            "active_runs": r.get("active_runs"),
            "planned_slots": len(plan["entries"]),
            "unsupported_configurations": plan.get("unsupported", []),
            "rows": rows,
            "cells": grouped,
            "quality": quality,
            "configuration_totals": configuration_totals(rows, plan),
            "coverage": coverage(plan, rows),
            "quota_reset_evidence": r.get("quota_reset_evidence"),
            "historical_pilot": r.get("historical_pilot"),
            "final_account_observation": r.get("final_account_observation"),
            "metrics_by_measurement_mode": mode_groups,
            "quota_total": r.get("quota_total"),
            "known_tokens": r.get("known_tokens_total"),
            "quality_review": r.get("quality_review"),
            "artifact_audit": audits,
            "input_comparability": comparisons,
            "note": "Missing counters and unassessed quality are null, never zero. Failed attempts are retained.",
        },
    )

    def write_csv(name, data):
        if not data:
            return
        with (out / name).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, list(data[0]))
            writer.writeheader()
            for row in data:
                writer.writerow(
                    {
                        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()
                    }
                )

    write_csv("all-calls.csv", rows)
    write_csv("all-cells.csv", grouped)
    write_csv("configuration-totals.csv", configuration_totals(rows, plan))
    write_csv("metrics-by-measurement-mode.csv", mode_groups)
    write_csv("artifact-audit.csv", audits)
    write_csv("input-comparability.csv", comparisons)
    findings = [
        {
            "trial": q["trial"],
            "blind_id": q["blind_id"],
            "audit_kind": q.get("audit_kind", "translation_fidelity"),
            "source_segment_id": q.get("source_segment_id"),
            **f,
        }
        for q in quality
        for f in q["findings"]
    ]
    write_csv("quality-findings.csv", findings)
    write_csv(
        "quality-assessments.csv",
        [
            {
                k: q.get(k)
                for k in (
                    "trial",
                    "blind_id",
                    "audit_kind",
                    "source_segment_id",
                    "verdict",
                    "fluency",
                    "register",
                    "last_pass",
                    "assessment_reused_from",
                    "review_reused_from",
                    "assessment",
                    "counts",
                )
            }
            for q in quality
        ],
    )
    plot(out, plan, rows, grouped, quality)
    render(out, r, plan, rows, grouped, quality)
    print(
        "Global report:",
        out / "GLOBAL.html",
        "Recorded:",
        len(rows),
        "Planned:",
        len(plan["entries"]),
    )
    return rows, grouped


def plot(out, plan, rows, grouped, quality=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "figure.facecolor": "#f6f8fb",
            "axes.facecolor": "#f6f8fb",
            "svg.fonttype": "none",
        }
    )
    configurations = sorted(
        {(e["model"], e["effort"]) for e in plan["entries"]},
        key=lambda k: (MODELS.index(k[0]), EFFORTS.index(k[1])),
    )
    lookup = {(c["model"], c["effort"], c["source"], c["target"]): c for c in grouped}

    def finish(fig, name):
        for extension in ("png", "svg", "pdf"):
            fig.savefig(out / (name + "." + extension), dpi=160, bbox_inches="tight")
        plt.close(fig)

    selected_ids = {r["trial"] for r in selected_successes(rows)}
    chained = [
        q
        for q in quality or []
        if q.get("audit_kind") == "end_to_end_chain" and q["trial"] in selected_ids
    ]
    trials = {r["trial"]: r for r in rows}
    fig, ax = plt.subplots(figsize=(13, max(5, len(configurations) * 0.4 + 2)))
    coverage_values = np.full((len(configurations), len(ROUTES)), np.nan)
    for i, (model, effort) in enumerate(configurations):
        for j, (source, target, _) in enumerate(ROUTES):
            cell = lookup.get((model, effort, source, target))
            if cell:
                coverage_values[i, j] = cell["completed"] / cell["slots_planned"]
                ax.text(
                    j,
                    i,
                    str(cell["completed"])
                    + "/"
                    + str(cell["slots_planned"])
                    + (
                        " · R" + str(cell["additional_retry_records"])
                        if cell["additional_retry_records"]
                        else ""
                    ),
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if coverage_values[i, j] > 0.6 else "#26384b",
                )
    cmap = plt.get_cmap("Greens").copy()
    cmap.set_bad("#e7ebf0")
    ax.imshow(coverage_values, cmap=cmap, vmin=0, vmax=1, aspect="auto", zorder=-1)
    ax.set_yticks(range(len(configurations)), [NAMES[m] + " " + e for m, e in configurations])
    ax.set_xticks(
        range(len(ROUTES)),
        [
            "EN → FR",
            "ZH → FR",
            "ZH → EN",
            "KO → FR",
            "KO → EN",
            "JA → FR",
            "JA → EN",
            "FR → EN\n(return)",
        ],
    )
    ax.set_title(
        "Coverage of the preregistered matrix\nUnique successful / planned slots · R = additional attempts",
        loc="left",
        pad=20,
    )
    fig.text(
        0.06,
        -0.01,
        "Recovery attempts stay in costs and the journal. Each slot counts once in coverage.",
        fontsize=10,
    )
    fig.tight_layout()
    finish(fig, "coverage-by-route")
    values = np.full((len(configurations), 4), np.nan)
    nvalues = []
    for i, (model, effort) in enumerate(configurations):
        own = [
            q
            for q in chained
            if (trials[q["trial"]]["model"], trials[q["trial"]]["effort"]) == (model, effort)
        ]
        nvalues.append(len(own))
        if own:
            for j, severity in enumerate(("critical", "major", "minor", "uncertain")):
                values[i, j] = statistics.mean(q["counts"][severity] for q in own)
    fig, ax = plt.subplots(figsize=(10, max(5, len(configurations) * 0.35 + 2)))
    cmap = plt.get_cmap("YlOrBr").copy()
    cmap.set_bad("#e7ebf0")
    finite = values[np.isfinite(values)]
    chain_maximum = max([1] + finite.tolist())
    ax.imshow(values, cmap=cmap, vmin=0, vmax=chain_maximum, aspect="auto")
    ax.set_yticks(range(len(configurations)), [NAMES[m] + " " + e for m, e in configurations])
    ax.set_xticks(range(4), ["Critical", "Major", "Minor", "Uncertain"])
    for i in range(len(configurations)):
        for j in range(4):
            ax.text(
                j,
                i,
                "—" if np.isnan(values[i, j]) else f"{values[i, j]:.1f}\nn={nvalues[i]}",
                ha="center",
                va="center",
                fontsize=9,
                color="white"
                if np.isfinite(values[i, j]) and values[i, j] > chain_maximum * 0.6
                else "#26384b",
            )
    ax.set_title(
        "Initial English → French → final English\nChain fidelity · mean findings, separate from step errors",
        loc="left",
        pad=20,
    )
    fig.text(
        0.06,
        -0.01,
        "— = unassessed chain. Restored initial text can coexist with an intermediate translation error.",
        fontsize=10,
    )
    fig.tight_layout()
    finish(fig, "roundtrip-chain-quality")
    for metric, name, title, unit in [
        (
            "successful_tokens_median",
            "tokens-by-route",
            "Tokens for every configuration and route",
            "tokens · median of completed calls",
        ),
        (
            "successful_seconds_median",
            "duration-by-route",
            "Duration for every configuration and route",
            "seconds · median of completed calls",
        ),
        (
            "major_mean",
            "quality-by-route",
            "Quality across all routes · cited major findings",
            "mean major findings per assessed draft",
        ),
        (
            "critical_mean",
            "quality-critical-by-route",
            "Critical findings across all routes",
            "mean critical findings per assessed draft",
        ),
        (
            "minor_mean",
            "quality-minor-by-route",
            "Minor findings across all routes",
            "mean minor findings per assessed draft",
        ),
        (
            "uncertain_mean",
            "quality-uncertain-by-route",
            "Uncertain findings across all routes",
            "mean uncertain findings per assessed draft",
        ),
    ]:
        values = np.full((len(configurations), len(ROUTES)), np.nan)
        for i, (model, effort) in enumerate(configurations):
            for j, (source, target, _) in enumerate(ROUTES):
                c = lookup.get((model, effort, source, target))
                if c and c[metric] is not None:
                    values[i, j] = c[metric]
        finite = values[np.isfinite(values)]
        maximum = max(1, float(max(finite))) if len(finite) else 1
        fig, ax = plt.subplots(figsize=(13, max(5, len(configurations) * 0.4 + 2)))
        cmap = plt.get_cmap("YlOrBr" if name.startswith("quality") else "Blues").copy()
        cmap.set_bad("#e7ebf0")
        ax.imshow(values, cmap=cmap, vmin=0, vmax=maximum, aspect="auto")
        ax.set_yticks(
            range(len(configurations)),
            [NAMES[m] + " · " + e.capitalize() for m, e in configurations],
        )
        ax.set_xticks(
            range(len(ROUTES)),
            [
                "EN → FR",
                "ZH → FR",
                "ZH → EN",
                "KO → FR",
                "KO → EN",
                "JA → FR",
                "JA → EN",
                "FR → EN\n(return)",
            ],
        )
        for i, (model, effort) in enumerate(configurations):
            for j, (source, target, _) in enumerate(ROUTES):
                value = values[i, j]
                c = lookup.get((model, effort, source, target), {})
                n = (
                    c.get("quality_assessed", 0)
                    if name.startswith("quality")
                    else c.get(
                        "successful_tokens_n"
                        if name.startswith("tokens")
                        else "successful_seconds_n",
                        0,
                    )
                )
                count = (
                    ("n=" + str(n) + " / j=" + str(c.get("quality_unique_assessments", 0)))
                    if name.startswith("quality")
                    else "n=" + str(n)
                )
                label = (
                    "—"
                    if np.isnan(value)
                    else (
                        (
                            f"{value:,.0f}".replace(",", " ")
                            if name.startswith("tokens")
                            else f"{value:.1f}"
                        )
                        + "\n"
                        + count
                    )
                )
                ax.text(
                    j,
                    i,
                    label,
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if np.isfinite(value) and value > maximum * 0.6 else "#26384b",
                )
        ax.set_title(title + "\n" + unit, loc="left", pad=20)
        fig.text(
            0.08,
            -0.01,
            "— = unavailable; n = drafts; j = distinct judgments. No reported finding does not prove a perfect translation.",
            fontsize=10,
        )
        fig.tight_layout()
        finish(fig, name)

    for source, target, label in ROUTES:
        fig, axes = plt.subplots(1, 2, figsize=(14, max(6, len(configurations) * 0.34 + 2)))
        for axis, metric, title in [
            (axes[0], "tokens_known", "Final tokens per repeat"),
            (axes[1], "seconds", "Duration per repeat · seconds"),
        ]:
            extent = []
            for i, (model, effort) in enumerate(configurations):
                own = [
                    r
                    for r in selected_successes(rows)
                    if (r["model"], r["effort"], r["source"], r["target"])
                    == (model, effort, source, target)
                    and r["usage_complete"]
                    and r[metric] is not None
                ]
                values = [r[metric] for r in own]
                extent.extend(values)
                color = {
                    "gpt-6-luna": "#2165a8",
                    "gpt-6.1-sol": "#7955aa",
                    "gpt-6-astra": "#158074",
                }[model]
                if not values:
                    axis.text(0, i, " —", va="center", color="#758393")
                    continue
                axis.plot([min(values), max(values)], [i, i], color=color, linewidth=2)
                axis.scatter(
                    [statistics.median(values)], [i], marker="|", s=230, color=color, zorder=4
                )
                for row in own:
                    axis.scatter(
                        [row[metric]],
                        [i + (row["repeat"] - 2) * 0.08],
                        marker="D" if (row["cachedInputTokens"] or 0) > 0 else "o",
                        s=25,
                        color=color,
                        alpha=0.7,
                        zorder=3,
                    )
            axis.set_yticks(
                range(len(configurations)), [NAMES[m] + " " + e for m, e in configurations]
            )
            axis.invert_yaxis()
            axis.set_xlim(0, max(extent or [1]) * 1.12)
            axis.set_ylim(len(configurations) - 0.5, -0.5)
            axis.set_title(title, loc="left")
            axis.grid(axis="x", alpha=0.15)
            axis.set_axisbelow(True)
        fig.suptitle(label + " · every configuration", x=0.05, ha="left", fontsize=16)
        fig.text(
            0.05,
            -0.01,
            "Points = repeats; line = median and min–max range, not a confidence interval. Diamond = partly cached input. — = missing final measurement.",
            fontsize=10,
        )
        fig.tight_layout()
        finish(fig, "detail-" + source + "-" + target)

    if len(rows) <= 40:
        labels = [
            str(r["trial"]).zfill(3)
            + " · "
            + r["source"].upper()
            + "→"
            + r["target"].upper()
            + " · "
            + NAMES[r["model"]]
            + " "
            + r["effort"]
            for r in rows
        ]
        fig, axes = plt.subplots(1, 2, figsize=(15, max(6, len(rows) * 0.36 + 2)))
        for column, key, title in [
            (0, "tokens_known", "Known tokens de toutes les attempts"),
            (1, "seconds", "Duration of every attempt"),
        ]:
            ax = axes[column]
            numbers = [r[key] if r[key] is not None else np.nan for r in rows]
            good = [v for v in numbers if np.isfinite(v)]
            maximum = max(good or [1])
            for i, (row, value) in enumerate(zip(rows, numbers)):
                color = "#257c91" if row["state"] == "draft" else "#d79a48"
                if np.isfinite(value):
                    ax.barh(i, value, color=color, height=0.7)
                text = (
                    "unknown"
                    if not np.isfinite(value)
                    else (
                        f"{value:,.0f}".replace(",", " ")
                        if key == "tokens_known"
                        else f"{value:.1f} s"
                    )
                )
                if row["state"] != "draft":
                    text += " · " + row["state"]
                ax.text(
                    (value if np.isfinite(value) else 0) + maximum * 0.01,
                    i,
                    text,
                    va="center",
                    fontsize=9,
                )
            ax.set_yticks(
                range(len(rows)),
                labels if column == 0 else [str(r["trial"]).zfill(3) for r in rows],
            )
            ax.invert_yaxis()
            ax.set_xlim(0, maximum * 1.3)
            ax.set_title(title, loc="left")
            ax.set_xlabel("Tokens" if key == "tokens_known" else "Seconds")
            ax.grid(axis="x", alpha=0.15)
            ax.set_axisbelow(True)
        fig.text(
            0.05,
            -0.01,
            "Every call is shown, including interruption and refusal. Languages, contexts and cache differ: this chart does not rank models.",
            fontsize=10,
        )
        fig.tight_layout()
        finish(fig, "every-attempt")

    totals = configuration_totals(rows, plan)
    fig, axes = plt.subplots(1, 2, figsize=(14, max(5, len(totals) * 0.33 + 2)))
    labels = [NAMES[t["model"]] + " " + t["effort"] for t in totals]
    y = np.arange(len(totals))
    axes[0].barh(
        y,
        [
            t["known_tokens_all_attempts"] if t["known_tokens_all_attempts"] is not None else np.nan
            for t in totals
        ],
        color="#257c91",
    )
    for i, total in enumerate(totals):
        if total["known_tokens_all_attempts"] is None:
            axes[0].text(0, i, "  not executed", va="center", fontsize=9)
        elif total["incomplete_usage_calls"]:
            axes[0].text(
                total["known_tokens_all_attempts"], i, "  total incomplet", va="center", fontsize=9
            )
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Known tokens · every call, including failures")
    axes[0].set_title("Configuration totals · varying coverage", loc="left")
    pairs = sorted({quota_identity(w) for t in totals for w in t["quota_observations"]}, key=str)
    axes[1].set_yticks(y, labels)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Quota percentage points · sum of comparable intervals")
    axes[1].set_title("Shared account observations · uncertain attribution", loc="left")
    for series, identity in enumerate(pairs):
        for i, total in enumerate(totals):
            observation = next(
                (w for w in total["quota_observations"] if quota_identity(w) == identity), None
            )
            if observation is None:
                continue
            value = observation["sum_comparable_intervals_pp"]
            if value is not None:
                axes[1].barh(
                    i + series * 0.15,
                    value,
                    height=0.14 if len(pairs) > 1 else 0.6,
                    color=["#ce8b37", "#257c91"][series % 2],
                    label=quota_label(identity) if i == 0 else None,
                )
            axes[1].text(
                value or 0,
                i + series * 0.15,
                "  "
                + ("unknown" if value is None else str(value) + " pt")
                + " · "
                + str(observation["comparable_intervals"])
                + "/"
                + str(observation["attempted_calls"])
                + " intervalles",
                va="center",
                fontsize=9,
            )
    axes[1].set_xlim(
        0,
        max(
            [w["sum_comparable_intervals_pp"] or 0 for t in totals for w in t["quota_observations"]]
            + [1]
        )
        * 1.6,
    )
    if len(pairs) > 1:
        axes[1].legend()
    fig.text(
        0.04,
        -0.02,
        "Partial observation sums: no exclusive attribution. Concurrent calls can count the same change twice.\nA displayed zero does not prove zero use. Distinct quota windows stay separate.",
        fontsize=10,
    )
    fig.tight_layout()
    finish(fig, "configuration-cost")

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    colors = {"gpt-6-luna": "#2165a8", "gpt-6.1-sol": "#7955aa", "gpt-6-astra": "#158074"}
    for model in MODELS:
        own = [r for r in rows if r["model"] == model and r["seconds"] is not None]
        axes[0].scatter(
            [r["trial"] for r in own],
            [r["seconds"] for r in own],
            color=colors[model],
            label=NAMES[model],
            s=30,
        )
    bad = [r for r in rows if r["state"] in ("failed", "interrupted") and r["seconds"] is not None]
    axes[0].scatter(
        [r["trial"] for r in bad],
        [r["seconds"] for r in bad],
        marker="x",
        s=70,
        color="#ba432e",
        label="Refusal / interruption",
    )
    axes[0].set_ylabel("Seconds per call")
    axes[0].set_title("Duration and quota in observed trial order", loc="left")
    axes[0].legend(ncol=4, fontsize=10)
    windows = sorted({quota_identity(w) for r in rows for w in r["quota_observations"]}, key=str)
    for series, identity in enumerate(windows):
        readings = [
            (r["trial"], w)
            for r in rows
            for w in r["quota_observations"]
            if quota_identity(w) == identity
        ]
        for timing, key, marker in [
            (-0.1, "before_used_percent", "o"),
            (0.1, "after_used_percent", "x"),
        ]:
            usable = [(i, w[key]) for i, w in readings if w.get(key) is not None]
            axes[1].scatter(
                [i + timing for i, v in usable],
                [v for i, v in usable],
                marker=marker,
                s=25,
                color=["#ce8b37", "#257c91"][series % 2],
                label=quota_label(identity) + (" before" if timing < 0 else " after"),
            )
    axes[1].set_xlabel("Chronological attempt number")
    axes[1].set_ylabel("Used account quota · %")
    if windows:
        axes[1].legend(fontsize=10)
    for axis in axes:
        axis.grid(alpha=0.15)
        axis.set_axisbelow(True)
    axes[1].set_xlim(0.5, max([r["trial"] for r in rows] + [1]) + 0.5)
    fig.text(
        0.05,
        -0.015,
        "Each quota point is a raw shared account reading. No smoothing or exclusive model attribution. Durations include measured refusals.",
        fontsize=10,
    )
    fig.tight_layout()
    finish(fig, "order-and-account-quota")


def render(out, r, plan, rows, grouped, quality):
    """Render complete frozen evidence without inventing missing measurements."""
    from tools.report_html import details, document, figure, findings, table

    summary = coverage(plan, rows)
    review = r.get("quality_review") or {}
    body = "<h1>Novel benchmark — complete evidence</h1>"
    body += "<p>This is a frozen report, not a live counter. Missing measurements are marked —. Drafts and AI verdicts remain unapproved.</p>"
    body += table(
        [
            "Snapshot UTC",
            "Finished UTC",
            "Stop reason",
            "Successful slots",
            "Planned slots",
            "Additional attempts",
        ],
        [
            [
                r.get("report_snapshot_at"),
                r.get("finished_at"),
                r.get("stop_reason"),
                summary["successful_slots"],
                summary["planned_slots"],
                summary["additional_retry_records"],
            ]
        ],
    )
    body += '<nav><a href="#matrix">Configurations and routes</a> · <a href="#calls">Every attempt</a> · <a href="#quality">Cited quality findings</a></nav>'
    body += "<h2>Known consumption and account observations</h2>"
    body += table(
        ["Translation tokens", "Review tokens", "Review usage complete", "Known combined tokens"],
        [
            [
                r.get("known_tokens_total"),
                review.get("known_tokens"),
                review.get("usage_complete"),
                review.get("combined_known_tokens"),
            ]
        ],
    )
    body += "<p>Known totals are lower bounds when final counters are absent. Input includes cached tokens; output includes reasoning. Neither component is added twice. Historical pilot costs are separate.</p>"
    for title, value in [
        ("Historical pilot (only when recorded)", r.get("historical_pilot")),
        ("Account quota observations", r.get("quota_total")),
        ("Quota reset evidence", r.get("quota_reset_evidence")),
        ("Last account observation", r.get("final_account_observation")),
        ("Review usage and provenance", r.get("quality_review")),
    ]:
        body += details(title, value)
    body += "<p>Quota belongs to the shared account. Rounding, delayed readings, other work and overlapping concurrent calls prevent exact attribution to a configuration. Windows and resets remain separate; the gap before a reset is unknown.</p>"
    body += figure(out, "configuration-cost", "Known cost of each configuration")
    body += figure(out, "order-and-account-quota", "Observed order, duration and account quota")
    body += '<h2 id="matrix">Every configuration and route</h2>'
    body += figure(out, "coverage-by-route", "Unique planned slots and retry records")
    body += table(
        [
            "Model",
            "Effort",
            "Source",
            "Target",
            "Completed",
            "Planned",
            "Attempts",
            "Token median",
            "Duration median",
            "Critical",
            "Major",
            "Minor",
            "Uncertain",
        ],
        [
            [
                c.get(k)
                for k in (
                    "model",
                    "effort",
                    "source",
                    "target",
                    "completed",
                    "slots_planned",
                    "attempt_records",
                    "successful_tokens_median",
                    "successful_seconds_median",
                    "critical_mean",
                    "major_mean",
                    "minor_mean",
                    "uncertain_mean",
                )
            ]
            for c in grouped
        ],
    )
    for name, title in [
        ("tokens-by-route", "Final tokens by route"),
        ("duration-by-route", "Measured duration by route"),
        ("quality-by-route", "Cited major findings"),
        ("quality-critical-by-route", "Cited critical findings"),
        ("quality-minor-by-route", "Cited minor findings"),
        ("quality-uncertain-by-route", "Uncertain findings"),
    ]:
        body += figure(out, name, title)
    body += "<p>Repeated observations describe one familiar preamble per language. Min–max ranges are not confidence intervals. Mixed sequential/concurrent load does not measure intrinsic model speed. No reported finding is not proof of a perfect translation.</p>"
    for source, target, label in ROUTES:
        body += figure(out, f"detail-{source}-{target}", label + " — repetitions and range")
    body += "<h2>English → French → English chain</h2>"
    body += figure(
        out, "roundtrip-chain-quality", "End-to-end findings, separate from each translation step"
    )
    body += "<p>The return leg uses its actual generated French source. The chain compares initial and final English. Step and chain findings are distinct and are never added together: errors may propagate, overlap or compensate.</p>"
    body += '<h2 id="calls">Every recorded attempt</h2><label>Filter calls: <input id="filter" placeholder="Language, model, effort, state"></label>'
    body += table(
        [
            "Trial",
            "Model",
            "Effort",
            "Route",
            "Repeat",
            "Mode / phase",
            "State",
            "Known tokens",
            "Final usage",
            "Seconds",
            "Quality",
            "Error",
        ],
        [
            [
                x.get("trial"),
                x.get("model"),
                x.get("effort"),
                f"{x.get('source')} → {x.get('target')}",
                x.get("repeat"),
                f"{x.get('measurement_mode')} / {x.get('measurement_phase')}",
                x.get("state"),
                x.get("tokens_lower_bound"),
                x.get("usage_complete"),
                x.get("seconds"),
                x.get("quality_status"),
                x.get("error"),
            ]
            for x in rows
        ],
        table_id="calls-table",
    )
    body += figure(out, "every-attempt", "Every attempt, including refusals and interruptions")
    for x in rows:
        body += details(f"Trial {x.get('trial')} — complete counters and provenance", x)
    body += '<h2 id="quality">Every cited quality assessment</h2>' + findings(quality)
    body += "<h2>Evidence and limitations</h2><p>The actual supplied source governs fidelity. Institutional reference variants can differ. Exact citations demonstrate evidence attachment, not the linguistic correctness of a verdict. Sol High findings can include judge/family bias and need bilingual human validation. Acknowledged model/effort requests do not independently attest the effort actually executed by the server. A refused call is unavailable, never an invented quality score.</p>"
    for name, title in [
        ("all-calls.csv", "Every attempt"),
        ("all-cells.csv", "Every configuration and route"),
        ("all-data.json", "Complete report data"),
        ("artifact-audit.csv", "Artifact fingerprints"),
        ("input-comparability.csv", "Source and prompt comparability"),
        ("metrics-by-measurement-mode.csv", "Separate measurement modes"),
        ("quality-findings.csv", "Exact cited findings"),
        ("quality-cases.csv", "Quality cases"),
    ]:
        if (out / name).is_file():
            body += f'<p><a href="{name}">{title}</a></p>'
    body += '<script>document.getElementById("filter").addEventListener("input",function(){const q=this.value.toLocaleLowerCase();document.querySelectorAll("#calls-table tbody tr").forEach(r=>r.hidden=!r.textContent.toLocaleLowerCase().includes(q))});</script>'
    (out / "GLOBAL.html").write_text(
        document("Novel benchmark — complete evidence", body), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--quality", type=Path)
    args = parser.parse_args()
    build(args.folder, args.quality)
