"""Analyze frozen translation/review evidence; never call a model or change evidence."""

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import save, sha
from job_tracking import now
from tools.benchmark_global import (
    EFFORTS,
    MODELS,
    NAMES,
    ROUTES,
    all_rows,
    cells,
    coverage,
    selected_successes,
)

SEVERITIES = ("critical", "major", "minor", "uncertain")
VERDICTS = ("clean", "errors", "uncertain")


def failure_category(error):
    text = (error or "").lower()
    if any(
        s in text for s in ("regurg", "safety_violation", "translation blocked", "content filter")
    ):
        return "content_filter_or_explicit_refusal"
    if any(
        s in text
        for s in (
            "routing",
            "transport",
            "host disappeared",
            "activity",
            "timed out",
            "timeout",
            "connection",
            "stdout",
            "pipe",
            "disconnect",
        )
    ):
        return "transport_or_execution_failure"
    if any(s in text for s in ("quota", "budget", "token limit")):
        return "administrative_limit"
    if any(s in text for s in ("schema", "invalid json", "validation")):
        return "response_validation"
    return "unclassified_failure"


def quality_summary(quality):
    return {
        "assessed": len(quality),
        "verdicts": {v: sum(q["verdict"] == v for q in quality) for v in VERDICTS},
        "findings": {s: sum(q["counts"][s] for q in quality) for s in SEVERITIES},
        "distinct_judgments": len(
            {q.get("assessment_reused_from") or q["blind_id"] for q in quality}
        ),
    }


def matched_efforts(rows, quality):
    """Keep repeated passage positions paired; never compare unmatched pools."""
    chosen = selected_successes(rows)
    step = {q["trial"]: q for q in quality if q.get("audit_kind") != "end_to_end_chain"}
    chain = {q["trial"]: q for q in quality if q.get("audit_kind") == "end_to_end_chain"}
    output = []
    for model in MODELS:
        available = sorted({r["effort"] for r in rows if r["model"] == model}, key=EFFORTS.index)
        for lower, higher in zip(available, available[1:]):
            for audit_kind in ("translation_fidelity", "end_to_end_chain"):
                selected = [
                    r
                    for r in chosen
                    if r["model"] == model
                    and (
                        (r["source"] != "fr" and r["kind"] != "roundtrip")
                        if audit_kind == "translation_fidelity"
                        else r["kind"] == "roundtrip"
                    )
                ]

                def index(effort):
                    return {
                        (r["source"], r["target"], r["repeat"], r["kind"]): r
                        for r in selected
                        if r["effort"] == effort
                    }

                left, right = index(lower), index(higher)
                common = sorted(left.keys() & right.keys())
                verdicts = step if audit_kind == "translation_fidelity" else chain
                assessed = [
                    (left[k], right[k])
                    for k in common
                    if left[k]["trial"] in verdicts
                    and right[k]["trial"] in verdicts
                    and verdicts[left[k]["trial"]]["source_sha256"]
                    == verdicts[right[k]["trial"]]["source_sha256"]
                ]
                # Durations/costs of return calls alone do not measure the complete chain.
                comparable = [
                    (left[k], right[k])
                    for k in common
                    if audit_kind == "translation_fidelity"
                    and left[k].get("source_sha256") == right[k].get("source_sha256")
                    and bool(left[k].get("source_sha256"))
                    and left[k].get("measurement_mode") == right[k].get("measurement_mode")
                    and left[k].get("measurement_mode") not in (None, "unspecified")
                    and left[k].get("cachedInputTokens") is not None
                    and right[k].get("cachedInputTokens") is not None
                    and (left[k]["cachedInputTokens"] > 0) == (right[k]["cachedInputTokens"] > 0)
                ]
                cost = [
                    (a, b)
                    for a, b in comparable
                    if a["usage_complete"] and b["usage_complete"] and a["tokens_known"] > 0
                ]
                timed = [
                    (a, b)
                    for a, b in comparable
                    if a["usage_complete"]
                    and b["usage_complete"]
                    and a["seconds"] is not None
                    and b["seconds"] is not None
                    and a["seconds"] > 0
                ]
                record = {
                    "model": model,
                    "lower": lower,
                    "higher": higher,
                    "audit_kind": audit_kind,
                    "common_successful_positions": len(common),
                    "quality_pairs": len(assessed),
                    "same_mode_cache_final_cost_pairs": len(cost),
                    "same_mode_cache_duration_pairs": len(timed),
                    "paired_tokens_percent_median": statistics.median(
                        (b["tokens_known"] / a["tokens_known"] - 1) * 100 for a, b in cost
                    )
                    if cost
                    else None,
                    "paired_duration_percent_median": statistics.median(
                        (b["seconds"] / a["seconds"] - 1) * 100 for a, b in timed
                    )
                    if timed
                    else None,
                    "quality_pairs_details": [],
                }
                for severity in SEVERITIES:
                    differences = [
                        verdicts[b["trial"]]["counts"][severity]
                        - verdicts[a["trial"]]["counts"][severity]
                        for a, b in assessed
                    ]
                    record[severity + "_mean_change"] = (
                        statistics.mean(differences) if differences else None
                    )
                    record[severity + "_lower_higher_equal"] = [
                        sum(d < 0 for d in differences),
                        sum(d > 0 for d in differences),
                        sum(d == 0 for d in differences),
                    ]
                record["quality_pairs_details"] = [
                    {
                        "lower_trial": a["trial"],
                        "higher_trial": b["trial"],
                        "position": list((a["source"], a["target"], a["repeat"], a["kind"])),
                        "source_sha256": verdicts[a["trial"]]["source_sha256"],
                        "counts_lower": verdicts[a["trial"]]["counts"],
                        "counts_higher": verdicts[b["trial"]]["counts"],
                    }
                    for a, b in assessed
                ]
                output.append(record)
    return output


def analyze(folder, quality_file):
    folder, quality_file = Path(folder), Path(quality_file)
    raw = (folder / "results.json").read_bytes()
    result = json.loads(raw.decode("utf-8"))
    qraw = quality_file.read_bytes()
    review = json.loads(qraw.decode("utf-8"))
    if review.get("input_results_sha256") != sha(raw):
        raise ValueError("Review does not match these exact results.")
    plan = json.loads((folder / "plan.json").read_text("utf-8"))
    key = {
        k["blind_id"]: k
        for k in json.loads((quality_file.parent / "blind-key.json").read_text("utf-8"))
    }
    trials = {t["trial"]: t for t in result["trials"]}
    quality = []
    for case in review["cases"]:
        metadata = key[case["blind_id"]]
        if metadata["translation_sha256"] != trials[metadata["trial"]].get("translation_sha256"):
            raise ValueError("Review candidate fingerprint differs from the trial.")
        quality.append(
            {
                **case,
                **metadata,
                "counts": {
                    s: sum(f["severity"] == s for f in case["findings"]) for s in SEVERITIES
                },
            }
        )
    rows = all_rows(result, quality)
    # Visible source hashes are required for actual paired comparisons.
    for row in rows:
        row["source_sha256"] = trials[row["trial"]].get("source_sha256")
    selected = selected_successes(rows)
    selected_ids = {r["trial"] for r in selected}
    step = [
        q
        for q in quality
        if q.get("audit_kind") != "end_to_end_chain" and q["trial"] in selected_ids
    ]
    chain = [
        q
        for q in quality
        if q.get("audit_kind") == "end_to_end_chain" and q["trial"] in selected_ids
    ]
    grouped = cells(plan, rows)
    for cell in grouped:
        own_ids = {
            row["trial"]
            for row in selected
            if (row["model"], row["effort"], row["source"], row["target"])
            == (cell["model"], cell["effort"], cell["source"], cell["target"])
        }
        cell["quality_summary"] = quality_summary([q for q in step if q["trial"] in own_ids])
    historical = result.get("historical_pilot") or {}
    account_file = folder / "final-account-observation.json"
    account_observation = (
        json.loads(account_file.read_text("utf-8")) if account_file.exists() else None
    )

    def summary(subplan, own):
        ids = {r["trial"] for r in selected_successes(own)}
        assessed = [q for q in step if q["trial"] in ids]
        actual = [r for r in own if r["state"] in ("draft", "failed", "interrupted", "starting")]
        return {
            **coverage(subplan, own),
            "actual_attempts": len(actual),
            "unknown_final_usage_attempts": sum(not r["usage_complete"] for r in actual),
            "known_tokens_all_attempts": sum(r["tokens_lower_bound"] for r in own),
            "quality": quality_summary(assessed),
            "failure_categories": dict(
                Counter(
                    failure_category(r["error"])
                    for r in own
                    if r["state"] in ("failed", "interrupted")
                )
            ),
        }

    configs = []
    for model, effort in sorted(
        {(e["model"], e["effort"]) for e in plan["entries"]},
        key=lambda k: (MODELS.index(k[0]), EFFORTS.index(k[1])),
    ):
        own = [r for r in rows if (r["model"], r["effort"]) == (model, effort)]
        subplan = {
            "entries": [e for e in plan["entries"] if (e["model"], e["effort"]) == (model, effort)]
        }
        configs.append(
            {
                "model": model,
                "effort": effort,
                **summary(subplan, own),
                "chain_quality": quality_summary(
                    [q for q in chain if q["trial"] in {r["trial"] for r in own}]
                ),
            }
        )
    routes = []
    for source, target, label in ROUTES:
        own = [r for r in rows if (r["source"], r["target"]) == (source, target)]
        subplan = {
            "entries": [
                e for e in plan["entries"] if (e["source"], e["target"]) == (source, target)
            ]
        }
        routes.append({"source": source, "target": target, "label": label, **summary(subplan, own)})
    return {
        "created_at": now(),
        "results_sha256": sha(raw),
        "quality_sha256": sha(qraw),
        "translation_stop_reason": result.get("stop_reason"),
        "translation_finished_at": result.get("finished_at"),
        "quality_status": review.get("status"),
        "global": summary(plan, rows),
        "cells": grouped,
        "configurations": configs,
        "routes": routes,
        "quality_step": quality_summary(step),
        "quality_chain": quality_summary(chain),
        "quality_cases": quality,
        "effort_comparisons": matched_efforts(rows, quality),
        "translation_known_tokens": result.get("known_tokens_total"),
        "review_known_tokens": review.get("known_tokens"),
        "review_usage_complete": review.get("usage_complete"),
        "campaign_known_tokens": result.get("known_tokens_total", 0)
        + review.get("known_tokens", 0),
        "historical_pilot": historical,
        "historical_known_tokens_separate": historical.get("combined_known_tokens"),
        "translation_token_components_known": {
            key: sum(row[key] for row in rows if type(row.get(key)) is int)
            for key in ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens")
        },
        "final_account_observation": account_observation,
        "final_account_observation_sha256": sha(account_file.read_bytes())
        if account_file.exists()
        else None,
        "quota_reset_evidence": result.get("quota_reset_evidence"),
        "quota_total": result.get("quota_total"),
        "review_quota_final": review.get("quota_final"),
        "limitations": [
            "One familiar institutional preamble per language; three repeats are not three independent texts.",
            "AI review is provisional, with one judge family and possible memorization/family bias; no human approval.",
            "Only common successful source-identical positions are paired; unmatched failures create selection bias.",
            "Cost/duration pairing additionally requires the same declared measurement mode and cache presence; hidden context, cache amount and load can still differ.",
            "Shared rounded quota with a reset gap cannot yield exact global or per-configuration consumption.",
        ],
    }


def plots(out, data):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})

    def finish(fig, name):
        for extension in ("png", "svg", "pdf"):
            fig.savefig(out / (name + "." + extension), dpi=160, bbox_inches="tight")
        plt.close(fig)

    configs = data["configurations"]
    fig, ax = plt.subplots(figsize=(13, max(6, len(configs) * 0.4)))
    y = np.arange(len(configs))
    left = np.zeros(len(configs))
    for kind, label, color in [
        ("clean", "No finding reported", "#23836d"),
        ("errors", "Judge-reported findings", "#d78232"),
        ("uncertain", "Uncertain", "#ccaf59"),
        ("unassessed", "Unassessed output", "#83a6c2"),
        ("unavailable", "No completed output", "#e1e5eb"),
    ]:
        values = []
        for c in configs:
            counts = c["quality"]["verdicts"]
            values.append(
                counts[kind]
                if kind in VERDICTS
                else c["successful_slots"] - c["quality"]["assessed"]
                if kind == "unassessed"
                else c["unresolved_slots"]
            )
        ax.barh(y, values, left=left, label=label, color=color)
        left += values
    ax.set_yticks(y, [NAMES[c["model"]] + " " + c["effort"] for c in configs])
    ax.invert_yaxis()
    ax.set_xlabel("Unique planned slots")
    ax.set_title("Availability and verdicts for every configuration", loc="left")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=3)
    fig.text(
        0.02,
        -0.04,
        "Retries do not inflate coverage. No reported finding does not imply perfection. Provisional AI review.",
        fontsize=9,
    )
    fig.tight_layout()
    finish(fig, "availability-and-quality")
    pairs = [p for p in data["effort_comparisons"] if p["audit_kind"] == "translation_fidelity"]
    fig, axes = plt.subplots(1, 2, figsize=(14, max(6, len(pairs) * 0.38)))
    labels = [NAMES[p["model"]] + " " + p["lower"] + " → " + p["higher"] for p in pairs]
    y = np.arange(len(pairs))
    for ax, metric, count, title in [
        (
            axes[0],
            "paired_tokens_percent_median",
            "same_mode_cache_final_cost_pairs",
            "Median token change · %",
        ),
        (axes[1], "major_mean_change", "quality_pairs", "Mean change in major findings"),
    ]:
        values = [p[metric] if p[metric] is not None else np.nan for p in pairs]
        ax.barh(y, values, color=["#cc8050" if v > 0 else "#287f86" for v in values])
        ax.axvline(0, color="#777", lw=0.7)
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.grid(axis="x", alpha=0.15)
        for i, p in enumerate(pairs):
            ax.text(0, i, " n=" + str(p[count]), va="center", fontsize=8)
    fig.suptitle("Adjacent efforts · common direct positions only", x=0.04, ha="left")
    fig.text(
        0.03,
        -0.015,
        "Change = higher effort minus lower effort. Small samples on one text; no causal or significance claim.\nTokens: compatible mode and cache presence. Quality: identical actual source. Returns and chains excluded.",
        fontsize=9,
    )
    fig.tight_layout()
    finish(fig, "paired-effort-effects")


def render(out, data):
    """Summarize matched evidence while keeping costs, refusals and chains separate."""
    from tools.report_html import details, document, figure, findings, table

    body = "<h1>Novel benchmark — conclusions</h1>"
    body += "<p>Descriptive evidence for the measured passages; AI verdicts are provisional and do not grant chapter approval. — means unavailable.</p>"
    body += table(
        ["Snapshot UTC", "Review status", "Translation stop reason"],
        [[data.get("created_at"), data.get("quality_status"), data.get("translation_stop_reason")]],
    )
    body += details("Unique slot coverage and attempts", data["global"])
    body += "<h2>Known cost</h2>"
    body += table(
        [
            "Translation tokens",
            "Review tokens",
            "Campaign tokens",
            "Review usage complete",
            "Separate historical pilot tokens",
        ],
        [
            [
                data.get("translation_known_tokens"),
                data.get("review_known_tokens"),
                data.get("campaign_known_tokens"),
                data.get("review_usage_complete"),
                data.get("historical_known_tokens_separate"),
            ]
        ],
    )
    body += details(
        "Known token components (not additive to totals)",
        data.get("translation_token_components_known"),
    )
    body += details("Historical pilot, when recorded", data.get("historical_pilot") or None)
    body += details("Account quota observations", data.get("quota_total"))
    body += details("Quota reset evidence", data.get("quota_reset_evidence"))
    body += details("Last account observation", data.get("final_account_observation"))
    body += "<p>Missing final counters make known totals lower bounds. Cached input and reasoning output are already included. Shared account quota cannot be attributed exactly to each model; concurrent intervals may overlap and reset gaps are unknown.</p>"
    body += "<h2>Availability and provisional quality</h2>"
    body += figure(out, "availability-and-quality", "Unique slots and available assessments")
    for section, records in [
        ("Configurations", data["configurations"]),
        ("Routes", data["routes"]),
    ]:
        body += f"<h3>{section}</h3>"
        for record in records:
            label = " · ".join(
                str(record.get(k, "")) for k in ("model", "effort", "source", "target")
            )
            body += details(label, record)
    body += "<h3>Each configuration within each route</h3>"
    body += table(
        ["Model", "Effort", "Source", "Target", "Completed", "Planned", "Quality summary"],
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
                    "quality_summary",
                )
            ]
            for c in data["cells"]
        ],
    )
    body += "<h2>Matched effort comparisons</h2>"
    body += figure(
        out,
        "paired-effort-effects",
        "Higher effort minus lower effort on common successful positions",
    )
    body += "<p>Quality pairs require the same actual source. Cost/duration pairs also require compatible load mode and cache presence. Refusals remove observations and can bias the successful subset. Small samples on one known text establish neither causality nor a stable ranking.</p>"
    body += table(
        [
            "Model",
            "Lower",
            "Higher",
            "Scope",
            "Quality pairs",
            "Mean major change",
            "Cost pairs",
            "Median token change %",
            "Duration pairs",
            "Median duration change %",
        ],
        [
            [
                p.get(k)
                for k in (
                    "model",
                    "lower",
                    "higher",
                    "audit_kind",
                    "quality_pairs",
                    "major_mean_change",
                    "same_mode_cache_final_cost_pairs",
                    "paired_tokens_percent_median",
                    "same_mode_cache_duration_pairs",
                    "paired_duration_percent_median",
                )
            ]
            for p in data["effort_comparisons"]
        ],
    )
    for pair in data["effort_comparisons"]:
        body += details(
            f"{pair['model']} · {pair['lower']} → {pair['higher']} · {pair['audit_kind']} — matched positions",
            pair,
        )
    body += "<h2>Translation steps and end-to-end chains</h2>"
    body += details("Step quality", data["quality_step"])
    body += details("English → French → English chain quality", data["quality_chain"])
    body += "<p>Chain findings compare initial and final English and stay separate from each step's fidelity to its actual source. Step errors cannot be added to chain errors: losses can propagate, overlap or compensate.</p>"
    body += "<h2>Every cited verdict</h2>" + findings(data["quality_cases"])
    body += "<h2>Interpretation limits</h2>"
    body += details("Recorded limitations", data.get("limitations"))
    body += "<p>Three repetitions of one familiar preamble are not three independent texts. One AI judge may misread evidence, favor a model family or remember a reference. Exact citations do not prove a correct verdict or severity. Bilingual reading is required before approval. Requested efforts are recorded in acknowledged requests; actual server execution is not independently confirmed.</p>"
    body += '<p><a href="../global/GLOBAL.html">Complete evidence and all attempts</a> · <a href="CONCLUSIONS.json">Analysis JSON</a> · <a href="effort-comparisons.csv">Matched comparison CSV</a></p>'
    (out / "CONCLUSIONS.html").write_text(
        document("Novel benchmark — conclusions", body), encoding="utf-8"
    )


def build(folder, quality_file):
    data = analyze(folder, quality_file)
    out = Path(folder) / "conclusions"
    out.mkdir(exist_ok=True)
    save(out / "CONCLUSIONS.json", data)
    comparisons = data["effort_comparisons"]
    with (out / "effort-comparisons.csv").open("w", newline="", encoding="utf-8-sig") as file:
        fields = list(comparisons[0]) if comparisons else []
        writer = csv.DictWriter(file, fields)
        writer.writeheader()
        for row in comparisons:
            writer.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                    for k, v in row.items()
                }
            )
    plots(out, data)
    render(out, data)
    print(out / "CONCLUSIONS.html")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("quality", type=Path)
    args = parser.parse_args()
    build(args.folder, args.quality)
