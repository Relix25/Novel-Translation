"""Editor, batch boundaries and quota semantics; all model responses are synthetic."""

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from test_batches import BatchBridge

from app import App, LocalServer, handler_for
from bulk_jobs import control, create, preview, work
from codex_bridge import CodexBridge
from library import Library
from quota import QuotaCache


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lib = Library(self.temp.name)
        self.sid = self.lib.create("Synthetic workshop", "en", ["fr"], "Faithful")
        for n in range(1, 4):
            self.lib.import_source(self.sid, "en", n, str(n), "One sentence.\n\nTwo sentences.")
        self.value = dict(
            series_id=self.sid,
            source="en",
            target="fr",
            numbers=[1, 2, 3],
            model="gpt-6-luna",
            effort="high",
        )

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def draft(self, number=1):
        job = self.lib.queue_job(self.sid, "en", "fr", number, "translation", "gpt-6-luna", "high")
        self.lib.run_job(job, BatchBridge())

    def test_edits_preserve_ids_history_and_invalidate_approval_summary(self):
        self.draft()
        with self.lib.pair(self.sid, "en", "fr") as p:
            original = p.chapter(1)
            segments = json.loads(original["translation"])
            p.review(1, original["translation_hash"], "Synthetic human review")
            s = p.summary(
                1,
                {
                    "chapter": 1,
                    "translation_hash": original["translation_hash"],
                    "text": "Synthetic summary",
                    "evidence": [segments[0]["id"]],
                },
            )
            p.review_summary(1, s["summary_hash"], "Evidence checked")
            saved = p.edit(
                1,
                original["translation_hash"],
                p.packet(1)["packet_hash"],
                {segments[0]["id"]: "Une correction humaine."},
            )
            after = p.chapter(1)
            self.assertEqual((after["state"], after["summary_state"]), ("draft", "stale"))
            self.assertEqual(json.loads(after["translation"])[1], segments[1])
            versions = p.versions(1)
            self.assertTrue(
                any(
                    v["state"] == "approved"
                    and v["translation_hash"] == original["translation_hash"]
                    for v in versions
                )
            )
            self.assertNotEqual(saved["translation_hash"], original["translation_hash"])
            with self.assertRaisesRegex(ValueError, "changed"):
                p.edit(
                    1,
                    original["translation_hash"],
                    p.packet(1)["packet_hash"],
                    {segments[0]["id"]: "Stale tab"},
                )
            old = next(v for v in versions if v["state"] == "approved")
            restored = p.restore_version(
                1, old["id"], after["translation_hash"], p.packet(1)["packet_hash"]
            )
            self.assertEqual(restored["translation_hash"], original["translation_hash"])
            self.assertEqual(p.chapter(1)["state"], "draft")

    def test_edit_rejects_changed_context_empty_unknown_segments_and_wrong_version(self):
        self.draft()
        with self.lib.pair(self.sid, "en", "fr") as p:
            c = p.chapter(1)
            sid = json.loads(c["segments"])[0]["id"]
            packet = p.packet(1)["packet_hash"]
            for edits in ({sid: ""}, {"unknown": "Text"}, {}):
                with self.assertRaises(ValueError):
                    p.edit(1, c["translation_hash"], packet, edits)
            with self.assertRaisesRegex(ValueError, "Context"):
                p.edit(1, c["translation_hash"], "old-context", {sid: "Text"})
            with self.assertRaises(ValueError):
                p.restore_version(1, 999, c["translation_hash"], packet)
            self.assertEqual(p.chapter(1)["translation_hash"], c["translation_hash"])

    def test_empty_explicit_selection_never_falls_back_to_next_ten(self):
        with self.assertRaises(ValueError):
            preview(self.lib, {**self.value, "numbers": []})
        with self.assertRaises(ValueError):
            preview(self.lib, {**self.value, "numbers": [1, 1]})
        with self.assertRaises(ValueError):
            preview(self.lib, {**self.value, "numbers": [True]})

    def test_selection_over_one_hundred_and_discontinuous_order(self):
        for n in range(4, 108):
            self.lib.import_source(self.sid, "en", n, str(n), "Synthetic sentence.")
        plan = preview(self.lib, {**self.value, "numbers": list(range(107, 0, -1))})
        self.assertEqual([c["number"] for c in plan["chapters"]], list(range(1, 108)))
        plan = preview(self.lib, {**self.value, "numbers": [103, 2, 71]})
        self.assertEqual([c["number"] for c in plan["chapters"]], [2, 71, 103])

    def test_gentle_pause_finishes_call_and_resumes_from_cached_output(self):
        # A long chapter needs multiple calls; its first complete call must survive the pause.
        self.lib.import_source(
            self.sid,
            "en",
            4,
            "Long",
            "\n\n".join("Synthetic " + str(n) + " x" * 450 for n in range(50)),
        )
        value = {**self.value, "numbers": [4]}
        value["fingerprint"] = preview(self.lib, value)["fingerprint"]
        run = create(self.lib, value)
        outer = self

        class Gentle(BatchBridge):
            def generate(inner, *args, on_event=None, timeout=None, idle_timeout=None):
                control(outer.lib, run, "pause-after-call")
                on_event({"kind": "heartbeat"})
                return super(Gentle, inner).generate(*args)

        first = Gentle()
        work(self.lib, run, first)
        self.assertEqual(first.calls, 1)
        self.assertEqual(self.lib.activity()["runs"][0]["state"], "paused")
        self.assertEqual(
            self.lib.db.execute("SELECT count(*) FROM translation_batches").fetchone()[0], 1
        )
        control(self.lib, run, "resume")
        second = BatchBridge()
        work(self.lib, run, second)
        self.assertEqual(self.lib.activity()["runs"][0]["state"], "completed")
        result = json.loads(
            self.lib.db.execute("SELECT result FROM jobs ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        )
        self.assertTrue(result["batches"][0]["cached"])

    def test_editor_refuses_to_write_under_queued_agent(self):
        self.draft()
        app = App(Path(self.temp.name) / "other", BatchBridge())
        app.root = self.lib.root
        try:
            with self.lib.pair(self.sid, "en", "fr") as p:
                c = p.chapter(1)
                sid = json.loads(c["segments"])[0]["id"]
                packet = p.packet(1)["packet_hash"]
            self.lib.queue_job(self.sid, "en", "fr", 1, "translation", "gpt-6-luna", "high")
            with self.assertRaisesRegex(ValueError, "job on this chapter to finish"):
                app.action(
                    {
                        **self.value,
                        "action": "edit",
                        "number": 1,
                        "hash": c["translation_hash"],
                        "packet_hash": packet,
                        "edits": {sid: "Do not overwrite"},
                    }
                )
        finally:
            app.close()


class QuotaTests(unittest.TestCase):
    def test_multiple_buckets_preferred_and_sparse_notifications_preserve_windows(self):
        q = QuotaCache()
        future = int(time.time() + 3600)
        q.update(
            {
                "rateLimits": {"limitId": "legacy", "primary": {"usedPercent": 99}},
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitName": "Codex",
                        "primary": {
                            "usedPercent": 20,
                            "windowDurationMins": 300,
                            "resetsAt": future,
                        },
                        "secondary": {
                            "usedPercent": 40,
                            "windowDurationMins": 10080,
                            "resetsAt": future,
                        },
                    },
                    "other": {"primary": {"usedPercent": 12}},
                },
            }
        )
        q.update(
            {
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {"usedPercent": 21, "resetsAt": None},
                    "secondary": None,
                }
            },
            rolling=True,
        )
        data = q.snapshot()
        self.assertEqual(len(data["buckets"]), 2)
        codex = next(b for b in data["buckets"] if b["id"] == "codex")
        self.assertEqual([w["remaining_percent"] for w in codex["windows"]], [79, 60])
        self.assertEqual(codex["windows"][0]["resets_at"], future)
        self.assertFalse(codex["windows"][0]["stale"])

    def test_unknown_is_not_zero_and_past_reset_is_not_assumed_recovered(self):
        q = QuotaCache()
        q.update({"rateLimits": {"primary": None, "secondary": None}})
        self.assertFalse(q.snapshot()["available"])
        q.update({"rateLimits": {"primary": {"usedPercent": 100, "resetsAt": time.time() - 1}}})
        w = q.snapshot()["buckets"][0]["windows"][0]
        self.assertEqual(w["remaining_percent"], 0)
        self.assertTrue(w["stale"])
        q.failed("Offline")
        self.assertTrue(q.snapshot()["available"])
        self.assertEqual(q.snapshot()["error"], "Offline")

    def test_quota_never_blocks_behind_generation_mutex(self):
        bridge = CodexBridge()
        held = threading.Event()
        release = threading.Event()

        def hold():
            with bridge.lock:
                held.set()
                release.wait(5)

        t = threading.Thread(target=hold)
        t.start()
        held.wait(2)
        try:
            started = time.monotonic()
            snapshot = bridge.quota()
            self.assertLess(time.monotonic() - started, 0.2)
            self.assertTrue(snapshot["busy"])
        finally:
            release.set()
            t.join()


class DockerTests(unittest.TestCase):
    def test_published_origin_is_checked_for_health_and_mutations(self):
        with tempfile.TemporaryDirectory() as root:
            app = App(root, BatchBridge())
            server = LocalServer(("127.0.0.1", 0), handler_for(app))
            server.public_origin = "http://127.0.0.1:8791"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            address = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(address + "/health")
                self.assertEqual(denied.exception.code, 403)
                headers = {"Host": "127.0.0.1:8791"}
                with urllib.request.urlopen(
                    urllib.request.Request(address + "/health", headers=headers)
                ) as response:
                    self.assertEqual(json.load(response)["version"], "0.7.0")
                headers.update(
                    {
                        "Origin": server.public_origin,
                        "X-Novel-CSRF": app.token,
                        "Content-Type": "application/json",
                    }
                )
                body = json.dumps(
                    {
                        "action": "create",
                        "title": "Docker fixture",
                        "source_language": "en",
                        "targets": ["fr"],
                        "style": "Faithful",
                    }
                ).encode()
                with urllib.request.urlopen(
                    urllib.request.Request(address + "/api/action", data=body, headers=headers)
                ) as response:
                    self.assertIn("series_id", json.load(response))
                headers["Origin"] = "http://evil.invalid"
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(
                        urllib.request.Request(address + "/api/action", data=body, headers=headers)
                    )
                self.assertEqual(denied.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                app.close()

    def test_backup_import_preserves_source_and_refuses_replacement(self):
        from docker_bootstrap import bootstrap

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            lib = Library(root / "source")
            try:
                sid = lib.create("Docker source", "en", ["fr"], "Faithful")
                lib.import_source(sid, "en", 1, "First", "Original.")
                with lib.pair(sid, "en", "fr"):
                    pass
                backup = Path(lib.backup()["database_backup"])
            finally:
                lib.close()
            original = (backup / "library.sqlite").read_bytes()
            result = bootstrap(backup, root / "docker-library")
            self.assertTrue(result["source_preserved"])
            self.assertEqual((root / "docker-library/library.sqlite").read_bytes(), original)
            with self.assertRaises(ValueError):
                bootstrap(backup, root / "docker-library")
            self.assertEqual((backup / "library.sqlite").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
