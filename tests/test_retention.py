"""Retention preview boundaries, snapshot safety and metadata-only output."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.domain import timestamp_ms
from qq_radar.ingestion import import_file
from qq_radar.retention import preview
from qq_radar.storage import connect, detail


def record(mid, account="a", group="g"):
    return {"schema_version": "synthetic.v1", "account_id": account, "group_id": group,
            "message_id": mid, "sender_id": "synthetic-secret-sender", "sender_name": "secret-name",
            "timestamp": "2026-10-10T10:00:00+08:00", "segments": [
                {"type": "text", "text": "secret-source-body"},
                {"type": "image", "resource_ref": "synthetic://secret-resource"}]}


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "retention.db"
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        self.cutoff = timestamp_ms("2026-10-13T10:00:00+08:00")

    def ingest(self, records):
        path = self.root / "input.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
        result = import_file(self.db, path, {(row["account_id"], row["group_id"]) for row in records})
        self.assertEqual(result["counts"]["failed"], 0)

    def test_expiry_boundary_uses_expires_at_and_does_not_hide_original(self):
        self.ingest([record("one")])
        self.assertEqual(preview(self.db, "a", "g", self.cutoff - 1)["counts"]["due_messages"], 0)
        due = preview(self.db, "a", "g", self.cutoff)
        self.assertEqual(due["counts"]["due_messages"], 1)
        self.assertEqual(due["items"][0]["expires_at"], "2026-10-13T10:00:00+08:00")
        with self.db:
            self.db.execute("UPDATE messages SET expires_at=?", (self.cutoff + 1,))
        self.assertEqual(preview(self.db, "a", "g", self.cutoff)["counts"]["due_messages"], 0)
        self.assertEqual(detail(self.db, due["items"][0]["id"])["content_status"], "available")

    def test_scope_and_duplicate_observations_counted_without_duplicate_messages(self):
        rows = [record("same"), record("same", "b"), record("same", group="other")]
        self.ingest(rows)
        self.ingest(rows)
        counts = preview(self.db, "a", "g", self.cutoff)["counts"]
        self.assertEqual(counts, {"total_messages": 1, "due_messages": 1,
                                 "already_unavailable_messages": 0, "status_counts": {"available": 1},
                                 "due_segments": 2, "due_observations": 2, "due_raw_observations": 2,
                                 "managed_media_files": 0})

    def test_pagination_is_stable_and_contains_only_candidates(self):
        self.ingest([record("b"), record("a"), record("c")])
        first = preview(self.db, "a", "g", self.cutoff, limit=2)
        self.assertEqual([row["external_id"] for row in first["items"]], ["a", "b"])
        self.assertEqual(first["next_offset"], 2)
        second = preview(self.db, "a", "g", self.cutoff, limit=2, offset=2)
        self.assertEqual([row["external_id"] for row in second["items"]], ["c"])
        self.assertIsNone(second["next_offset"])
        beyond = preview(self.db, "a", "g", self.cutoff, offset=20)
        self.assertEqual(beyond["items"], [])
        self.assertIsNone(beyond["next_offset"])

    def test_unavailable_messages_counted_but_not_candidates(self):
        self.ingest([record("available"), record("expired"), record("withdrawn")])
        with self.db:
            self.db.execute("UPDATE messages SET content_status='expired' WHERE external_id='expired'")
            self.db.execute("UPDATE messages SET content_status='withdrawn' WHERE external_id='withdrawn'")
        result = preview(self.db, "a", "g", self.cutoff)
        self.assertEqual(result["counts"]["already_unavailable_messages"], 2)
        self.assertEqual(result["counts"]["status_counts"], {"available": 1, "expired": 1, "withdrawn": 1})
        self.assertEqual([item["external_id"] for item in result["items"]], ["available"])
        self.assertEqual(result["counts"]["due_observations"], 1)

    def test_observations_without_raw_data_are_counted_separately(self):
        self.ingest([record("one")])
        self.ingest([record("one")])
        with self.db:
            self.db.execute("UPDATE observations SET raw_json=NULL WHERE rowid="
                            "(SELECT min(rowid) FROM observations)")
        counts = preview(self.db, "a", "g", self.cutoff)["counts"]
        self.assertEqual(counts["due_observations"], 2)
        self.assertEqual(counts["due_raw_observations"], 1)

    def test_stored_invalid_expiry_rolls_back_without_closing_connection(self):
        self.ingest([record("one")])
        with self.db:
            self.db.execute("UPDATE messages SET expires_at=?", (-(2 ** 63) + 1,))
        with self.assertRaisesRegex(ValueError, "INVALID_WINDOW"):
            preview(self.db, "a", "g", self.cutoff)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute("SELECT count(*) FROM messages").fetchone()[0], 1)

    def test_empty_database_and_current_time(self):
        result = preview(self.db, "a", "g")
        self.assertEqual(result["counts"]["total_messages"], 0)
        self.assertEqual(result["counts"]["due_observations"], 0)
        self.assertEqual(result["items"], [])
        self.assertIsNone(result["next_offset"])
        self.assertTrue(result["as_of"].endswith("+08:00"))
        self.assertEqual(result["policy"], {"raw_days": 3, "digest_days": 10,
                                           "digest_storage_implemented": False, "retention_active": False})

    def test_readonly_repeatable_and_metadata_does_not_contain_source(self):
        self.ingest([record("one")])
        before = self.path.read_bytes()
        changes = self.db.total_changes
        readonly = connect(self.path, readonly=True)
        try:
            first = preview(readonly, "a", "g", self.cutoff)
            self.assertEqual(first, preview(readonly, "a", "g", self.cutoff))
            self.assertFalse(readonly.in_transaction)
            self.assertTrue(first["readonly"])
            self.assertFalse(first["executed"])
            self.assertEqual(set(first["items"][0]), {"id", "external_id", "expires_at", "content_status",
                                                      "segment_count", "observation_count"})
            for secret in ("secret-source-body", "secret-name", "secret-resource", "secret-sender"):
                self.assertNotIn(secret, json.dumps(first))
        finally:
            readonly.close()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.db.total_changes, changes)

    def test_non_synthetic_rejected_only_in_requested_scope_and_transaction_recovered(self):
        self.ingest([record("one"), record("other", "b")])
        with self.db:
            self.db.execute("UPDATE messages SET namespace='onebot.v1' WHERE account_id='b'")
        self.assertEqual(preview(self.db, "a", "g", self.cutoff)["counts"]["due_messages"], 1)
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_ONLY"):
            preview(self.db, "b", "g", self.cutoff)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute("SELECT count(*) FROM messages").fetchone()[0], 2)

    def test_invalid_arguments_and_active_transaction(self):
        for account, group in (("", "g"), ("a", " "), (None, "g"), (3, "g")):
            with self.assertRaisesRegex(ValueError, "INVALID_RETENTION_SCOPE"):
                preview(self.db, account, group, self.cutoff)
        for params in ({"limit": 0}, {"limit": 101}, {"limit": True}, {"offset": -1},
                       {"offset": 1.2}, {"offset": 2 ** 100}):
            with self.assertRaisesRegex(ValueError, "INVALID_PAGINATION"):
                preview(self.db, "a", "g", self.cutoff, **params)
        for date in (True, "2026-10-13", 1.2, 10 ** 30, -(10 ** 30)):
            with self.assertRaisesRegex(ValueError, "INVALID_AS_OF"):
                preview(self.db, "a", "g", date)
        self.db.execute("BEGIN")
        with self.assertRaisesRegex(ValueError, "ACTIVE_TRANSACTION"):
            preview(self.db, "a", "g", self.cutoff)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
