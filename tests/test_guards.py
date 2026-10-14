"""Real scheduling and protocol boundaries with synthetic model responses only."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_batches import BatchBridge
from test_quality_review import ReviewBridge

from app import App
from bulk_jobs import control, create, preview, work
from codex_bridge import CodexBridge
from consumption import credits, report
from job_tracking import JobStopped, limits, spent
from library import Library


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lib = Library(Path(self.temp.name) / "library")
        self.sid = self.lib.create("Synthetic guards", "en", ["fr"], "Faithful")
        for n in range(1, 4):
            self.lib.import_source(self.sid, "en", n, f"Chapter {n}", "A synthetic source.")
        self.value = dict(
            series_id=self.sid,
            source="en",
            target="fr",
            count=3,
            model="gpt-6-luna",
            effort="high",
            limits={"max_tokens": 100000, "max_calls": 64},
        )

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def start(self, **changes):
        value = {**self.value, **changes}
        value["fingerprint"] = preview(self.lib, value)["fingerprint"]
        return create(self.lib, value)

    def run_row(self, run):
        return dict(self.lib.db.execute("SELECT * FROM bulk_runs WHERE id=?", (run,)).fetchone())

    def test_pause_on_first_error_and_resume_only_remaining_chapters(self):
        run = self.start()
        bridge = BatchBridge(fail_at=2)
        work(self.lib, run, bridge)
        self.assertEqual(bridge.calls, 2)
        self.assertEqual(self.run_row(run)["state"], "paused")
        self.assertEqual(
            [i["state"] for i in self.lib.activity()["runs"][0]["items"]],
            ["done", "failed", "pending"],
        )
        self.assertEqual(spent(self.lib.db, run=run), (300, 2))
        retry = BatchBridge()
        control(self.lib, run, "resume")
        work(self.lib, run, retry)
        self.assertEqual(retry.calls, 2)
        self.assertEqual(self.run_row(run)["state"], "completed")
        self.assertEqual(spent(self.lib.db, run=run), (900, 4))
        self.assertEqual(len(report(self.lib, self.sid, "en", "fr")["chapters"]), 3)

    def test_limits_span_retries_and_cannot_be_reset_by_resume(self):
        run = self.start(limits={"max_calls": 1, "max_tokens": 1000})
        bridge = BatchBridge()
        work(self.lib, run, bridge)
        self.assertEqual(bridge.calls, 1)
        self.assertEqual(self.run_row(run)["state"], "paused")
        with self.assertRaisesRegex(ValueError, "limit"):
            control(self.lib, run, "resume")
        control(self.lib, run, "resume", {"max_calls": 5, "max_tokens": 1000})
        work(self.lib, run, bridge)
        self.assertEqual(bridge.calls, 3)
        self.assertEqual(spent(self.lib.db, run=run), (900, 3))

    def test_unknown_usage_pauses_and_completed_draft_is_not_retranslated(self):
        class Unknown(BatchBridge):
            def generate(self, *args):
                result = super().generate(*args)
                result["token_usage"] = None
                return result

        run = self.start()
        bridge = Unknown()
        work(self.lib, run, bridge)
        self.assertEqual(bridge.calls, 1)
        self.assertIn("unknown", self.run_row(run)["error"])
        control(self.lib, run, "resume")
        retry = BatchBridge()
        work(self.lib, run, retry)
        self.assertEqual(retry.calls, 2)
        self.assertEqual(self.run_row(run)["state"], "completed")

    def test_review_failure_keeps_translation_and_resume_skips_luna(self):
        run = self.start(
            count=1, review={"model": "gpt-6.1-sol", "effort": "high", "max_passes": 2}
        )
        first = ReviewBridge(["fail"])
        work(self.lib, run, first)
        self.assertEqual(self.run_row(run)["state"], "paused")
        self.assertEqual(len(first.calls), 2)
        control(self.lib, run, "resume")
        second = ReviewBridge()
        work(self.lib, run, second)
        self.assertEqual([c[0] for c in second.calls], ["gpt-6.1-sol"])
        self.assertEqual(self.run_row(run)["state"], "completed")

    def test_restart_pauses_queue_and_preserves_unknown_inflight_usage(self):
        run = self.start()
        with self.lib.db:
            self.lib.db.execute("UPDATE bulk_runs SET state='running' WHERE id=?", (run,))
        job = self.lib.queue_job(
            self.sid, "en", "fr", 1, "translation", "gpt-6-luna", "high", run_id=run, position=0
        )
        with self.lib.db:
            self.lib.db.execute("UPDATE jobs SET state='running' WHERE id=?", (job,))
            self.lib.db.execute(
                "INSERT INTO inference_calls(id,job,state,usage) VALUES('inflight',?,'running',?)",
                (job, json.dumps({"inputTokens": 500})),
            )
        self.lib.recover_jobs()
        self.assertEqual(self.run_row(run)["state"], "paused")
        self.assertEqual(
            self.lib.db.execute("SELECT state FROM inference_calls WHERE id='inflight'").fetchone()[
                0
            ],
            "interrupted",
        )
        bridge = BatchBridge()
        work(self.lib, run, bridge)
        self.assertEqual(bridge.calls, 0)
        self.assertFalse(report(self.lib, self.sid, "en", "fr")["chapters"][0]["complete"])

    def test_preview_reading_order_selection_and_existing_drafts(self):
        # Stable IDs are deliberately out of book order.
        for n, section in [(1, 3), (2, 1), (3, 2)]:
            meta = {
                "volume": 1,
                "section": section,
                "volume_title": "Book",
                "kind": "chapter",
                "file": "test.epub",
                "book_hash": "a" * 64,
            }
            with self.lib.db:
                self.lib.db.execute(
                    "INSERT INTO origins VALUES(?,?,?,?,?)",
                    (self.sid, "en", n, str(n), json.dumps(meta)),
                )
        plan = preview(self.lib, self.value)
        self.assertEqual([c["number"] for c in plan["chapters"]], [2, 3, 1])
        selected = preview(self.lib, {**self.value, "numbers": [1, 2]})
        self.assertEqual([c["number"] for c in selected["chapters"]], [2, 1])
        job = self.lib.queue_job(self.sid, "en", "fr", 2, "translation", "gpt-6-luna", "high")
        self.lib.run_job(job, BatchBridge())
        self.assertEqual([c["number"] for c in preview(self.lib, self.value)["chapters"]], [3, 1])
        with self.assertRaisesRegex(ValueError, "already has"):
            preview(self.lib, {**self.value, "numbers": [2]})
        with self.assertRaisesRegex(ValueError, "changed"):
            create(self.lib, {**self.value, "fingerprint": plan["fingerprint"]})

    def test_duplicate_runs_and_individual_jobs_are_rejected_until_cancelled(self):
        run = self.start()
        with self.assertRaises(ValueError):
            self.start()
        with self.assertRaisesRegex(ValueError, "batch run"):
            self.lib.queue_job(self.sid, "en", "fr", 1, "translation", "gpt-6-luna", "high")
        control(self.lib, run, "pause")
        with self.assertRaises(ValueError):
            self.start()
        control(self.lib, run, "cancel")
        self.assertNotEqual(run, self.start())

    def test_streamed_usage_replaces_cumulative_values_and_failure_preserves_it(self):
        class Streaming(BatchBridge):
            def generate(self, *args, on_event=None, timeout=None, idle_timeout=None):
                on_event(
                    {"kind": "usage", "usage": {"last": {"inputTokens": 200, "outputTokens": 40}}}
                )
                on_event(
                    {
                        "kind": "usage",
                        "usage": {
                            "last": {
                                "inputTokens": 200,
                                "cachedInputTokens": 100,
                                "outputTokens": 80,
                                "reasoningOutputTokens": 30,
                            }
                        },
                    }
                )
                raise ValueError("Synthetic disconnect")

        job = self.lib.queue_job(self.sid, "en", "fr", 1, "translation", "gpt-6-luna", "high")
        self.lib.run_job(job, Streaming())
        self.assertEqual(spent(self.lib.db, job=job), (280, 1))
        row = report(self.lib, self.sid, "en", "fr")["chapters"][0]
        self.assertEqual((row["input"], row["output"], row["reasoning"]), (200, 80, 30))
        self.assertFalse(row["complete"])
        self.assertAlmostEqual(row["credits"], (100 * 2.5 + 100 * 0.25 + 80 * 12.5) / 1e6)

    def test_budget_aborts_on_usage_notification_before_more_output(self):
        class Excess(BatchBridge):
            def generate(self, *args, on_event=None, timeout=None, idle_timeout=None):
                self.calls += 1
                on_event(
                    {"kind": "usage", "usage": {"last": {"inputTokens": 900, "outputTokens": 150}}}
                )
                raise AssertionError("Budget should have interrupted this call")

        job = self.lib.queue_job(
            self.sid,
            "en",
            "fr",
            1,
            "translation",
            "gpt-6-luna",
            "high",
            limits_config={"max_tokens": 1000},
        )
        bridge = Excess()
        self.lib.run_job(job, bridge)
        row = self.lib.db.execute("SELECT state,error FROM jobs WHERE id=?", (job,)).fetchone()
        self.assertEqual(row["state"], "interrupted")
        self.assertIn("token limit", row["error"])
        self.assertEqual(spent(self.lib.db, job=job), (1050, 1))

    def test_stop_flag_interrupts_running_call_without_model_mutex(self):
        class Stoppable(BatchBridge):
            def generate(inner, *args, on_event=None, timeout=None, idle_timeout=None):
                other = Library(self.lib.root)
                try:
                    with other.db:
                        other.db.execute("UPDATE jobs SET stop_requested=1 WHERE id=?", (job,))
                finally:
                    other.close()
                on_event({"kind": "heartbeat"})
                raise AssertionError("Stopped call continued")

        job = self.lib.queue_job(self.sid, "en", "fr", 1, "translation", "gpt-6-luna", "high")
        self.lib.run_job(job, Stoppable())
        self.assertEqual(
            self.lib.db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()[0],
            "interrupted",
        )

    def test_bounded_chapter_calls_and_cached_resume_accounting(self):
        self.lib.import_source(
            self.sid,
            "en",
            4,
            "Long",
            "\n\n".join("Long source " + str(i) + " x" * 450 for i in range(100)),
        )
        first = self.lib.queue_job(
            self.sid,
            "en",
            "fr",
            4,
            "translation",
            "gpt-6-luna",
            "high",
            limits_config={"max_calls": 1},
        )
        a = BatchBridge()
        self.lib.run_job(first, a)
        self.assertEqual(a.calls, 1)
        retry = self.lib.queue_job(self.sid, "en", "fr", 4, "translation", "gpt-6-luna", "high")
        b = BatchBridge()
        self.lib.run_job(retry, b)
        result = json.loads(
            self.lib.db.execute("SELECT result FROM jobs WHERE id=?", (retry,)).fetchone()[0]
        )
        self.assertTrue(result["batches"][0]["cached"])
        self.assertEqual(
            report(self.lib, self.sid, "en", "fr")["chapters"][0]["total"],
            300 * (a.calls + b.calls),
        )

    def test_prices_and_validation_do_not_invent_unknowns_or_double_reasoning(self):
        self.assertIsNone(credits("unknown", {"inputTokens": 100, "outputTokens": 200}))
        self.assertIsNone(credits("gpt-6-luna", {}))
        self.assertEqual(
            credits(
                "gpt-6-luna", {"inputTokens": 100, "outputTokens": 200, "reasoningOutputTokens": 50}
            ),
            0.00275,
        )
        for value in ({"max_calls": 0}, {"idle_seconds": True}, {"max_tokens": -1}):
            with self.assertRaises(ValueError):
                limits(value)

    def test_ten_next_and_stricter_run_timeouts_apply_to_every_call(self):
        for n in range(4, 13):
            self.lib.import_source(self.sid, "en", n, str(n), "Synthetic source.")
        self.assertEqual(len(preview(self.lib, {**self.value, "count": 10})["chapters"]), 10)

        class Timed(BatchBridge):
            def generate(inner, *args, on_event=None, timeout=None, idle_timeout=None):
                self.assertEqual((timeout, idle_timeout), (60, 15))
                return super(Timed, inner).generate(*args)

        run = self.start(limits={"timeout_seconds": 60, "idle_seconds": 15})
        bridge = Timed()
        work(self.lib, run, bridge)
        self.assertEqual(bridge.calls, 3)
        self.assertEqual(self.run_row(run)["state"], "completed")

    def test_active_jobs_do_not_disappear_behind_history_and_bulk_backup_is_guarded(self):
        job = self.lib.queue_job(self.sid, "en", "fr", 1, "translation", "gpt-6-luna", "high")
        with self.lib.db:
            for n in range(105):
                self.lib.db.execute(
                    "INSERT INTO jobs(id,state,number) VALUES(?,'failed',2)", (str(n),)
                )
        self.assertIn(job, [j["id"] for j in self.lib.activity()["jobs"]])
        with self.lib.db:
            self.lib.db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job,))
        run = self.start()
        with self.assertRaisesRegex(ValueError, "(?i)pause"):
            self.lib.backup()
        control(self.lib, run, "pause")
        backup = self.lib.backup()["database_backup"]
        restored = Library(backup)
        try:
            self.assertEqual(restored.activity()["runs"][0]["state"], "paused")
        finally:
            restored.close()


class ConcurrencyTests(unittest.TestCase):
    def test_queue_connect_and_stop_remain_responsive_during_inference(self):
        class Busy:
            def __init__(self):
                self.lock = threading.RLock()
                self.started = threading.Event()
                self.release = threading.Event()
                self.connections = 0

            def connection(self):
                with self.lock:
                    self.connections += 1
                    return {
                        "connected": True,
                        "models": [
                            {
                                "model": "fake",
                                "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                            }
                        ],
                    }

            def generate(self, *args):
                with self.lock:
                    self.started.set()
                    self.release.wait(4)
                    raise ValueError("Synthetic stop")

        with tempfile.TemporaryDirectory() as root:
            bridge = Busy()
            app = App(root, bridge)
            try:
                with app.library() as lib:
                    sid = lib.create("Synthetic", "en", ["fr"], "Faithful")
                    for n in (1, 2):
                        lib.import_source(sid, "en", n, str(n), "Synthetic source.")
                value = dict(
                    action="generate",
                    series_id=sid,
                    source="en",
                    target="fr",
                    kind="translation",
                    model="fake",
                    effort="high",
                    review={"model": "fake", "effort": "high", "max_passes": 2},
                )
                first = app.action({**value, "number": 1})
                self.assertTrue(bridge.started.wait(2))
                start = time.monotonic()
                app.action({**value, "number": 2})
                self.assertTrue(app.action({"action": "connect"})["cached_while_busy"])
                app.action({"action": "stop-job", "job_id": first["job_id"]})
                self.assertLess(time.monotonic() - start, 1.5)
                self.assertEqual(bridge.connections, 1)
                with app.library() as lib:
                    self.assertEqual(len(lib.activity()["jobs"]), 2)
            finally:
                bridge.release.set()
                app.close()

    def test_duplicate_instance_cannot_recover_another_instances_active_job(self):
        with tempfile.TemporaryDirectory() as root:
            app = App(root, BatchBridge())
            try:
                with app.library() as lib:
                    sid = lib.create("Synthetic", "en", ["fr"], "Faithful")
                    lib.import_source(sid, "en", 1, "One", "Synthetic source.")
                    job = lib.queue_job(sid, "en", "fr", 1, "translation", "fake", "high")
                with self.assertRaisesRegex(ValueError, "already open"):
                    App(root, BatchBridge())
                with app.library() as lib:
                    self.assertEqual(
                        lib.db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()[0],
                        "queued",
                    )
            finally:
                app.close()
            restarted = App(root, BatchBridge())
            try:
                with restarted.library() as lib:
                    self.assertEqual(
                        lib.db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()[0],
                        "interrupted",
                    )
            finally:
                restarted.close()

    def test_watchdog_interrupts_silent_turn_and_callback_cancellation(self):
        class Silent(CodexBridge):
            def __init__(self):
                super().__init__()
                self.interrupted = False
                self.closed = False

            def connection(self):
                return {
                    "connected": True,
                    "models": [
                        {
                            "model": "fake",
                            "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                        }
                    ],
                }

            def rpc(self, method, params, timeout=30):
                if method == "thread/start":
                    return {"thread": {"id": "thread", "ephemeral": True}}
                if method == "turn/start":
                    return {"turn": {"id": "turn"}}
                if method == "turn/interrupt":
                    self.interrupted = True
                    return {}
                raise AssertionError(method)

            def close(self):
                self.closed = True

        for cancel in (False, True):
            bridge = Silent()

            def event(value):
                if cancel and value["kind"] == "heartbeat":
                    raise JobStopped("Test stop")

            with self.assertRaises((TimeoutError, JobStopped)):
                bridge.generate(
                    "Synthetic",
                    {},
                    "fake",
                    "high",
                    Path.cwd(),
                    timeout=1,
                    idle_timeout=0.04,
                    on_event=event,
                )
            self.assertTrue(bridge.interrupted)
            self.assertTrue(bridge.closed)

    def test_uncertain_turn_start_is_closed_without_automatic_retry(self):
        class Uncertain(CodexBridge):
            def __init__(self):
                super().__init__()
                self.closed = False
                self.starts = 0

            def connection(self):
                return {
                    "connected": True,
                    "models": [
                        {
                            "model": "fake",
                            "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                        }
                    ],
                }

            def rpc(self, method, params, timeout=30):
                if method == "thread/start":
                    return {"thread": {"id": "thread", "ephemeral": True}}
                if method == "turn/start":
                    self.starts += 1
                    raise TimeoutError("Synthetic lost acknowledgement")
                raise AssertionError(method)

            def close(self):
                self.closed = True

        bridge = Uncertain()
        with self.assertRaises(TimeoutError):
            bridge.generate("Synthetic", {}, "fake", "high", Path.cwd())
        self.assertEqual(bridge.starts, 1)
        self.assertTrue(bridge.closed)


if __name__ == "__main__":
    unittest.main()
