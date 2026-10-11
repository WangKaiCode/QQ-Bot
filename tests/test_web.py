"""HTTP behavior and read-only source reader regressions."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.demo import prepare_demo
from qq_radar.server import create_server
from qq_radar.storage import connect


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "demo.db"
        self.result = prepare_demo(self.db_path)
        self.server = create_server(self.db_path, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, method="GET", headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            client.request(method, path, headers=headers or {})
            response = client.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            client.close()

    def get(self, path):
        status, headers, body = self.request(path)
        self.assertEqual(status, 200)
        return json.loads(body)

    def query(self, **params):
        return self.get("/api/v1/messages?" + urlencode({"account": "demo-account", "group": "demo-tech", **params}))

    def test_demo_repeat_and_import_report(self):
        self.assertEqual(self.result["counts"], {"seen": 12, "inserted": 8, "matched": 1, "failed": 2, "excluded": 1})
        replay = prepare_demo(self.db_path)
        self.assertEqual(replay["counts"]["inserted"], 0)
        self.assertEqual(replay["counts"]["matched"], 9)
        result = self.get("/api/v1/imports/" + self.result["id"])
        self.assertEqual([e["line"] for e in result["errors"]], [10, 11])
        self.assertNotIn("raw_json", json.dumps(result))
        self.assertEqual(len(self.get("/api/v1/imports")), 2)

    def test_query_pagination_account_isolation_and_context(self):
        first = self.query(limit=2)
        self.assertEqual(first["next_offset"], 2)
        second = self.query(limit=2, offset=2)
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        forward = self.query(keyword="网络条件")["items"]
        self.assertEqual(len(forward), 1)
        result = self.get("/api/v1/messages/" + forward[0]["id"] + "/context?radius=2")
        self.assertEqual(result["message"]["source"]["segments"][0]["type"], "forward")
        self.assertEqual([r["external_id"] for r in result["before"]], ["sample-01", "sample-02"])
        self.assertEqual([r["external_id"] for r in result["after"]], ["sample-04", "sample-05"])
        all_rows = result["before"] + [result["message"]] + result["after"]
        self.assertTrue(all(r["account_id"] == "demo-account" and r["group_id"] == "demo-tech" for r in all_rows))
        self.assertEqual(len(self.query(account="demo-second-account")["items"]), 1)
        self.assertEqual(len(self.get("/api/v1/conversations")), 3)

    def test_invalid_queries_unknown_paths_and_no_writes(self):
        for path in ("/api/v1/messages", "/api/v1/messages?account=a&group=g&limit=0",
                     "/api/v1/messages?account=a&group=g&offset=-1",
                     "/api/v1/messages?account=a&account=b&group=g",
                     "/api/v1/messages?account=a&group=g&since=bad"):
            status, _, body = self.request(path)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["code"], "INVALID_QUERY")
        for path in ("/api/v1/messages/missing", "/api/v1/imports/missing", "/../docs/status.md", "/data/demo.db"):
            self.assertEqual(self.request(path)[0], 404)
        digest = self.db_path.read_bytes()
        self.assertEqual(self.request("/api/v1/messages", method="POST")[0], 405)
        self.query()
        self.assertEqual(self.db_path.read_bytes(), digest)

    def test_host_origin_and_plain_text_rendering_contract(self):
        self.assertEqual(self.request("/api/v1/conversations", headers={"Host": "malicious.example"})[0], 403)
        self.assertEqual(self.request("/api/v1/conversations", headers={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("/api/v1/conversations", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        status, headers, html = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("合成数据".encode(), html)
        script = self.request("/app.js")[2].decode()
        self.assertNotIn("innerHTML", script)
        self.assertIn("textContent", script)
        # The actual browser check also imports and opens a hostile text sample.
        self.assertEqual(self.get("/api/v1/health"), {"mode": "synthetic", "readonly": True, "retention_active": False})

    def test_startup_rejects_missing_and_nonsynthetic_database(self):
        import sqlite3
        with self.assertRaises(sqlite3.OperationalError):
            create_server(Path(self.temp.name) / "missing.db", 0)
        db = connect(self.db_path)
        try:
            with db:
                db.execute("UPDATE messages SET namespace='not-synthetic' WHERE external_id='sample-01'")
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_ONLY"):
            create_server(self.db_path, 0)

    def test_analysis_preview_and_invalid_rules(self):
        topics = self.get("/api/v1/topics")
        self.assertEqual([topic["id"] for topic in topics], ["ai", "network"])
        before = self.db_path.read_bytes()
        route = "/api/v1/analysis/preview?" + urlencode({"account": "demo-account", "group": "demo-tech", "topic": "ai"})
        result = self.get(route)
        self.assertEqual(result["coverage"]["matched_messages"], 3)
        self.assertEqual(result["coverage"]["image_segments"], 2)
        self.assertEqual(result["coverage"]["unsupported_segments"], 1)
        self.assertFalse(result["persisted"])
        evidence = result["digests"][0]["evidence"]
        self.assertTrue(all(self.get("/api/v1/messages/" + item["message_id"])["account_id"] == "demo-account" for item in evidence))
        custom = self.get(route + "&keywords=" + urlencode({"x": "网络"})[2:])
        self.assertEqual(custom["coverage"]["matched_messages"], 1)
        for path in (route + "&kind=invalid", route + "&keywords=", route + "&topic=network", "/api/v1/analysis/preview?topic=ai"):
            self.assertEqual(self.request(path)[0], 400)
        self.assertEqual(self.db_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
