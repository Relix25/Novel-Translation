"""Quota safeguards with synthetic responses; no live model calls."""

import json
import tempfile
import unittest
from pathlib import Path

from library import Library


class BatchBridge:
    def __init__(self, fail_at=None, invalid=False):
        self.calls = 0
        self.fail_at = fail_at
        self.invalid = invalid
        self.schemas = []

    def generate(self, prompt, schema, model, effort, cwd):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("Synthetic interruption")
        template = json.loads(prompt.split("\nResponse template: ")[1])
        self.schemas.append(schema)
        self.asserted_ids = [s["id"] for s in template["segments"]]
        assert (
            schema["properties"]["segments"]["items"]["properties"]["id"]["enum"]
            == self.asserted_ids
        )
        for key in ("chapter", "source_hash", "packet_hash"):
            assert schema["properties"][key]["enum"] == [template[key]]
        for s in template["segments"]:
            s["text"] = "Traduction synthétique."
        if self.invalid:
            template["segments"].pop()
        return {
            "response": template,
            "model": model,
            "effort": effort,
            "token_usage": {
                "last": {"inputTokens": 100, "outputTokens": 200, "reasoningOutputTokens": 20}
            },
        }


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lib = Library(Path(self.temp.name) / "data")
        self.sid = self.lib.create("Synthetic batches", "en", ["fr"], "Faithful")
        self.lib.import_source(
            self.sid,
            "en",
            1,
            "Long chapter",
            "\n\n".join("Paragraph " + str(i) + " x" * 450 for i in range(100)),
        )

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def run_job(self, bridge, model="test-luna"):
        job = self.lib.queue_job(self.sid, "en", "fr", 1, "translation", model, "medium")
        self.lib.run_job(job, bridge)
        return dict(self.lib.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())

    def test_manual_resume_reuses_only_completed_valid_batches(self):
        broken = BatchBridge(fail_at=3)
        first = self.run_job(broken)
        self.assertEqual(first["state"], "failed")
        with self.lib.pair(self.sid, "en", "fr") as p:
            self.assertIsNone(p.chapter(1)["translation"])
        bridge = BatchBridge()
        result = self.run_job(bridge)
        generated = json.loads(result["result"])
        self.assertEqual(result["state"], "draft")
        self.assertEqual(sum(b["cached"] for b in generated["batches"]), 2)
        self.assertEqual(bridge.calls, generated["batch_total"] - 2)
        self.assertEqual(generated["token_usage"]["last"]["inputTokens"], bridge.calls * 100)
        with self.lib.pair(self.sid, "en", "fr") as p:
            self.assertEqual(len(json.loads(p.chapter(1)["translation"])), 100)
        # An explicit retranslation after a completed draft actually generates again.
        fresh = BatchBridge()
        self.run_job(fresh)
        self.assertEqual(fresh.calls, generated["batch_total"])

    def test_invalid_batch_is_not_cached_or_submitted(self):
        result = self.run_job(BatchBridge(invalid=True))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(
            self.lib.db.execute("SELECT count(*) FROM translation_batches").fetchone()[0], 0
        )
        generated = json.loads(result["result"])
        self.assertEqual(generated["token_usage"]["last"]["inputTokens"], 100)
        self.assertEqual(generated["failed_batch"]["index"], 1)
        self.assertTrue(generated["failed_batch"]["result"]["response"]["segments"])
        self.assertIn("Batch 1/", result["error"])
        self.assertNotIn("failed_batch", json.loads(self.lib.snapshot()["jobs"][0]["result"]))

    def test_identifier_schema_is_scoped_to_each_batch(self):
        bridge = BatchBridge()
        result = self.run_job(bridge)
        self.assertEqual(result["state"], "draft")
        batches = [
            schema["properties"]["segments"]["items"]["properties"]["id"]["enum"]
            for schema in bridge.schemas
        ]
        self.assertGreater(len(batches), 1)
        ids = [identifier for batch in batches for identifier in batch]
        with self.lib.pair(self.sid, "en", "fr") as project:
            self.assertEqual(ids, [s["id"] for s in project.packet(1)["segments"]])
        self.assertEqual(len(ids), len(set(ids)))

    def test_cache_does_not_cross_models(self):
        self.run_job(BatchBridge(fail_at=2))
        fresh = BatchBridge()
        result = json.loads(self.run_job(fresh, "another-model")["result"])
        self.assertTrue(all(not b["cached"] for b in result["batches"]))
        self.assertEqual(fresh.calls, result["batch_total"])
