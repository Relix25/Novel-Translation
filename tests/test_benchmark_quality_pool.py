"""Synthetic shared transport checks through the real fresh-thread generation path."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_benchmark_quality_full import snapshot

from benchmark import save
from codex_bridge import CodexBridge
from tools.benchmark_quality_full import SharedReviewBridge, run


class FakeProcess:
    def __init__(self):
        self.alive = True
        self.terminations = 0
        self.pid = 1234
        self.stdin = Mock()
        self.stdout = Mock()

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False
        self.terminations += 1

    def wait(self, timeout=None):
        return 0


class SyntheticWire:
    def __init__(
        self,
        *,
        connection_errors=(),
        fail_turn=False,
        uncertain=False,
        duplicate_thread=False,
        ephemeral=True,
    ):
        self.process = FakeProcess()
        self.connection_errors = list(connection_errors)
        self.connection_calls = 0
        self.rpc_calls = []
        self.fail_turn = fail_turn
        self.uncertain = uncertain
        self.duplicate_thread = duplicate_thread
        self.ephemeral = ephemeral
        self.thread_count = 0
        self.turn_count = 0
        self.bridges = []

    def connection(self, bridge):
        self.connection_calls += 1
        bridge.process = self.process
        if bridge not in self.bridges:
            self.bridges.append(bridge)
        if self.connection_errors:
            error = self.connection_errors.pop(0)
            if error:
                raise ValueError(error)
        return {
            "connected": True,
            "models": [
                {"model": "gpt-6.1-sol", "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}
            ],
        }

    def rpc(self, bridge, method, params, timeout=30):
        self.rpc_calls.append((method, params))
        if method == "thread/start":
            self.thread_count += 1
            thread = "fresh-%d" % (1 if self.duplicate_thread else self.thread_count)
            return {
                "thread": {"id": thread, "ephemeral": self.ephemeral, "modelProvider": "synthetic"},
                "model": params["model"],
                "reasoningEffort": "high",
            }
        if method == "turn/start":
            self.turn_count += 1
            turn = "turn-%d" % self.turn_count
            thread = params["threadId"]
            data = json.loads(params["input"][0]["text"].split("\nData: ", 1)[1])
            assessments = []
            for case in data["cases"]:
                uncertain = (
                    self.uncertain
                    and case["blind_id"] == "B000"
                    and "prior_uncertainties" not in data
                )
                findings = (
                    [
                        {
                            "severity": "uncertain",
                            "category": "meaning",
                            "source_quote": "source",
                            "translation_quote": "target",
                            "explanation": "Synthetic uncertainty.",
                            "suggested_edit": "",
                        }
                    ]
                    if uncertain
                    else []
                )
                assessments.append(
                    {
                        "blind_id": case["blind_id"],
                        "verdict": "uncertain" if uncertain else "clean",
                        "findings": findings,
                        "fluency": "natural",
                        "register": "preserved",
                        "assessment": "Synthetic only.",
                    }
                )
            response = json.dumps(
                {"cases": assessments, "limitations": "Synthetic fixture, not real access."}
            )
            bridge.events.extend(
                [
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread,
                            "item": {"type": "agentMessage", "text": response},
                        },
                    },
                    {
                        "method": "thread/tokenUsage/updated",
                        "params": {
                            "threadId": thread,
                            "tokenUsage": {"inputTokens": 1000, "outputTokens": 500},
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": thread,
                            "turn": {
                                "id": turn,
                                "status": "failed" if self.fail_turn else "completed",
                                "error": "Synthetic model failure" if self.fail_turn else None,
                            },
                        },
                    },
                ]
            )
            return {"turn": {"id": turn, "status": "running"}}
        return {}


class ReviewPoolTests(unittest.TestCase):
    def exercise(self, wire, size=13):
        cases = [
            {
                "blind_id": "B%03d" % n,
                "source": "source " + str(n),
                "translation": "target " + str(n),
            }
            for n in range(size)
        ]
        key = [
            {"blind_id": c["blind_id"], "trial": n + 1, "audit_kind": "translation_fidelity"}
            for n, c in enumerate(cases)
        ]
        translations = {
            "known_tokens_total": 100000,
            "quota_initial": snapshot(),
            "quota_final": snapshot(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "experiment"
            folder.mkdir()
            save(folder / "results.json", {})
            with (
                patch(
                    "tools.benchmark_quality_full.frozen_cases",
                    return_value=(translations, cases, key, {}),
                ),
                patch.object(CodexBridge, "connection", lambda bridge: wire.connection(bridge)),
                patch.object(
                    CodexBridge,
                    "rpc",
                    lambda bridge, method, params, timeout=30: wire.rpc(
                        bridge, method, params, timeout
                    ),
                ),
                patch.object(SharedReviewBridge, "quota", lambda bridge: snapshot()),
                patch("tools.benchmark_quality_full.time.sleep") as sleep,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                report = run(folder, root / "quality", 12000000, 50, reuse_server=True)
                return report, wire, sleep.call_args_list

    def test_one_live_transport_still_uses_a_fresh_ephemeral_thread_for_every_batch(self):
        report, wire, waits = self.exercise(SyntheticWire())
        self.assertEqual(report["status"], "assessed")
        self.assertEqual(wire.connection_calls, 1)
        self.assertEqual(len(wire.bridges), 1)
        self.assertEqual(report["fresh_ephemeral_thread_ids"], ["fresh-1", "fresh-2"])
        starts = [params for method, params in wire.rpc_calls if method == "thread/start"]
        self.assertEqual(len(starts), 2)
        self.assertTrue(all(p["ephemeral"] is True for p in starts))
        self.assertFalse(any(method == "thread/resume" for method, params in wire.rpc_calls))
        self.assertEqual(wire.process.terminations, 1)
        self.assertEqual(wire.turn_count, 2)
        self.assertEqual(report["known_tokens"], 3000)
        self.assertEqual(waits, [])

    def test_uncertainty_gets_only_one_extra_fresh_thread_pass(self):
        report, wire, waits = self.exercise(SyntheticWire(uncertain=True))
        self.assertEqual(
            [(c["batch"], c["pass"], len(c["case_ids"])) for c in report["calls"]],
            [(1, 1, 12), (1, 2, 1), (2, 1, 1)],
        )
        self.assertEqual(report["fresh_ephemeral_thread_ids"], ["fresh-1", "fresh-2", "fresh-3"])
        self.assertEqual(wire.connection_calls, 1)
        self.assertEqual(wire.turn_count, 3)

    def test_failed_generation_really_closes_transport_and_never_retries(self):
        report, wire, waits = self.exercise(SyntheticWire(fail_turn=True))
        self.assertEqual(report["status"], "shared_transport_failed_without_restart")
        self.assertEqual(len(report["calls"]), 1)
        self.assertEqual(wire.thread_count, 1)
        self.assertEqual(wire.turn_count, 1)
        self.assertEqual(wire.process.terminations, 1)
        self.assertIsNone(wire.bridges[0].process)
        self.assertFalse(report["usage_complete"])
        self.assertEqual(report["cases"], [])

    def test_startup_retries_are_read_only_bounded_and_use_the_same_process(self):
        report, wire, waits = self.exercise(
            SyntheticWire(connection_errors=["workspace routing discovery timed out"] * 2 + [None])
        )
        self.assertEqual(report["status"], "assessed")
        self.assertEqual(wire.connection_calls, 3)
        self.assertEqual(len(report["read_only_connection_checks"]), 3)
        self.assertEqual(
            [c["connected"] for c in report["read_only_connection_checks"]], [False, False, True]
        )
        self.assertTrue(
            all(c["generation_started"] is False for c in report["read_only_connection_checks"])
        )
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(call.args == (20,) for call in waits))
        self.assertEqual(wire.turn_count, 2)

    def test_failed_read_only_setup_makes_no_generation_or_usage_record(self):
        report, wire, waits = self.exercise(
            SyntheticWire(connection_errors=["workspace routing discovery timed out"] * 3)
        )
        self.assertEqual(report["status"], "read_only_setup_failed_before_generation")
        self.assertEqual(wire.connection_calls, 3)
        self.assertEqual(wire.turn_count, 0)
        self.assertEqual(wire.thread_count, 0)
        self.assertEqual(report["calls"], [])
        self.assertEqual(report["fresh_ephemeral_thread_ids"], [])
        self.assertEqual(wire.process.terminations, 1)
        self.assertFalse(any("token_usage" in c for c in report["read_only_connection_checks"]))

    def test_unknown_setup_error_is_not_automatically_retried(self):
        report, wire, waits = self.exercise(SyntheticWire(connection_errors=["Unexpected error"]))
        self.assertEqual(wire.connection_calls, 1)
        self.assertEqual(report["calls"], [])
        self.assertEqual(waits, [])

    def test_duplicate_thread_id_stops_before_second_turn(self):
        report, wire, waits = self.exercise(SyntheticWire(duplicate_thread=True))
        self.assertEqual(wire.thread_count, 2)
        self.assertEqual(wire.turn_count, 1)
        self.assertEqual(report["status"], "shared_transport_failed_without_restart")
        self.assertEqual(report["fresh_ephemeral_thread_ids"], ["fresh-1"])
        self.assertEqual(wire.process.terminations, 1)

    def test_non_ephemeral_thread_is_archived_without_starting_a_turn(self):
        report, wire, waits = self.exercise(SyntheticWire(ephemeral=False))
        self.assertEqual(wire.turn_count, 0)
        self.assertTrue(any(method == "thread/archive" for method, params in wire.rpc_calls))
        self.assertEqual(wire.process.terminations, 1)

    def test_active_capture_cannot_be_reset_and_closed_server_cannot_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = SharedReviewBridge(Path(temporary))
            bridge.current = {"state": "running"}
            with self.assertRaisesRegex(ValueError, "preceding trial"):
                bridge.begin_trial(Path(temporary) / "next")
            bridge.current = {"state": "completed"}
            bridge.begin_trial(Path(temporary) / "next")
            self.assertIsNone(bridge.current)
            bridge.ready_connection = {"connected": True}
            bridge.transport_started = True
            with self.assertRaisesRegex(ValueError, "no automatic restart"):
                bridge.connection()

    def test_one_inference_per_capture_and_close_is_inherited(self):
        self.assertNotIn("close", SharedReviewBridge.__dict__)
        with tempfile.TemporaryDirectory() as temporary:
            bridge = SharedReviewBridge(Path(temporary))
            bridge.calls = [{"state": "completed"}]
            with self.assertRaisesRegex(ValueError, "one inference"):
                bridge.generate("unused", {}, "gpt-6.1-sol", "high", Path(temporary))


if __name__ == "__main__":
    unittest.main()
