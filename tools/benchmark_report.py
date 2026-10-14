"Build an offline results report and a separate blind review packet."

import argparse
import csv
import json
import random
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import corpus, save


def build(folder):
    folder = Path(folder)
    result = json.loads((folder / "results.json").read_text("utf-8"))
    planned = json.loads((folder / "plan.json").read_text("utf-8"))
    manifest, texts = corpus()
    if manifest != planned["corpus"]:
        raise ValueError("Corpus does not match the recorded trial plan.")
    if not result.get("finished_at"):
        raise ValueError("Wait for the pilot to finish before freezing its report.")
    completed = [x for x in result["trials"] if x["state"] == "draft"]
    with (folder / "quota.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = [
            "trial",
            "model",
            "effort",
            "source",
            "target",
            "bucket",
            "window",
            "before_used_percent",
            "after_used_percent",
            "delta_pp",
            "status",
            "duration_minutes",
            "resets_at",
        ]
        writer = csv.DictWriter(f, columns, extrasaction="ignore")
        writer.writeheader()
        for trial in result["trials"]:
            for window in trial.get("quota_delta", []):
                writer.writerow({**trial, **window})
    order = completed[:]
    random.Random(19101).shuffle(order)
    blind = folder / "blind-review"
    if blind.exists():
        raise ValueError("Blind packet already exists; do not overwrite prior assessments.")
    blind.mkdir()
    key = []
    rows = []
    for n, trial in enumerate(order, 1):
        label = "B%03d" % n
        directory = folder / ("trial-%03d" % trial["trial"])
        source = texts[trial["source"]]
        if trial["kind"] == "roundtrip":
            parent = (
                Path(trial["dependency_directory"])
                if trial.get("dependency_directory")
                else folder / ("trial-%03d" % trial["dependency_trial"])
            )
            source = (parent / "translation.txt").read_text("utf-8")
        output = (directory / "translation.txt").read_text("utf-8")
        reference = texts["en"] if trial["kind"] == "roundtrip" else texts[trial["target"]]
        content = (
            "<h1>" + label + "</h1><p>" + escape(trial["source"] + " → " + trial["target"]) + "</p>"
        )
        for title, text in [
            ("Source", source),
            ("Translation to assess", output),
            ("Institutional reference (wording may differ)", reference),
        ]:
            content += "<h2>" + title + '</h2><p class="prose">' + escape(text) + "</p>"
        raw = json.loads((directory / "raw-response.json").read_text("utf-8"))
        notes = raw.get("response", {}).get("editorial_notes", [])
        if notes:
            content += (
                '<h2>Translator editorial notes (unapproved)</h2><pre class="prose">'
                + escape(json.dumps(notes, ensure_ascii=False, indent=2))
                + "</pre>"
            )
        (blind / (label + ".html")).write_text(page(label, content), encoding="utf-8")
        key.append({"blind_id": label, **trial})
        rows.append(
            {
                "blind_id": label,
                "source": trial["source"],
                "target": trial["target"],
                "assessment_status": "pending_bilingual_reading",
            }
        )
    save(folder / "blind-key.json", key)
    with (blind / "assessment.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = [
            "blind_id",
            "source",
            "target",
            "assessor",
            "assessment_status",
            "critical_errors",
            "major_errors",
            "minor_errors",
            "source_quote",
            "output_quote",
            "reason",
        ]
        writer = csv.DictWriter(f, columns)
        writer.writeheader()
        writer.writerows(rows)
    (blind / "README.txt").write_text(
        "Human assessment pending. Do not inspect blind-key.json, results.json or trial directories before assessing. Use two competent readers per pair, exact citations and adjudication. Trials are unapproved. Backtranslation is a separate diagnostic; a model may know a reference.",
        encoding="utf-8",
    )
    total_windows = result["quota_total"]
    quota_text = (
        "; ".join(
            x["bucket"]
            + "/"
            + x["window"]
            + ": "
            + str(x["delta_pp"])
            + " observed percentage point(s)"
            for x in total_windows
        )
        or "unavailable"
    )
    reconciliation = []
    for total in total_windows:
        windows = [
            w
            for t in result["trials"]
            for w in t.get("quota_delta", [])
            if (w["bucket"], w["window"]) == (total["bucket"], total["window"])
        ]
        comparable = total["delta_pp"] is not None and all(
            w["delta_pp"] is not None
            and (w["resets_at"], w["duration_minutes"])
            == (total["resets_at"], total["duration_minutes"])
            for w in windows
        )
        observed_sum = sum(w["delta_pp"] for w in windows) if comparable else None
        reconciliation.append(
            {
                "bucket": total["bucket"],
                "window": total["window"],
                "whole_account_delta_pp": total["delta_pp"],
                "sum_trial_observations_pp": observed_sum,
                "outside_trial_intervals_pp": total["delta_pp"] - observed_sum
                if comparable
                else None,
            }
        )
    save(folder / "quota-reconciliation.json", reconciliation)
    body = "<h1>Novel pilot — recorded results</h1>"
    body += (
        "<p>"
        + escape(
            str(len(completed))
            + " validated draft(s) out of "
            + str(len(planned["entries"]))
            + " planned calls. Stop reason: "
            + result["stop_reason"]
        )
        + "</p>"
    )
    body += (
        '<div class="cards"><div>Known tokens<br><strong>'
        + str(result["known_tokens_total"])
        + "</strong></div><div>Account quota<br><strong>"
        + escape(quota_text)
        + "</strong></div><div>Bilingual quality<br><strong>To assess</strong></div></div>"
    )
    body += "<p>Quota deltas are shared account observations without exact attribution to a configuration. A displayed zero may hide use below counter resolution. Reasoning tokens are already included in output tokens.</p>"
    body += (
        "<p>"
        + str(len(result["trials"]))
        + " retained attempts, including interruptions. Missing or nonfinal counters make the token total incomplete.</p>"
    )
    for row in reconciliation:
        if row["outside_trial_intervals_pp"]:
            body += (
                "<p>Reconciliation "
                + escape(row["bucket"] + "/" + row["window"])
                + ": whole account change "
                + str(row["whole_account_delta_pp"])
                + " percentage point(s), sum of call intervals "
                + str(row["sum_trial_observations_pp"])
                + ", change outside those intervals "
                + str(row["outside_trial_intervals_pp"])
                + ". Delayed telemetry and other account work prevent attributing this gap to configurations.</p>"
            )
    body += (
        "<p>Corpus: UDHR preamble, "
        + str(manifest["languages"]["en"]["whitespace_words"])
        + " English words, historical OHCHR copies archived in Unicode ICU. Familiar formal prose may be memorized; one trial establishes neither literary generalization nor a statistical ranking.</p>"
    )
    matched = [
        t
        for t in completed
        if t["kind"] == "matched" and t["source"] == "ja" and t["target"] == "fr"
    ]
    if matched:
        first_prompt = (folder / ("trial-%03d" % matched[0]["trial"]) / "prompt.txt").read_text(
            "utf-8"
        )
        identical = len({t["prompt_sha256"] for t in matched}) == 1
        body += (
            "<h2>Actually supplied context</h2><p>Japanese source: "
            + str(len(texts["ja"]))
            + " characters. Visible prompt: "
            + str(len(first_prompt))
            + " characters. Identical Japanese → French prompt hashes: "
            + ("oui" if identical else "non")
            + ". Measured input tokens include Codex context; visible prompt characters are not a token estimate. A small text's context overhead does not predict a long chapter's cost linearly.</p>"
        )
    config_quota = []
    body += "<h2>Configuration totals</h2><table><thead><tr><th>Configuration</th><th>Drafts / trials</th><th>Known tokens</th><th>Usage complete</th><th>Σ observed Δ (percentage points)</th></tr></thead><tbody>"
    for name, group in result["configuration_totals"].items():
        buckets = {}
        for observation in group["quota_observations"]:
            for window in observation["windows"]:
                buckets.setdefault((window["bucket"], window["window"]), []).append(window)
        sums = []
        for (bucket, window_name), windows in buckets.items():
            identities = {(w["resets_at"], w["duration_minutes"]) for w in windows}
            total = (
                sum(w["delta_pp"] for w in windows)
                if len(identities) == 1 and all(w["delta_pp"] is not None for w in windows)
                else None
            )
            config_quota.append(
                {
                    "configuration": name,
                    "bucket": bucket,
                    "window": window_name,
                    "observed_sum_pp": total,
                    "causal_attribution": "unavailable_account_shared",
                }
            )
            sums.append(
                bucket
                + "/"
                + window_name
                + ": "
                + (str(total) if total is not None else "unavailable")
            )
        body += (
            "<tr><td>"
            + escape(name)
            + "</td><td>"
            + str(group["completed"])
            + " / "
            + str(group["trials"])
            + "</td><td>"
            + str(group["known_tokens"])
            + "</td><td>"
            + ("oui" if group["usage_complete"] else "non")
            + "</td><td>"
            + escape("; ".join(sums) or "unavailable")
            + "</td></tr>"
        )
    save(folder / "configuration-quota.json", config_quota)
    body += "</tbody></table><p>Totals covering different routes are not comparable. The matched comparison covers Japanese → French only.</p>"
    body += "<h2>Trial details</h2><table><thead><tr><th>Trial</th><th>Configuration</th><th>Route</th><th>State</th><th>Tokens</th><th>Seconds</th><th>Account quota Δ</th></tr></thead><tbody>"
    for trial in result["trials"]:
        u = trial.get("usage") or {}
        tokens = (
            str(u["inputTokens"] + u["outputTokens"])
            if "inputTokens" in u and "outputTokens" in u
            else "unknown"
        )
        label = "trial-%03d" % trial["trial"]
        link = (
            '<a href="' + label + '/translation.txt">' + label + "</a>"
            if trial["state"] == "draft"
            else label
        )
        deltas = (
            "; ".join(
                x["bucket"]
                + "/"
                + x["window"]
                + ": "
                + (str(x["delta_pp"]) if x["delta_pp"] is not None else x["status"])
                for x in trial.get("quota_delta", [])
            )
            or "unavailable"
        )
        duration = "unknown" if trial.get("seconds") is None else str(round(trial["seconds"], 2))
        body += (
            "<tr><td>"
            + link
            + "</td><td>"
            + escape(trial["model"] + " / " + trial["effort"])
            + "</td><td>"
            + escape(trial["source"] + " → " + trial["target"])
            + "</td><td>"
            + escape(trial["state"])
            + "</td><td>"
            + tokens
            + "</td><td>"
            + duration
            + "</td><td>"
            + escape(deltas)
            + "</td></tr>"
        )
    body += "</tbody></table>"
    missing = result.get("pending_cells", planned["entries"][len(result["trials"]) :])
    body += "<h2>Unexecuted cells</h2>"
    body += (
        "<ul>"
        + "".join(
            "<li>"
            + escape(x["model"] + " / " + x["effort"] + " : " + x["source"] + " → " + x["target"])
            + "</li>"
            for x in missing
        )
        + "</ul>"
        if missing
        else "<p>Every planned trial was executed.</p>"
    )
    errors = [x for x in result["trials"] if x.get("error")]
    if errors:
        body += (
            "<h2>Retained failures</h2><ul>"
            + "".join("<li>" + escape(x["error"]) + "</li>" for x in errors)
            + "</ul>"
        )
    body += "<h2>Blind reading</h2><p>The blind-review folder contains sources, drafts and references without model or effort. Assessments start empty; the form is not a quality score. The identity key stays separate.</p>"
    body += '<p><a href="results.csv">Tokens/duration CSV</a> · <a href="quota.csv">Quota percentage CSV</a> · <a href="results.json">Evidence JSON</a> · <a href="plan.json">Preregistered plan</a> · <a href="blind-review/assessment.csv">Assessment form</a></p>'
    (folder / "REPORT.html").write_text(page("Novel benchmark", body), encoding="utf-8")
    return folder / "REPORT.html"


def page(title, body):
    from tools.report_html import document

    return document(title, body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    print(build(parser.parse_args().folder))
