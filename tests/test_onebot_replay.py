"""Replay tests are synthetic and must not create database files or echo events."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.cli import main
from qq_radar.onebot_replay import replay


def frame(message_id=1, text="synthetic-private-text", group=200001):
    return {"schema_version": "onebot.replay.v1", "synthetic": True, "event": {
        "self_id": 100001, "post_type": "message", "message_type": "group", "group_id": group,
        "message_id": message_id, "user_id": 300001, "time": 1791640800, "message": text}}


class ReplayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "synthetic.jsonl"

    def write(self, values):
        self.path.write_text("\n".join(json.dumps(value) for value in values), encoding="utf-8")

    def test_cli_counts_dedup_conflict_scope_and_no_database(self):
        self.write([frame(), frame(), frame(text="synthetic-conflict"), frame(group=200002)])
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--db", str(self.root / "must-not-exist.db"), "onebot-replay", str(self.path),
                         "--account", "100001", "--group", "200001"])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["purged"])
        self.assertEqual(result["snapshot_phase"], "before_purge")
        for key in ("accepted", "matched", "conflicts", "excluded"):
            self.assertEqual(result["counts"][key], 1)
        for secret in ("private-text", "synthetic-conflict", "100001", "200001", "300001", "local_id", "token"):
            self.assertNotIn(secret, out.getvalue())
        self.assertEqual(list(self.root.glob("*.db")), [])

    def test_invalid_frames_have_line_codes_and_failure_exit(self):
        self.path.write_bytes(b'{"synthetic": false}\nnot-json\n')
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["onebot-replay", str(self.path), "--account", "100001", "--group", "200001"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["errors"], [
            {"line": 1, "code": "INVALID_SYNTHETIC_FRAME"}, {"line": 2, "code": "INVALID_SYNTHETIC_FRAME"}])

    def test_file_line_and_session_budgets(self):
        for raw in (b"", b"x" * 1048577, b"{}\n" * 1001):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                replay(self.path, "100001", "200001")
        self.write([frame(number) for number in range(101)])
        result = replay(self.path, "100001", "200001")
        self.assertEqual(result["retained_messages"], 100)
        self.assertEqual(result["errors"], [{"line": 101, "code": "SESSION_LIMIT"}])

    def test_missing_file_error_does_not_echo_path(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["onebot-replay", str(self.root / "sensitive-missing.jsonl"),
                         "--account", "100001", "--group", "200001"])
        self.assertEqual(code, 2)
        self.assertNotIn("sensitive", err.getvalue())
