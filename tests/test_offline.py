import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.cli import main
from qq_radar.ingestion import ImportAborted, import_file
from qq_radar.storage import connect, context, detail, report, search

FIXTURES = Path(__file__).parent / "fixtures"


def record(mid="one", **changes):
    result = {"schema_version": "synthetic.v1", "account_id": "a", "group_id": "g",
              "message_id": mid, "sender_id": "u", "timestamp": "2026-10-10T10:00:00+08:00",
              "segments": [{"type": "text", "text": "same text"}]}
    result.update(changes)
    return result


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "test.db")
        self.addCleanup(self.db.close)

    def ingest(self, records, allowed=None, chunk_size=200):
        path = self.root / "input.jsonl"
        path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        return import_file(self.db, path, allowed or {("a", "g")}, chunk_size)

    def test_replay_identity_and_conflict(self):
        first = self.ingest([record(), record("two"), record(account_id="b")], {("a", "g"), ("b", "g")})
        self.assertEqual(first["counts"]["inserted"], 3)
        replay = self.ingest([record(), record("two"), record(account_id="b")], {("a", "g"), ("b", "g")})
        self.assertEqual(replay["counts"]["matched"], 3)
        conflict = record(segments=[{"type": "text", "text": "changed"}])
        result = self.ingest([conflict])
        self.assertEqual(result["errors"][0]["error_code"], "IDENTITY_CONFLICT")
        self.assertEqual(search(self.db, "a", "g")[0]["text"], "same text")
        self.assertEqual(len(search(self.db, "b", "g")), 1)

    def test_order_and_context_isolation(self):
        self.ingest([record("z"), record("early", timestamp="2026-10-10T09:00:00+08:00"),
                     record("a"), record(group_id="other"), record(account_id="b")],
                    {("a", "g"), ("a", "other"), ("b", "g")})
        rows = search(self.db, "a", "g")
        self.assertEqual([r["external_id"] for r in rows], ["early", "a", "z"])
        around = context(self.db, rows[1]["id"])
        self.assertEqual([r["external_id"] for r in around["before"]], ["early"])
        self.assertEqual([r["external_id"] for r in around["after"]], ["z"])
        self.assertEqual(search(self.db, "a", "g", "' OR 1=1 --"), [])
        self.assertEqual(len(search(self.db, "a", "g", limit=1, offset=1)), 1)

    def test_nested_source_and_missing_media(self):
        allowed = {("demo-account", "demo-group"), ("demo-second-account", "demo-group")}
        result = import_file(self.db, FIXTURES / "synthetic.jsonl", allowed)
        self.assertEqual(result["counts"]["inserted"], 3)
        rows = search(self.db, "demo-account", "demo-group", "网络")
        source = detail(self.db, rows[0]["id"])
        self.assertEqual(source["source"]["segments"][0]["nodes"][0]["sender_id"], "synthetic-forward-user")
        states = {r["kind"]: r["state"] for r in source["segments"]}
        self.assertEqual(states["image"], "not_fetched")
        self.assertEqual(states["future_segment"], "unsupported")
        self.assertEqual(source["segments"][-1]["parent_path"], "segments/0/nodes/0/segments/1/nodes/0")

    def test_errors_and_allowlist_never_store_excluded_body(self):
        missing = record()
        del missing["sender_id"]
        result = self.ingest(["{bad", missing, record(timestamp="no time"),
                              record(group_id="excluded", segments=[{"type": "text", "text": "EXCLUDED_SECRET_MARKER"}]),
                              record("ok"), record("naive", timestamp="2026-10-10T10:00:00")])
        self.assertEqual(result["counts"], {"seen": 6, "inserted": 1, "matched": 0, "failed": 4, "excluded": 1})
        self.assertEqual([e["line"] for e in result["errors"]], [1, 2, 3, 6])
        self.assertNotIn("EXCLUDED_SECRET_MARKER", "\n".join(self.db.iterdump()))
        self.assertEqual(result["status"], "completed_with_errors")

    def test_commit_failure_rolls_back_and_replay_recovers(self):
        # SQLite trigger aborts an actual write after a message insert. First
        # chunk commits; second chunk and its checkpoint must roll back.
        self.db.executescript("CREATE TRIGGER fail_row BEFORE INSERT ON observations WHEN NEW.line=2 BEGIN SELECT RAISE(ABORT, 'injected'); END;")
        with self.assertRaises(ImportAborted) as failure:
            self.ingest([record("one"), record("two"), record("three")], chunk_size=1)
        result = report(self.db, failure.exception.batch_id)
        self.assertEqual(result["committed_line"], 1)
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(len(search(self.db, "a", "g")), 1)
        self.db.execute("DROP TRIGGER fail_row")
        replay = self.ingest([record("one"), record("two"), record("three")])
        self.assertEqual(replay["counts"]["matched"], 1)
        self.assertEqual(replay["counts"]["inserted"], 2)

    def test_process_termination_has_committed_progress_only(self):
        path = self.root / "crash.jsonl"
        path.write_text("\n".join(json.dumps(record(str(i))) for i in range(3)), encoding="utf-8")
        crash_db = self.root / "crash.db"
        code = """
import os, sys
from qq_radar import ingestion
from qq_radar.storage import connect
original = ingestion.process_line
def crash(db, batch, line, raw, allowed):
    original(db, batch, line, raw, allowed)
    if line == 2: os._exit(37)
ingestion.process_line = crash
ingestion.import_file(connect(sys.argv[1]), sys.argv[2], {('a', 'g')}, chunk_size=1)
"""
        import os
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        process = subprocess.run([sys.executable, "-c", code, str(crash_db), str(path)], env=env, capture_output=True)
        self.assertEqual(process.returncode, 37)
        db = connect(crash_db)
        try:
            batch_id = db.execute("SELECT id FROM import_batches").fetchone()[0]
            self.assertEqual(report(db, batch_id)["committed_line"], 1)
            self.assertEqual(report(db, batch_id)["status"], "running")
            recovered = import_file(db, path, {("a", "g")})
            self.assertEqual(recovered["counts"]["inserted"], 2)
            self.assertEqual(recovered["counts"]["matched"], 1)
        finally:
            db.close()

    def test_cli_roundtrip_and_exit_codes(self):
        args = ["--db", str(self.root / "cli.db")]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ["import", str(FIXTURES / "synthetic.jsonl"), "--allow", str(FIXTURES / "allowlist.json")]), 0)
        imported = json.loads(output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ["report", imported["id"]]), 0)
        self.assertEqual(json.loads(output.getvalue())["counts"]["inserted"], 3)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["show", "missing"]), 2)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args + ["query", "--account", "demo-account", "--group", "demo-group"]), 0)

    def test_size_depth_and_nonstandard_json(self):
        nested = [{"type": "text", "text": "deep"}]
        for _ in range(18):
            nested = [{"type": "forward", "nodes": [{"segments": nested}]}]
        result = self.ingest(["x" * (2 * 1024 * 1024), record("depth", segments=nested),
                              '{"account_id":"a","group_id":"g","value":NaN}',
                              record("valid")])
        self.assertEqual([e["error_code"] for e in result["errors"]], ["LINE_LIMIT", "DEPTH_LIMIT", "INVALID_JSON"])
        self.assertEqual(result["committed_line"], 4)
        self.assertEqual(result["counts"]["inserted"], 1)

    def test_time_filters_and_invalid_utf8(self):
        from qq_radar.domain import timestamp_ms
        self.ingest([record("early", timestamp="2026-10-10T09:00:00+08:00"), record("later")])
        self.assertEqual([r["external_id"] for r in search(self.db, "a", "g", since=timestamp_ms("2026-10-10T02:00:00Z"))], ["later"])
        self.assertEqual([r["external_id"] for r in search(self.db, "a", "g", until=timestamp_ms("2026-10-10T10:00:00+08:00"))], ["early"])
        path = self.root / "bad-encoding.jsonl"
        path.write_bytes(b"\xff\n" + json.dumps(record("ok")).encode())
        result = import_file(self.db, path, {("a", "g")})
        self.assertEqual(result["errors"][0]["error_code"], "INVALID_JSON")
        self.assertEqual(result["counts"]["seen"], 2)

    def test_equivalent_key_order_matches_and_cli_row_failure(self):
        self.ingest([record()])
        reordered = dict(reversed(list(record().items())))
        self.assertEqual(self.ingest([reordered])["counts"]["matched"], 1)
        allowed = self.root / "allow.json"
        allowed.write_text('[{"account_id":"a","group_id":"g"}]', encoding="utf-8")
        path = self.root / "failure.jsonl"
        path.write_text("bad json\n", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.root / "test.db"), "import", str(path), "--allow", str(allowed)]), 1)
        self.assertEqual(json.loads(output.getvalue())["counts"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
