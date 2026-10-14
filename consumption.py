"""Local accounting. Estimates of Codex credits are not subscription quota percentages."""

import json

from job_tracking import enough_usage, normalize

RATES_DATE = "2026-10-12"
RATES_URL = "https://learn.chatgpt.com/docs/pricing"
# Standard Codex credits per million tokens: uncached input, cached input, output.
RATES = {
    "gpt-6-luna": (2.5, 0.25, 12.5),
    "gpt-6.1-sol": (50, 2.5, 250),
    "gpt-6-sol": (50, 5, 250),
    "gpt-5.6-sol": (100, 10, 500),
    "gpt-6-astra": (250, 25, 1250),
}


def credits(model, usage):
    if model not in RATES or not enough_usage(usage):
        return None
    # A missing cache count gives an upper estimate (no assumed cache discount).
    i, c, o = RATES[model]
    cached = min(usage.get("cachedInputTokens", 0), usage["inputTokens"])
    return (
        (usage["inputTokens"] - cached) * i + cached * c + usage["outputTokens"] * o
    ) / 1_000_000


def calls_for(db, job):
    rows = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM inference_calls WHERE job=? ORDER BY rowid", (job["id"],)
        )
    ]
    if rows:
        for r in rows:
            r["usage"] = normalize(json.loads(r["usage"] or "{}"))
            r["complete"] = r["state"] == "completed" and enough_usage(r["usage"])
        return rows
    # Historical jobs predate the ledger. Never charge locally reused translation batches twice.
    value = json.loads(job["result"] or "{}")
    results = []
    for b in value.get("batches", []):
        if not b.get("cached"):
            results.append((job["kind"], job["model"], job["effort"], b))
    if value.get("failed_batch"):
        results.append((job["kind"], job["model"], job["effort"], value["failed_batch"]["result"]))
    for call in value.get("quality", {}).get("calls", []):
        results.append(("quality_review", call.get("model"), call.get("effort"), call))
    if not results and value.get("token_usage") and not value.get("batches"):
        results = [(job["kind"], job["model"], job["effort"], value)]
    for phase, model, effort, result in results:
        u = normalize(result.get("token_usage"))
        rows.append(
            {
                "job": job["id"],
                "phase": phase,
                "model": model,
                "effort": effort,
                "usage": u,
                "state": "historical",
                "complete": enough_usage(u),
            }
        )
    if not rows and job["state"] not in ("queued",):
        rows = [
            {
                "job": job["id"],
                "phase": job["kind"],
                "model": job["model"],
                "effort": job["effort"],
                "usage": {},
                "state": "unknown",
                "complete": False,
            }
        ]
    # An interrupted legacy call can be missing entirely from old result JSON.
    if job["error"] and rows:
        for r in rows:
            r["complete"] = False
    return rows


def report(library, series, source, target):
    chapters = {}
    for raw in library.db.execute(
        "SELECT * FROM jobs WHERE series=? AND source=? AND target=? ORDER BY rowid",
        (series, source, target),
    ):
        job = dict(raw)
        chapter = chapters.setdefault(
            job["number"],
            {
                "number": job["number"],
                "jobs": 0,
                "calls": 0,
                "input": 0,
                "cached": 0,
                "output": 0,
                "reasoning": 0,
                "credits": 0,
                "complete": True,
                "operations": [],
            },
        )
        chapter["jobs"] += 1
        for call in calls_for(library.db, job):
            u = call["usage"]
            cost = credits(call["model"], u)
            call.update(credits=cost, job_state=job["state"])
            chapter["operations"].append(call)
            chapter["calls"] += 1
            for field, key in [
                ("input", "inputTokens"),
                ("cached", "cachedInputTokens"),
                ("output", "outputTokens"),
                ("reasoning", "reasoningOutputTokens"),
            ]:
                chapter[field] += u.get(key, 0)
            chapter["credits"] += cost or 0
            chapter["complete"] &= call["complete"] and cost is not None
    rows = sorted(
        chapters.values(), key=lambda c: library.reading_position(series, source, c["number"])
    )
    for c in rows:
        c["title"] = library.source(series, source, c["number"])["title"]
        c["total"] = c["input"] + c["output"]
        if not any(o["credits"] is not None for o in c["operations"]):
            c["credits"] = None
    return {
        "chapters": rows,
        "rates_date": RATES_DATE,
        "rates_url": RATES_URL,
        "note": "Estimated Codex Standard credits. These are not billed currency or a percentage of the included quota. Reasoning is already included in output tokens. Cache usage unavailable: undiscounted rate.",
    }


def estimate(characters, model, review, chapters=1):
    # Broad planning range, explicitly not a measured prediction or quota guarantee.
    lower, upper = (2, 14) if review else (1, 7)
    overhead = 5500 if review else 2000
    low, high = (
        int(characters * lower) + chapters * overhead,
        int(characters * upper) + chapters * overhead * 3,
    )
    models = [model] + ([review["model"]] if review else [])
    rates = [RATES[m] for m in models if m in RATES]
    unit = (
        sum(0.7 * r[0] + 0.3 * r[2] for r in rates) / len(models) / 1_000_000
        if len(rates) == len(models)
        else None
    )
    return {
        "tokens_low": low,
        "tokens_high": high,
        "credits_low": low * unit if unit is not None else None,
        "credits_high": high * unit if unit is not None else None,
        "rates_date": RATES_DATE,
        "rates_url": RATES_URL,
        "basis": "Illustrative scenarios: source characters and context allowance per chapter; 70% input / 30% output, no cache discount, equal allocation between models. Actual context, reasoning and corrections may exceed this range. This estimate is not calibrated to your books. Only limits stop the run.",
    }
