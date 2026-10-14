"""Persisted progress and per-inference accounting; never store streamed prose/reasoning."""

import inspect
import json
import time
import uuid
from datetime import datetime, timezone

from novel_v1 import encode, require


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStopped(ValueError):
    pass


def limits(value=None):
    value = {} if value is None else value
    require(isinstance(value, dict), "Invalid limits.")
    result = {}
    for key, default, lower, upper in [
        ("max_tokens", 750000, 1000, 100000000),
        ("max_calls", 64, 1, 1000),
        ("timeout_seconds", 600, 30, 1200),
        ("idle_seconds", 120, 15, 600),
    ]:
        n = value.get(key, default)
        require(type(n) is int and lower <= n <= upper, "Invalid limit: " + key)
        result[key] = n
    result["idle_seconds"] = min(result["idle_seconds"], result["timeout_seconds"])
    return result


def schema(db):
    columns = {r["name"] for r in db.execute("PRAGMA table_info(jobs)")}
    for name, kind in [
        ("progress", "TEXT"),
        ("run_id", "TEXT"),
        ("stop_requested", "INTEGER NOT NULL DEFAULT 0"),
        ("started_at", "TEXT"),
        ("finished_at", "TEXT"),
    ]:
        if name not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN " + name + " " + kind)
    db.executescript("""CREATE TABLE IF NOT EXISTS inference_calls(
        id TEXT PRIMARY KEY,job TEXT REFERENCES jobs(id),phase TEXT,model TEXT,effort TEXT,
        batch INTEGER,pass INTEGER,state TEXT,usage TEXT,started_at TEXT,finished_at TEXT,error TEXT);
        CREATE INDEX IF NOT EXISTS calls_job ON inference_calls(job);
        CREATE TABLE IF NOT EXISTS bulk_runs(id TEXT PRIMARY KEY,series TEXT,source TEXT,target TEXT,
            options TEXT,state TEXT,error TEXT,created_at TEXT,updated_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS open_bulk_pair ON bulk_runs(series,source,target)
            WHERE state IN ('queued','running','pause_requested','paused');
        CREATE TABLE IF NOT EXISTS bulk_items(run TEXT REFERENCES bulk_runs(id),position INTEGER,
            number INTEGER,state TEXT,job TEXT,error TEXT,PRIMARY KEY(run,position),UNIQUE(run,number));""")
    db.commit()


def progress(library, job, **fields):
    row = library.db.execute("SELECT progress FROM jobs WHERE id=?", (job,)).fetchone()
    value = json.loads(row[0] or "{}")
    value.update(fields, updated_at=now())
    with library.db:
        library.db.execute(
            "UPDATE jobs SET progress=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (encode(value), job),
        )


def normalize(usage):
    raw = (usage or {}).get("last", usage or {})
    if not isinstance(raw, dict):
        return {}
    return {
        k: v
        for k, v in raw.items()
        if k
        in (
            "inputTokens",
            "cachedInputTokens",
            "outputTokens",
            "reasoningOutputTokens",
            "totalTokens",
        )
        and type(v) is int
        and v >= 0
    }


def enough_usage(usage):
    return "inputTokens" in usage and "outputTokens" in usage


def spent(db, job=None, run=None):
    rows = db.execute(
        "SELECT c.usage FROM inference_calls c JOIN jobs j ON j.id=c.job WHERE "
        + ("j.run_id=?" if run else "j.id=?"),
        (run or job,),
    ).fetchall()
    return sum(
        (u.get("inputTokens", 0) + u.get("outputTokens", 0))
        for r in rows
        for u in [json.loads(r[0] or "{}")]
    ), len(rows)


def check(library, row, config, before_call=False):
    current = library.db.execute(
        "SELECT stop_requested FROM jobs WHERE id=?", (row["id"],)
    ).fetchone()
    if current[0]:
        raise JobStopped("Stop requested; validated batches are preserved.")
    tokens, calls = spent(library.db, job=row["id"])
    if tokens >= config["max_tokens"]:
        raise JobStopped("Chapter token limit reached.")
    if before_call and calls >= config["max_calls"]:
        raise JobStopped("Chapter call limit reached.")
    if before_call:
        missing = library.db.execute(
            "SELECT usage FROM inference_calls WHERE job=? AND state='completed'", (row["id"],)
        ).fetchall()
        if any(not enough_usage(json.loads(r[0] or "{}")) for r in missing):
            raise JobStopped(
                "Usage for the last call is unknown; stopping to avoid untracked calls."
            )
    if row.get("run_id"):
        run = library.db.execute(
            "SELECT options,state FROM bulk_runs WHERE id=?", (row["run_id"],)
        ).fetchone()
        # A gentle pause finishes and stores the current call before the next one.
        if run["state"] != "running" and (before_call or run["state"] != "pause_requested"):
            raise JobStopped("Pause requested; the last usable result is preserved.")
        budget = json.loads(run["options"])["limits"]
        tokens, calls = spent(library.db, run=row["run_id"])
        if tokens >= budget["max_tokens"]:
            raise JobStopped("Run token limit reached.")
        if before_call and calls >= budget["max_calls"]:
            raise JobStopped("Run call limit reached.")


def invoke(
    library,
    row,
    bridge,
    prompt,
    output_schema,
    model,
    effort,
    folder,
    *,
    phase,
    batch=1,
    total=1,
    pass_number=1,
    start=1,
    end=1,
    completed=0,
    paragraphs=1,
):
    config = limits(json.loads(row.get("options") or "{}").get("limits"))
    if row.get("run_id"):
        run = library.db.execute(
            "SELECT options FROM bulk_runs WHERE id=?", (row["run_id"],)
        ).fetchone()
        run_limits = json.loads(run["options"])["limits"]
        for key in ("timeout_seconds", "idle_seconds"):
            config[key] = min(config[key], run_limits[key])
    check(library, row, config, True)
    call = uuid.uuid4().hex
    started = now()
    with library.db:
        library.db.execute(
            "INSERT INTO inference_calls(id,job,phase,model,effort,batch,pass,state,started_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (call, row["id"], phase, model, effort, batch, pass_number, "running", started),
        )
    progress(
        library,
        row["id"],
        phase=phase,
        model=model,
        effort=effort,
        batch=batch,
        batch_total=total,
        pass_number=pass_number,
        paragraph_start=start,
        paragraph_end=end,
        paragraphs_done=completed,
        paragraphs_total=paragraphs,
        call_started_at=started,
        last_event_at=started,
        activity="starting",
        output_chars=0,
    )
    last_write = 0.0
    usage = {}
    output_chars = 0

    def event(value):
        nonlocal last_write, usage, output_chars
        if value["kind"] == "usage":
            usage = normalize(value["usage"])
            with library.db:
                library.db.execute(
                    "UPDATE inference_calls SET usage=? WHERE id=?", (encode(usage), call)
                )
        check(library, row, config)
        if value["kind"] == "heartbeat":
            return
        if value["kind"] == "output":
            output_chars += value.get("characters", 0)
        clock = time.monotonic()
        if clock - last_write >= 0.5 or value["kind"] in ("usage", "started"):
            progress(
                library,
                row["id"],
                last_event_at=now(),
                activity=value["kind"],
                output_chars=output_chars,
            )
            last_write = clock

    try:
        # The protocol bridge supports live events; deterministic old fixtures may not.
        parameters = inspect.signature(bridge.generate).parameters
        extra = (
            {
                "on_event": event,
                "timeout": config["timeout_seconds"],
                "idle_timeout": config["idle_seconds"],
            }
            if "on_event" in parameters
            else {}
        )
        result = bridge.generate(prompt, output_schema, model, effort, folder, **extra)
        usage = normalize(result.get("token_usage")) or usage
        with library.db:
            library.db.execute(
                "UPDATE inference_calls SET state='completed',usage=?,finished_at=? WHERE id=?",
                (encode(usage), now(), call),
            )
        progress(library, row["id"], activity="validating", last_event_at=now())
        return result
    except Exception as error:
        with library.db:
            library.db.execute(
                "UPDATE inference_calls SET state='failed',usage=?,finished_at=?,error=? WHERE id=?",
                (encode(usage), now(), str(error), call),
            )
        raise
