"""Config checks happen before any listener or database; only synthetic inputs."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.cli import main


class ProbeCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "sensitive-config.json"
        self.config = {"account": "100001", "allowed_groups": ["200001"], "token": "synthetic-token-only-32-characters"}

    def invoke(self, value, port="8766"):
        self.path.write_text(json.dumps(value), encoding="utf-8")
        err = io.StringIO()
        with patch("qq_radar.probe_server.serve") as serve, redirect_stderr(err):
            code = main(["--db", str(self.root / "unused.db"), "probe-serve", "--config", str(self.path), "--port", port])
        self.assertNotIn("sensitive", err.getvalue())
        self.assertNotIn(self.config["token"], err.getvalue())
        self.assertFalse((self.root / "unused.db").exists())
        return code, serve

    def test_single_group_config_delegated_without_database(self):
        code, serve = self.invoke(self.config)
        self.assertEqual(code, 0)
        serve.assert_called_once_with(self.config, 8766)

    def test_unknown_fields_multiple_groups_bad_port_rejected(self):
        for value in ({**self.config, "unexpected": "secret"}, {**self.config, "allowed_groups": ["200001", "200002"]}, [],
                      {**self.config, "allowed_groups": "200001"}):
            code, serve = self.invoke(value)
            self.assertEqual(code, 2)
            serve.assert_not_called()
        code, serve = self.invoke(self.config, "65536")
        self.assertEqual(code, 2)
        serve.assert_not_called()

    def test_oversized_config_never_starts(self):
        for raw in (b" " * 65537, b"[" * 2000 + b"]" * 2000):
            self.path.write_bytes(raw)
            with patch("qq_radar.probe_server.serve") as serve, redirect_stderr(io.StringIO()):
                self.assertEqual(main(["probe-serve", "--config", str(self.path)]), 2)
            serve.assert_not_called()
