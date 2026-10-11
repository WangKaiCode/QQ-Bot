"""Deterministic offline job recovery, identity and content lifetime checks."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar import jobs
from qq_radar.domain import timestamp_ms
from qq_radar.ingestion import import_file
from qq_radar.storage import connect

TOPIC = {"id": "ai", "name": "AI", "keywords": ["AI"]}
START = timestamp_ms("2026-10-10T10:00:00+08:00")
END = START + 3600000


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_path = self.root / "source.db"
        self.writer = connect(self.source_path)
        self.addCleanup(self.writer.close)
        self.source = connect(self.source_path, readonly=True)
        self.addCleanup(self.source.close)
        self.jobs = jobs.connect(self.root / "jobs.db")
        self.addCleanup(self.jobs.close)
        self.ingest("one")

    def ingest(self, mid, account="a", group="g", text="AI secret synthetic body"):
        row = {"schema_version": "synthetic.v1", "account_id": account, "group_id": group,
               "message_id": mid, "sender_id": "synthetic-user", "timestamp": "2026-10-10T10:15:00+08:00",
               "segments": [{"type": "text", "text": text}]}
        path = self.root / "input.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual(import_file(self.writer, path, {(account, group)})["counts"]["failed"], 0)

    def enqueue(self, **kwargs):
        return jobs.enqueue(self.jobs, self.source, "a", "g", TOPIC, "hourly", START, END, as_of=kwargs.get("as_of", END))

    def test_idempotent_persistence_contains_no_source_text(self):
        before = list(self.source.iterdump())
        self.assertEqual(self.enqueue()["inserted"], 1)
        self.assertEqual(self.enqueue()["matched"], 1)
        self.assertEqual(jobs.run(self.jobs, self.source, END)["succeeded"], 1)
        self.assertEqual(jobs.run(self.jobs, self.source, END)["succeeded"], 0)
        stored = "\n".join(self.jobs.iterdump())
        self.assertNotIn("secret synthetic body", stored)
        self.assertNotIn("excerpt", stored)
        self.assertEqual(before, list(self.source.iterdump()))
        result = jobs.feed(self.jobs, self.source, "a", "g", END)
        self.assertEqual(result["items"][0]["points"][0]["excerpt"], "AI secret synthetic body")
        self.assertFalse(self.source.in_transaction)

    def test_late_input_supersedes_and_latest_success_is_one_card(self):
        self.enqueue()
        self.ingest("late")
        self.assertEqual(jobs.run(self.jobs, self.source, END)["superseded"], 1)
        self.assertEqual(jobs.run(self.jobs, self.source, END)["succeeded"], 1)
        self.ingest("later")
        self.enqueue()
        self.assertTrue(jobs.feed(self.jobs, self.source, "a", "g", END)["items"][0]["update_pending"])
        jobs.run(self.jobs, self.source, END)
        cards = jobs.feed(self.jobs, self.source, "a", "g", END)["items"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(cards[0]["evidence"]), 3)
        self.assertEqual(len(jobs.list_jobs(self.jobs, "a", "g")), 3)

    def test_source_and_digest_expiry_never_return_excerpt(self):
        self.enqueue()
        jobs.run(self.jobs, self.source, END)
        source_expiry = START + 900000 + 3 * 86400000
        card = jobs.feed(self.jobs, self.source, "a", "g", source_expiry)["items"][0]
        self.assertEqual(card["state"], "available")
        self.assertEqual(card["points"][0]["source_state"], "expired")
        self.assertNotIn("excerpt", card["points"][0])
        card = jobs.feed(self.jobs, self.source, "a", "g", END + 10 * 86400000)["items"][0]
        self.assertEqual(card["state"], "expired")
        self.assertNotIn("excerpt", card["points"][0])
        self.assertEqual(self.enqueue(as_of=source_expiry)["empty_windows"], 1)

    def test_changed_source_and_scope_isolation(self):
        self.enqueue()
        jobs.run(self.jobs, self.source, END)
        self.assertEqual(jobs.feed(self.jobs, self.source, "b", "g", END)["items"], [])
        with self.writer:
            self.writer.execute("UPDATE messages SET payload_hash='changed'")
        point = jobs.feed(self.jobs, self.source, "a", "g", END)["items"][0]["points"][0]
        self.assertEqual(point["source_state"], "changed")
        self.assertNotIn("excerpt", point)

    def test_old_failure_does_not_mark_latest_success_pending(self):
        old_id = self.enqueue()["job_ids"][0]
        jobs.run(self.jobs, self.source, END)
        self.ingest("late")
        self.enqueue()
        jobs.run(self.jobs, self.source, END)
        with self.jobs:
            self.jobs.execute("UPDATE analysis_jobs SET status='failed' WHERE id=?", (old_id,))
        card = jobs.feed(self.jobs, self.source, "a", "g", END)["items"][0]
        self.assertFalse(card["update_pending"])
        self.assertEqual(len(card["evidence"]), 2)
        self.assertFalse(self.jobs.in_transaction)
        self.assertFalse(self.source.in_transaction)

    def test_late_input_visible_before_enqueue_without_writes(self):
        self.enqueue()
        jobs.run(self.jobs, self.source, END)
        self.assertFalse(jobs.feed(self.jobs, self.source, "a", "g", END)["items"][0]["input_changed"])
        self.ingest("late", text="unrelated late text")
        before = list(self.jobs.iterdump())
        card = jobs.feed(self.jobs, self.source, "a", "g", END)["items"][0]
        self.assertTrue(card["input_changed"])
        self.assertFalse(card["update_pending"])
        self.assertEqual(before, list(self.jobs.iterdump()))

    def test_pagination_rejects_noninteger_and_overflow(self):
        for value in (True, 1.5, "2", 10 ** 30, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    jobs.feed(self.jobs, self.source, "a", "g", END, offset=value)
                with self.assertRaises(ValueError):
                    jobs.list_jobs(self.jobs, "a", "g", value)
                with self.assertRaises(ValueError):
                    jobs.feed(self.jobs, self.source, "a", "g", END, limit=value)
        self.assertFalse(self.jobs.in_transaction)
        self.assertFalse(self.source.in_transaction)

    def test_retry_limit_and_reclaimed_crash_lease(self):
        self.enqueue()
        with patch.object(jobs, "_window", side_effect=ValueError("private body")):
            for _ in range(3):
                self.assertEqual(jobs.run(self.jobs, self.source, END)["failed"], 1)
        row = jobs.list_jobs(self.jobs, "a", "g")[0]
        self.assertEqual((row["status"], row["attempts"]), ("failed_terminal", 3))
        self.assertNotIn("private body", row["error_code"])
        with self.jobs:
            self.jobs.execute("UPDATE analysis_jobs SET status='running',attempts=1,claim_token='dead',lease_until=?", (END + 1,))
        self.assertEqual(jobs.run(self.jobs, self.source, END)["succeeded"], 0)
        self.assertEqual(jobs.run(self.jobs, self.source, END + 1)["succeeded"], 1)

    def test_stale_worker_fenced_after_lease_reclaim(self):
        self.enqueue()
        original = jobs._window
        calls = []
        def interleaved(*args):
            if not calls:
                calls.append(True)
                self.assertEqual(jobs.run(self.jobs, self.source, END + 300000)["succeeded"], 1)
                raise ValueError("stale worker failure")
            return original(*args)
        with patch.object(jobs, "_window", side_effect=interleaved):
            self.assertEqual(jobs.run(self.jobs, self.source, END)["failed"], 0)
        self.assertEqual(jobs.list_jobs(self.jobs, "a", "g")[0]["status"], "succeeded")

    def test_reject_wrong_database_and_invalid_windows(self):
        with self.assertRaises(ValueError):
            jobs.connect(self.source_path)
        with self.assertRaisesRegex(ValueError, "COLLISION"):
            jobs.enqueue(self.source, self.source, "a", "g", TOPIC, "hourly", START, END, END)
        for since, until in ((START + 1, END), (START, END + 1), (START, START), (START, END + 72 * 3600000)):
            with self.assertRaises(ValueError):
                jobs.enqueue(self.jobs, self.source, "a", "g", TOPIC, "hourly", since, until, END + 80 * 3600000)
        with self.assertRaises(ValueError):
            self.enqueue(as_of=END - 1)
        with self.assertRaises(ValueError):
            jobs.feed(self.jobs, self.source, "a", "g", END, limit=0)


if __name__ == "__main__":
    unittest.main()
