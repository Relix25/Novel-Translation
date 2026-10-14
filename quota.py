"""Read-only account quota cache. Never infer subscription usage from token prices."""

import copy
import math
import threading
import time
from datetime import datetime, timezone


class QuotaCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.buckets = {}
        self.updated_at = None
        self.error = None
        self.ordinary_usage_allowed = None

    def update(self, payload, *, rolling=False):
        if not isinstance(payload, dict):
            return
        mapping = payload.get("rateLimitsByLimitId")
        if not isinstance(mapping, dict) or not mapping:
            single = payload.get("rateLimits")
            mapping = {single.get("limitId") or "codex": single} if isinstance(single, dict) else {}
        stamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            if not rolling:
                self.buckets = {}
                self.ordinary_usage_allowed = (
                    payload.get("ordinaryUsageAllowed")
                    if type(payload.get("ordinaryUsageAllowed")) is bool
                    else None
                )
            changed = False
            for identity, raw in mapping.items():
                if not isinstance(raw, dict):
                    continue
                key = str(raw.get("limitId") or identity)
                bucket = self.buckets.setdefault(key, {"id": key, "name": key, "windows": {}})
                if isinstance(raw.get("limitName"), str):
                    bucket["name"] = raw["limitName"] or key
                for name in ("primary", "secondary"):
                    window = raw.get(name)
                    if not isinstance(window, dict):
                        continue
                    used = window.get("usedPercent")
                    if type(used) not in (int, float) or not math.isfinite(used):
                        continue
                    previous = bucket["windows"].get(name, {}) if rolling else {}
                    values = {
                        "key": name,
                        "used_percent": used,
                        "remaining_percent": max(0, min(100, 100 - used)),
                        "observed_at": stamp,
                    }
                    for raw_key, field in (
                        ("windowDurationMins", "duration_minutes"),
                        ("resetsAt", "resets_at"),
                    ):
                        number = window.get(raw_key)
                        values[field] = (
                            number
                            if type(number) in (int, float) and math.isfinite(number) and number > 0
                            else previous.get(field)
                        )
                    bucket["windows"][name] = values
                    changed = True
            if changed:
                self.updated_at = stamp
                self.error = None

    def failed(self, message):
        with self.lock:
            self.error = str(message)

    def clear(self):
        with self.lock:
            self.buckets = {}
            self.updated_at = None
            self.error = None
            self.ordinary_usage_allowed = None

    def snapshot(self):
        with self.lock:
            buckets = copy.deepcopy(list(self.buckets.values()))
            for bucket in buckets:
                bucket["windows"] = list(bucket["windows"].values())
                for window in bucket["windows"]:
                    elapsed = (
                        time.time() - datetime.fromisoformat(window["observed_at"]).timestamp()
                    )
                    window["stale"] = bool(
                        self.error
                        or elapsed > 120
                        or (window.get("resets_at") and window["resets_at"] <= time.time())
                    )
            return {
                "buckets": buckets,
                "available": any(b["windows"] for b in buckets),
                "updated_at": self.updated_at,
                "error": self.error,
                "ordinary_usage_allowed": self.ordinary_usage_allowed,
                "scope": "account",
                "note": "Account quota is shared with your other Codex activity. Chapter tokens do not determine its exact quota percentage.",
            }
