"""CLI and read-only HTTP integration for independently stored Mock jobs."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.cli import main
from qq_radar.demo import prepare_demo, prepare_jobs
from qq_radar.domain import timestamp_ms
from qq_radar.server import create_server

CLOCK = "2026-10-11T12:00:00+08:00"


class JobsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.db"
        self.jobs = self.root / "source.jobs.db"
        prepare_demo(self.source)

    def cli(self, *args):
        out, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(errors):
            code = main(["--db", str(self.source), *args])
        return code, json.loads(out.getvalue() if code == 0 else errors.getvalue())

    def start(self, jobs_path=None):
        server = create_server(self.source, 0, jobs_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_port}"

    def test_cli_roundtrip_and_invalid_window_error_without_paths(self):
        code, result = self.cli("jobs-enqueue", "--account", "demo-account", "--group", "demo-tech",
                                "--since", "2026-10-10T10:00:00+08:00", "--until", "2026-10-10T11:00:00+08:00", "--as-of", CLOCK)
        self.assertEqual((code, result["inserted"]), (0, 1))
        self.assertEqual(self.cli("jobs-run", "--as-of", CLOCK)[1]["succeeded"], 1)
        self.assertEqual(len(self.cli("jobs-list", "--account", "demo-account", "--group", "demo-tech")[1]), 1)
        card = self.cli("feed", "--account", "demo-account", "--group", "demo-tech", "--as-of", CLOCK)[1]["items"][0]
        self.assertEqual(len(card["points"]), 3)
        code, result = self.cli("jobs-enqueue", "--account", "demo-account", "--group", "demo-tech",
                                "--since", "2026-10-10T10:01:00+08:00", "--until", "2026-10-10T11:00:00+08:00", "--as-of", CLOCK)
        self.assertEqual(code, 2)
        self.assertEqual(set(result), {"code"})
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_http_feed_jobs_and_databases_remain_unchanged(self):
        self.assertEqual(prepare_jobs(self.source, as_of=timestamp_ms(CLOCK))["succeeded"], 8)
        before = {path: path.read_bytes() for path in (self.source, self.jobs)}
        base = self.start()
        query = "?account=demo-account&group=demo-tech&as_of=2026-10-11T12%3A00%3A00%2B08%3A00"
        with urlopen(base + "/api/v1/feed" + query) as response:
            result = json.load(response)
        self.assertEqual(len(result["items"]), 4)
        with urlopen(base + "/api/v1/jobs" + query) as response:
            self.assertEqual(len(json.load(response)), 4)
        with self.assertRaises(HTTPError) as failed:
            urlopen(Request(base + "/api/v1/feed", data=b"{}", method="POST"))
        self.assertEqual(failed.exception.code, 405)
        failed.exception.close()
        for path, original in before.items():
            self.assertEqual(path.read_bytes(), original)

    def test_missing_jobs_not_created_by_server_or_read_cli(self):
        base = self.start()
        with urlopen(base + "/api/v1/feed?account=demo-account&group=demo-tech") as response:
            self.assertFalse(json.load(response)["configured"])
        with urlopen(base + "/api/v1/jobs?account=demo-account&group=demo-tech") as response:
            self.assertEqual(json.load(response), [])
        self.assertEqual(self.cli("feed", "--account", "demo-account", "--group", "demo-tech")[0], 2)
        self.assertEqual(self.cli("jobs-list", "--account", "demo-account", "--group", "demo-tech")[0], 2)
        self.assertFalse(self.jobs.exists())

    def test_wrong_jobs_database_and_colliding_path_rejected(self):
        before = self.source.read_bytes()
        with self.assertRaises(ValueError):
            create_server(self.source, 0, self.source)
        wrong = self.root / "wrong.db"
        prepare_demo(wrong)
        with self.assertRaises(ValueError):
            create_server(self.source, 0, wrong)
        code, _ = self.cli("--jobs-db", str(self.source), "jobs-run", "--as-of", CLOCK)
        self.assertEqual(code, 2)
        self.assertEqual(self.source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
