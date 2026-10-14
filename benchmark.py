"""Reproducible, isolated Novel translation trials through the real Codex bridge.

No credentials, API keys, automatic retries, corrections, approvals or publishing.
"""

import argparse
import csv
import hashlib
import json
import platform
import random
import time
from datetime import datetime
from pathlib import Path

from codex_bridge import CodexBridge, executable
from job_tracking import enough_usage, normalize, now
from library import Library

ROOT = Path(__file__).resolve().parent
MODELS = ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra")
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
STYLE = "Preserve every fact, condition, negation and the formal register. Use idiomatic target-language prose. No adaptation or summary."
CODEX_COMMAND = None


def configure_codex_logging(directory):
    """Explicit local logging for routing diagnostics; no authentication changes."""
    global CODEX_COMMAND
    if directory is None:
        CODEX_COMMAND = None
        return
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    CODEX_COMMAND = [
        executable(),
        "-c",
        "log_dir=" + json.dumps(str(directory)),
        "app-server",
        "--listen",
        "stdio://",
    ]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def quota_windows(snapshot):
    return {(b["id"], w["key"]): w for b in snapshot.get("buckets", []) for w in b["windows"]}


def quota_delta(before, after, *, allow_timestamp_jitter=False):
    """Percentage POINTS per unchanged window; never sum different buckets/windows."""
    left, right = quota_windows(before), quota_windows(after)
    result = []
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key), right.get(key)
        reason = None
        if before.get("error") or after.get("error"):
            reason = "quota_read_failed"
        elif not a or not b:
            reason = "window_missing"
        elif a.get("stale") or b.get("stale"):
            reason = "stale"
        elif not a.get("resets_at") or not a.get("duration_minutes"):
            reason = "window_identity_unknown"
        elif (a.get("resets_at"), a.get("duration_minutes")) != (
            b.get("resets_at"),
            b.get("duration_minutes"),
        ):
            # Administrative guard only: some server readings round a far-future
            # reset deadline by one second. Raw snapshots remain untouched and
            # ordinary scientific reports stay strict unless explicitly labelled.
            future = (
                max(datetime.fromisoformat(w["observed_at"]).timestamp() for w in (a, b))
                if all(w.get("observed_at") for w in (a, b))
                else None
            )
            jitter = (
                allow_timestamp_jitter
                and a.get("duration_minutes") == b.get("duration_minutes")
                and b.get("resets_at")
                and abs(a["resets_at"] - b["resets_at"]) <= 2
                and future is not None
                and min(a["resets_at"], b["resets_at"]) > future + 60
                and b["used_percent"] >= a["used_percent"]
            )
            if not jitter:
                reason = "window_changed_or_reset"
        elif b["used_percent"] < a["used_percent"]:
            reason = "usage_decreased"
        delta = None if reason else b["used_percent"] - a["used_percent"]
        result.append(
            {
                "bucket": key[0],
                "window": key[1],
                "delta_pp": delta,
                "status": reason
                or (
                    "account_observation_with_reset_timestamp_jitter"
                    if (a and b and a.get("resets_at") != b.get("resets_at"))
                    else (
                        "below_display_resolution_or_zero"
                        if delta == 0
                        else "account_observation_only"
                    )
                ),
                "before_used_percent": a.get("used_percent") if a else None,
                "after_used_percent": b.get("used_percent") if b else None,
                "duration_minutes": a.get("duration_minutes") if a else None,
                "resets_at": a.get("resets_at") if a else None,
            }
        )
    return result


def corpus():
    folder = ROOT / "benchmarks" / "corpus"
    manifest = json.loads((folder / "manifest.json").read_text("utf-8"))
    texts = {}
    for lang, spec in manifest["languages"].items():
        raw = (folder / spec["file"]).read_bytes()
        if sha(raw) != spec["sha256"]:
            raise ValueError("Corpus changed: " + lang)
        lines = raw.decode("utf-8").splitlines()
        # Extraction is fixed by inclusive one-based line spans, not model output.
        texts[lang] = " ".join(
            x.strip() for x in lines[spec["start_line"] - 1 : spec["end_line"]] if x.strip()
        )
        if sha(texts[lang].encode()) != spec["extracted_sha256"]:
            raise ValueError("Extraction changed: " + lang)
    return manifest, texts


def supported(models):
    return {
        (m["model"], e["reasoningEffort"])
        for m in models
        for e in m.get("supportedReasoningEfforts", [])
    }


def plan(models, mode="pilot", repetitions=3, seed=73113):
    available = supported(models)
    for model in MODELS:
        if not any(m == model for m, _ in available):
            raise ValueError("Requested configuration unavailable; no substitution: " + model)
    if mode == "pilot":
        # 9 matched Japanese->French trials + 7 coverage calls = 16 calls.
        configs = [
            (m, e) for m in MODELS for e in ("low", "high", "max" if m == MODELS[0] else "ultra")
        ]
        entries = [
            {
                "model": m,
                "effort": e,
                "source": "ja",
                "target": "fr",
                "repeat": 1,
                "kind": "matched",
            }
            for m, e in configs
        ]
        random.Random(seed).shuffle(entries)
        coverage = [
            ("en", "fr"),
            ("zh", "fr"),
            ("zh", "en"),
            ("ko", "fr"),
            ("ko", "en"),
            ("ja", "en"),
        ]
        entries += [
            {
                "model": MODELS[0],
                "effort": "high",
                "source": a,
                "target": b,
                "repeat": 1,
                "kind": "coverage",
            }
            for a, b in coverage
        ]
        entries.append(
            {
                "model": MODELS[0],
                "effort": "high",
                "source": "fr",
                "target": "en",
                "repeat": 1,
                "kind": "roundtrip",
            }
        )
    else:
        configs = [(m, e) for m in MODELS for e in EFFORTS if (m, e) in available]
        entries = []
        for repeat in range(1, repetitions + 1):
            block = [
                {
                    "model": m,
                    "effort": e,
                    "source": a,
                    "target": b,
                    "repeat": repeat,
                    "kind": "matched",
                }
                for m, e in configs
                for a, b in [
                    ("en", "fr"),
                    ("zh", "fr"),
                    ("zh", "en"),
                    ("ko", "fr"),
                    ("ko", "en"),
                    ("ja", "fr"),
                    ("ja", "en"),
                ]
            ]
            random.Random(seed + repeat).shuffle(block)
            # Each return leg uses its own configuration's preceding English->French draft.
            block += [
                {
                    "model": m,
                    "effort": e,
                    "source": "fr",
                    "target": "en",
                    "repeat": repeat,
                    "kind": "roundtrip",
                }
                for m, e in configs
            ]
            entries += block
    missing = [x for x in entries if (x["model"], x["effort"]) not in available]
    if missing:
        raise ValueError("Requested configuration unavailable; no substitution: " + str(missing[0]))
    return {
        "mode": mode,
        "seed": seed,
        "repetitions": 1 if mode == "pilot" else repetitions,
        "entries": entries,
        "unsupported": [
            {"model": m, "effort": e} for m in MODELS for e in EFFORTS if (m, e) not in available
        ],
    }


class TrialBridge(CodexBridge):
    """Capture allowed evidence and reject rerouting; use production generation."""

    def __init__(self, directory):
        super().__init__(command=CODEX_COMMAND)
        self.directory = Path(directory)
        self.calls = []
        self.current = None

    def quota(self):
        return BenchmarkControl.quota(self)

    def rpc(self, method, params, timeout=30):
        result = super().rpc(method, params, timeout)
        if method == "turn/start" and self.current is not None:
            self.current["turn_request"] = {
                k: params.get(k) for k in ("model", "effort", "serviceTierForTurn")
            }
            self.current["turn_acknowledgement"] = {
                k: result.get("turn", {}).get(k) for k in ("id", "status")
            }
            save(self.directory / "call.json", self.current)
        if method == "thread/start" and self.current is not None:
            thread = result.get("thread", {})
            self.current["thread"] = {
                k: thread.get(k) for k in ("id", "ephemeral", "modelProvider")
            }
            self.current["start_model"] = result.get("model")
            self.current["start_effort"] = result.get("reasoningEffort")
            save(self.directory / "call.json", self.current)
            if result.get("model") not in (None, params["model"]):
                raise ValueError("Server returned a different model; no generation permitted.")
        return result

    def _next(self, deadline):
        message = super()._next(deadline)
        if message.get("method") == "model/rerouted" and self.current is not None:
            params = message.get("params", {})
            self.current["rerouted"] = {
                k: params.get(k) for k in ("fromModel", "toModel", "reason")
            }
            save(self.directory / "call.json", self.current)
            raise ValueError("Model rerouted; trial invalid, stopping without retry.")
        return message

    def generate(
        self, prompt, schema, model, effort, cwd, timeout=600, on_event=None, idle_timeout=120
    ):
        if self.calls:
            raise ValueError(
                "Pilot expects one inference per trial; unexpected extra batch stopped."
            )
        self.current = {
            "started_at": now(),
            "model": model,
            "effort": effort,
            "prompt_sha256": sha(prompt.encode()),
            "schema_sha256": sha(json.dumps(schema, sort_keys=True).encode()),
            "service_tier": "default",
            "usage": None,
        }
        self.calls.append(self.current)
        (self.directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        save(self.directory / "schema.json", schema)
        save(self.directory / "call.json", self.current)

        def event(value):
            if value["kind"] == "usage":
                self.current["usage"] = normalize(value["usage"])
                save(self.directory / "call.json", self.current)
            if on_event:
                on_event(value)

        started = time.monotonic()
        try:
            result = super().generate(
                prompt, schema, model, effort, cwd, timeout, event, idle_timeout
            )
            self.current.update(state="completed", usage=normalize(result.get("token_usage")))
            save(self.directory / "raw-response.json", result)
            return result
        except Exception as error:
            self.current.update(state="failed", error=str(error))
            raise
        finally:
            self.current.update(finished_at=now(), seconds=time.monotonic() - started)
            save(self.directory / "call.json", self.current)


class BenchmarkControl(CodexBridge):
    """Allow a read-only quota response 30 seconds; never retry an inference.

    Generation still uses the unchanged production bridge. An unavailable or
    stale response remains a stop condition, with no guessed quota replacement.
    """

    def _quota_once(self):
        if not self.lock.acquire(blocking=False):
            return {**self.quota_cache.snapshot(), "busy": True}
        try:
            if not self.process or self.process.poll() is not None:
                self.quota_cache.failed("Connect Codex to refresh the quota.")
            else:
                try:
                    self.quota_cache.update(self.rpc("account/rateLimits/read", {}, timeout=30))
                except (ValueError, TimeoutError, OSError) as error:
                    self.quota_cache.failed(error)
            return self.quota_cache.snapshot()
        finally:
            self.lock.release()

    def quota(self):
        initial = BenchmarkControl._quota_once(self)
        if valid_quota(initial) or initial.get("busy"):
            return initial
        # Refresh only the read-only transport, never a translation or review.
        fresh = CodexBridge(command=self.command)
        try:
            connection = fresh.connection()
            if not connection["connected"]:
                return initial
            recovered = BenchmarkControl._quota_once(fresh)
            recovered["quota_read_recovery"] = {
                "attempts": 2,
                "first_error": initial.get("error"),
                "generation_retried": False,
            }
            return recovered
        except Exception as error:
            return {
                **initial,
                "quota_read_recovery": {
                    "attempts": 2,
                    "second_error": str(error),
                    "generation_retried": False,
                },
            }
        finally:
            fresh.close()


def valid_quota(snapshot):
    return (
        snapshot.get("available")
        and not snapshot.get("error")
        and all(not w.get("stale") for w in quota_windows(snapshot).values())
    )


def budget_ready(evidence, max_tokens):
    """Reserve at least the smallest already observed input context for a new call.

    This is a planning guard, not a bound on the next call's reported usage.
    """
    observed = [
        (t.get("usage") or {}).get("inputTokens")
        for t in evidence["trials"]
        if t["state"] == "draft"
    ]
    floor = max(1000, min((n for n in observed if type(n) is int and n > 0), default=1000))
    return max_tokens - evidence["known_tokens_total"] >= floor


def report(folder, evidence):
    rows = evidence["trials"]
    fields = [
        "trial",
        "model",
        "effort",
        "source",
        "target",
        "kind",
        "repeat",
        "state",
        "seconds",
        "inputTokens",
        "cachedInputTokens",
        "outputTokens",
        "reasoningOutputTokens",
        "totalTokens",
        "error",
    ]
    with (folder / "results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **(row.get("usage") or {})})
    groups = {}
    for row in rows:
        key = row["model"] + "/" + row["effort"]
        group = groups.setdefault(
            key,
            {
                "trials": 0,
                "completed": 0,
                "known_tokens": 0,
                "usage_complete": True,
                "quota_observations": [],
            },
        )
        group["trials"] += 1
        group["completed"] += row["state"] == "draft"
        u = row.get("usage") or {}
        # A streamed counter from an interrupted call is a known lower bound.
        group["usage_complete"] &= enough_usage(u) and row.get("call_state", row["state"]) in (
            "completed",
            "draft",
        )
        group["known_tokens"] += u.get("inputTokens", 0) + u.get("outputTokens", 0)
        group["quota_observations"].append(
            {"trial": row["trial"], "windows": row.get("quota_delta", [])}
        )
    evidence["configuration_totals"] = groups
    evidence["known_tokens_total"] = sum(g["known_tokens"] for g in groups.values())
    evidence["quota_total"] = quota_delta(
        evidence.get("quota_initial", {}), evidence.get("quota_final", {})
    )
    evidence["quota_attribution"] = (
        "Account-level observations; concurrent Codex chat and delayed/rounded telemetry prevent exact per-configuration attribution."
    )
    save(folder / "results.json", evidence)


def execute(
    folder,
    planned,
    texts,
    max_calls=16,
    max_tokens=200000,
    max_delta_pp=3,
    initial_roundtrips=None,
    all_cells=False,
):
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "plan.json", planned)
    files = [
        "benchmark.py",
        "codex_bridge.py",
        "library.py",
        "novel_v1.py",
        "batches.py",
        "job_tracking.py",
        "quota.py",
        "translation_prompt.py",
        "prompts/literary_translation.md",
        "source_images.py",
        "story_memory.py",
        "quality_review.py",
    ]
    for source_file in files:
        snapshot_path = folder / "source-snapshot" / source_file
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes((ROOT / source_file).read_bytes())
    evidence = {
        "started_at": now(),
        "python": platform.python_version(),
        "code_sha256": {p: sha((ROOT / p).read_bytes()) for p in files},
        "limits": {"max_calls": max_calls, "max_tokens": max_tokens, "max_delta_pp": max_delta_pp},
        "trials": [],
        "stop_reason": None,
    }
    control = BenchmarkControl(command=CODEX_COMMAND)
    evidence["transport_command_override"] = CODEX_COMMAND
    roundtrips = dict(initial_roundtrips or {})
    continuation_meta = planned.get("manual_continuation", {}) if all_cells else {}
    blocked_cells = {
        tuple(item["key"]): item["trial"] for item in continuation_meta.get("blocked_cells", [])
    }
    prior_known = continuation_meta.get("cumulative_prior_known_tokens", 0)
    evidence["budget_prior_known_tokens"] = prior_known

    def cell_key(entry):
        return tuple(entry[k] for k in ("model", "effort", "source", "target", "kind"))

    try:
        connection = control.connection()
        save(folder / "catalogue.json", connection)
        quota = control.quota()
        evidence["quota_initial"] = quota
        evidence["quota_final"] = quota
        budget_quota = continuation_meta.get("budget_quota_initial", quota)
        evidence["budget_quota_initial"] = budget_quota
        if not connection["connected"] or (max_delta_pp is not None and not valid_quota(quota)):
            raise ValueError("ChatGPT connection and fresh quota required before generation.")
        for index, entry in enumerate(planned["entries"], 1):
            report(folder, evidence)
            if index > max_calls or (
                max_tokens is not None
                and not budget_ready(
                    {
                        **evidence,
                        "known_tokens_total": evidence["known_tokens_total"] + prior_known,
                    },
                    max_tokens,
                )
            ):
                evidence["stop_reason"] = "pilot_budget_reached"
                break
            directory = folder / ("trial-%03d" % index)
            directory.mkdir()
            key = cell_key(entry)
            if key in blocked_cells:
                evidence["trials"].append(
                    {
                        **entry,
                        "trial": index,
                        "state": "not_run_after_prior_error",
                        "blocked_by_trial": blocked_cells[key],
                        "error": "No automatic retry of a previously rejected cell.",
                        "call_state": "not_started",
                    }
                )
                report(folder, evidence)
                print(
                    json.dumps(
                        {"trial": index, "state": "not_run_after_prior_error", **entry},
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                continue
            before = control.quota()
            total_delta = quota_delta(budget_quota, before, allow_timestamp_jitter=all_cells)
            if max_delta_pp is not None and (
                not valid_quota(before) or any(x["delta_pp"] is None for x in total_delta)
            ):
                evidence["stop_reason"] = "quota_unavailable_or_window_changed"
                break
            if max_delta_pp is not None and any(x["delta_pp"] >= max_delta_pp for x in total_delta):
                evidence["stop_reason"] = "quota_budget_reached"
                break
            if any(
                w["remaining_percent"] <= (0 if all_cells else 5)
                for w in quota_windows(before).values()
            ):
                evidence["stop_reason"] = "quota_reserve_reached"
                break
            text = texts[entry["source"]]
            dependency = None
            if entry["kind"] == "roundtrip":
                dependency = roundtrips.get((entry["model"], entry["effort"], entry["repeat"]))
                if not dependency:
                    if all_cells:
                        evidence["trials"].append(
                            {
                                **entry,
                                "trial": index,
                                "state": "not_run_missing_outgoing_leg",
                                "error": "Outgoing English->French draft is unavailable; no invented return-leg input.",
                                "call_state": "not_started",
                            }
                        )
                        report(folder, evidence)
                        continue
                    raise ValueError("Return leg has no validated English->French draft.")
                text = dependency["text"]
            lib = Library(directory / "library")
            bridge = TrialBridge(directory)
            trial = {
                **entry,
                "trial": index,
                "quota_before": before,
                "source_sha256": sha(text.encode()),
                "dependency_trial": dependency["trial"] if dependency else None,
                "dependency_directory": dependency.get("directory") if dependency else None,
            }
            # Persist attempted trial before any possible inference.
            trial["state"] = "starting"
            evidence["trials"].append(trial)
            report(folder, evidence)
            try:
                sid = lib.create(
                    "UDHR preamble benchmark", entry["source"], [entry["target"]], STYLE
                )
                lib.import_source(sid, entry["source"], 1, "Preamble", text)
                job = lib.queue_job(
                    sid,
                    entry["source"],
                    entry["target"],
                    1,
                    "translation",
                    entry["model"],
                    entry["effort"],
                    review=None,
                    limits_config={
                        "max_calls": 1,
                        "max_tokens": 100000000
                        if max_tokens is None
                        else min(100000, max_tokens - evidence["known_tokens_total"] - prior_known),
                        "timeout_seconds": 600,
                        "idle_seconds": 120,
                    },
                )
                trial.update(job=job, series=sid)
                lib.run_job(job, bridge)
                jobrow = dict(lib.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())
                trial.update(state=jobrow["state"], error=jobrow["error"])
                save(directory / "job.json", jobrow)
                if bridge.current:
                    trial.update(
                        usage=bridge.current["usage"],
                        seconds=bridge.current["seconds"],
                        prompt_sha256=bridge.current["prompt_sha256"],
                        model_confirmation=bridge.current.get("start_model"),
                        ephemeral=bridge.current.get("thread", {}).get("ephemeral"),
                        call_state=bridge.current.get("state"),
                    )
                if jobrow["state"] == "draft":
                    result = json.loads(jobrow["result"])
                    translated = "\n\n".join(s["text"] for s in result["response"]["segments"])
                    (directory / "translation.txt").write_text(translated, encoding="utf-8")
                    trial["translation_sha256"] = sha(translated.encode())
                    if entry["source"] == "en" and entry["target"] == "fr":
                        roundtrips[(entry["model"], entry["effort"], entry["repeat"])] = {
                            "text": translated,
                            "trial": index,
                        }
            except Exception as error:
                trial.update(state="failed", error=str(error))
            finally:
                bridge.close()
                lib.close()
                after = control.quota()
                trial.update(quota_after=after, quota_delta=quota_delta(before, after))
                evidence["quota_final"] = after
                report(folder, evidence)
            print(
                json.dumps(
                    {
                        k: trial.get(k)
                        for k in (
                            "trial",
                            "model",
                            "effort",
                            "source",
                            "target",
                            "state",
                            "usage",
                            "error",
                        )
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            if trial["state"] != "draft" or not enough_usage(trial.get("usage") or {}):
                if all_cells:
                    blocked_cells[key] = index
                    evidence.setdefault("failures", []).append(
                        {
                            "trial": index,
                            "cell": entry,
                            "error": trial.get("error") or "Usage unknown",
                        }
                    )
                    # Other predeclared independent cells continue; never restart this cell.
                    continue
                evidence["stop_reason"] = (
                    "token_budget_interruption_no_retry"
                    if trial.get("error") == "Chapter token limit reached."
                    else "first_error_or_unknown_usage_no_retry"
                )
                break
        if evidence["stop_reason"] is None:
            evidence["stop_reason"] = (
                "planned_trials_completed_with_rejections"
                if evidence.get("failures")
                else "planned_trials_completed"
            )
    except Exception as error:
        evidence["stop_reason"] = str(error)
    finally:
        control.close()
        evidence["finished_at"] = now()
        report(folder, evidence)
    return evidence


def continuation(previous, planned, texts, preserve_failures=False):
    """Explicit manual continuation, never automatically retry a prior experiment."""
    previous = Path(previous).resolve()
    recorded = json.loads((previous / "results.json").read_text("utf-8"))
    old_plan = json.loads((previous / "plan.json").read_text("utf-8"))
    if (
        not recorded.get("finished_at")
        or old_plan["corpus"] != planned["corpus"]
        or any(old_plan[k] != planned[k] for k in ("mode", "seed", "repetitions"))
    ):
        raise ValueError("Continuation requires a finished run with the identical frozen corpus.")

    def key(t):
        return tuple(t[k] for k in ("model", "effort", "source", "target", "repeat", "kind"))

    if preserve_failures:
        master = old_plan.get("master_entries", old_plan["entries"])
        available = {(t["model"], t["effort"]) for t in planned["entries"]}
        if any((t["model"], t["effort"]) not in available for t in master):
            raise ValueError(
                "A prior configuration is unavailable; refusing to change the frozen matrix."
            )
        planned["master_entries"] = master
        planned["entries"] = master
        planned["unsupported"] = old_plan.get("unsupported", [])
    inherited = old_plan.get("manual_continuation", {}) if preserve_failures else {}
    completed, dependencies, recorded_keys, blocked = (
        set(),
        {},
        {tuple(k) for k in inherited.get("preserved_entry_keys", [])},
        [],
    )
    for item in inherited.get("outgoing_dependencies", []):
        directory = Path(item["directory"])
        translated = (directory / "translation.txt").read_text("utf-8")
        if sha(translated.encode()) != item["translation_sha256"]:
            raise ValueError("Previously validated draft changed; refusing reuse.")
        dependencies[(item["model"], item["effort"], item["repeat"])] = {
            "text": translated,
            "trial": item["trial"],
            "directory": str(directory),
        }
    for trial in recorded["trials"]:
        recorded_keys.add(key(trial))
        if trial["state"] in ("failed", "interrupted") or (
            trial["state"] == "draft" and not enough_usage(trial.get("usage") or {})
        ):
            blocked.append(
                {
                    "key": [trial[k] for k in ("model", "effort", "source", "target", "kind")],
                    "trial": str(previous) + "/trial-%03d" % trial["trial"],
                }
            )
        if trial["state"] != "draft":
            continue
        directory = previous / ("trial-%03d" % trial["trial"])
        translated = (directory / "translation.txt").read_text("utf-8")
        if sha(translated.encode()) != trial["translation_sha256"]:
            raise ValueError("Previously validated draft changed; refusing reuse.")
        completed.add(key(trial))
        if trial["source"] == "en" and trial["target"] == "fr":
            if sha(texts["en"].encode()) != trial["source_sha256"]:
                raise ValueError("English source changed; refusing the previous outgoing leg.")
            dependencies[(trial["model"], trial["effort"], trial["repeat"])] = {
                "text": translated,
                "trial": trial["trial"],
                "directory": str(directory),
            }
    excluded = recorded_keys if preserve_failures else completed
    planned["entries"] = [entry for entry in planned["entries"] if key(entry) not in excluded]
    planned["manual_continuation"] = {
        "previous_directory": str(previous),
        "previous_results_sha256": sha((previous / "results.json").read_bytes()),
        "completed_cells_reused_without_inference": len(completed),
        "prior_known_tokens": recorded["known_tokens_total"],
    }
    if preserve_failures:
        planned["manual_continuation"].update(
            blocked_cells=inherited.get("blocked_cells", []) + blocked,
            cumulative_prior_known_tokens=recorded["known_tokens_total"]
            + recorded.get("budget_prior_known_tokens", 0),
            budget_quota_initial=recorded.get(
                "budget_quota_initial", recorded.get("quota_initial", {})
            ),
            recorded_slots_preserved_without_retry=len(recorded_keys),
            preserved_entry_keys=[list(k) for k in sorted(recorded_keys)],
            outgoing_dependencies=[
                {
                    "model": k[0],
                    "effort": k[1],
                    "repeat": k[2],
                    "trial": v["trial"],
                    "directory": v["directory"],
                    "translation_sha256": sha(v["text"].encode()),
                }
                for k, v in dependencies.items()
            ],
        )
    return dependencies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("--mode", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=200000)
    parser.add_argument("--max-delta-pp", type=float, default=3)
    parser.add_argument(
        "--continue-from",
        type=Path,
        help="Explicit manual continuation of a finished experiment into a new directory.",
    )
    parser.add_argument(
        "--codex-log-dir",
        type=Path,
        help="Explicit local Codex log directory for routing diagnostics; no account or model changes.",
    )
    parser.add_argument(
        "--all-cells",
        action="store_true",
        help="Continue other independent predeclared cells after errors; never retry a failed cell.",
    )
    parser.add_argument(
        "--unlimited-tokens",
        action="store_true",
        help="Remove benchmark token/quota-delta ceilings; account limits and watchdogs remain.",
    )
    args = parser.parse_args()
    if (
        args.repetitions < 1
        or args.max_calls < 1
        or args.max_tokens < 1000
        or args.max_delta_pp <= 0
    ):
        parser.error("Positive limits required (tokens >= 1000).")
    if (args.all_cells or args.unlimited_tokens) and args.mode != "full":
        parser.error("Expanded execution must use the explicitly selected full mode.")
    # Prevent accidentally using an existing personal library as the destination.
    if args.output.exists():
        parser.error("Output must be a new directory; existing evidence is immutable.")
    manifest, texts = corpus()
    configure_codex_logging(args.codex_log_dir)
    bridge = CodexBridge(command=CODEX_COMMAND)
    try:
        catalogue = bridge.connection()
        planned = plan(catalogue["models"], args.mode, args.repetitions)
    finally:
        bridge.close()
    planned.update(
        corpus=manifest,
        quality_review="disabled; raw drafts only",
        approval="not approved",
        quota_scope="account",
    )
    planned["execution_policy"] = {
        "all_independent_cells": args.all_cells,
        "unlimited_token_budget": args.unlimited_tokens,
        "on_error": "record rejection, skip future repetitions of that cell, continue other predeclared cells"
        if args.all_cells
        else "stop",
    }
    dependencies = (
        continuation(args.continue_from, planned, texts, preserve_failures=args.all_cells)
        if args.continue_from
        else None
    )
    if args.action == "plan":
        args.output.mkdir(parents=True)
        save(args.output / "plan.json", planned)
        save(args.output / "catalogue.json", catalogue)
        print("Planned inference calls:", len(planned["entries"]))
    else:
        result = execute(
            args.output,
            planned,
            texts,
            len(planned["entries"]) if args.all_cells else args.max_calls,
            None if args.unlimited_tokens else args.max_tokens,
            None if args.unlimited_tokens else args.max_delta_pp,
            dependencies,
            args.all_cells,
        )
        print("Stop:", result["stop_reason"], "Known tokens:", result["known_tokens_total"])
        if result["stop_reason"] not in (
            "planned_trials_completed",
            "planned_trials_completed_with_rejections",
            "pilot_budget_reached",
            "quota_budget_reached",
            "quota_reserve_reached",
        ):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
