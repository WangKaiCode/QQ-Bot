"""Actual loopback HTTP provider preview; no paid transport or state writes."""
from contextlib import redirect_stdout, redirect_stderr
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar import cli
from qq_radar.ingestion import import_file
from qq_radar.server import create_server
from qq_radar.storage import connect


class ProviderWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.db"
        self.writer = connect(self.source)
        self.addCleanup(self.writer.close)
        self.ingest("one", "AI safe synthetic discussion.")
        self.ingest("other-account", "AI foreign account text.", account="second-account")
        self.ingest("other-group", "AI foreign group text.", group="second-group")
        self.server = create_server(self.source, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def ingest(self, mid, text, account="synthetic-account", group="synthetic-group",
               when="2026-10-11T10:00:00+08:00"):
        row = {"schema_version": "synthetic.v1", "account_id": account, "group_id": group,
               "message_id": mid, "sender_id": "synthetic-sender", "sender_name": "合成测试昵称",
               "timestamp": when, "segments": [{"type": "text", "text": text}]}
        path = self.root / "input.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual(import_file(self.writer, path, {(account, group)})["counts"]["failed"], 0)

    def request(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def route(self, **options):
        return "/api/v1/provider/preview?" + urlencode({"account": "synthetic-account", "group": "synthetic-group",
                                                      "topic": "ai", **options})

    def preview(self, **options):
        status, headers, body = self.request(self.route(**options))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        return json.loads(body)

    def evidence(self, envelope):
        return json.loads(envelope["request"]["messages"][1]["content"])["evidence"]

    def test_http_preview_matches_cli_envelope_and_review_hash(self):
        result = self.preview()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--db", str(self.source), "provider-preview", "--account", "synthetic-account",
                             "--group", "synthetic-group"])
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertEqual(result, json.loads(stdout.getvalue()))
        self.assertFalse(result["allowed_to_send"])
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(len(result["request_sha256"]), 64)

    def test_account_and_group_isolate_candidate_source(self):
        default = self.evidence(self.preview())
        self.assertEqual([row["sanitized_text"] for row in default], ["AI safe synthetic discussion."])
        self.assertEqual(self.evidence(self.preview(account="second-account"))[0]["sanitized_text"], "AI foreign account text.")
        self.assertEqual(self.evidence(self.preview(group="second-group"))[0]["sanitized_text"], "AI foreign group text.")

    def test_custom_keywords_model_tokens_and_half_open_time(self):
        self.ingest("network", "网络 synthetic example.", when="2026-10-11T11:00:00+08:00")
        result = self.preview(keywords="网络", model="deepseek-v4-pro", max_tokens=128)
        self.assertEqual([row["sanitized_text"] for row in self.evidence(result)], ["网络 synthetic example."])
        self.assertEqual((result["request"]["model"], result["request"]["max_tokens"]), ("deepseek-v4-pro", 128))
        result = self.preview(since="2026-10-11T10:00:00+08:00", until="2026-10-11T11:00:00+08:00")
        self.assertEqual(len(self.evidence(result)), 1)

    def test_invalid_queries_do_not_echo_payload_or_allow_payment_controls(self):
        routes = ["/api/v1/provider/preview", self.route() + "&account=other",
                  self.route(model="unknown"), self.route(max_tokens=127), self.route(max_tokens=4097),
                  self.route(max_tokens="true"), self.route(since="invalid"), self.route(topic="unknown"),
                  self.route(keywords=""), self.route(since="2026-10-11T11:00:00+08:00", until="2026-10-11T10:00:00+08:00")]
        for route in routes:
            with self.subTest(route=route):
                status, _, body = self.request(route)
                self.assertEqual(status, 400)
                self.assertEqual(set(json.loads(body)), {"code", "request_id"})
                self.assertNotIn("synthetic discussion", body.decode())

    def test_no_paid_call_secret_read_database_or_ledger_write(self):
        config = self.root / "synthetic-config.json"
        config.write_text('{"api_key":"synthetic-private-key"}', encoding="utf-8")
        files_before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        real_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == config:
                raise AssertionError("provider preview must not read secret configuration")
            return real_open(path, *args, **kwargs)
        with patch("qq_radar.deepseek_client.call", side_effect=AssertionError("paid API forbidden")), \
                patch("urllib.request.build_opener", side_effect=AssertionError("external transport forbidden")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("external transport forbidden")), \
                patch.object(Path, "open", guarded_open):
            self.preview()
            self.preview(model="deepseek-v4-pro", max_tokens=4096)
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, files_before)

    def test_host_origin_method_and_unknown_route_guards(self):
        for headers in ({"Host": "untrusted.invalid"}, {"Origin": "https://untrusted.invalid"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(self.route(), headers=headers)[0], 403)
        self.assertEqual(self.request(self.route(), method="POST")[0], 405)
        for route in ("/api/v1/provider/call", "/api/v1/provider/config", "/api/v1/provider/preview/extra"):
            self.assertEqual(self.request(route)[0], 404)

    def test_hostile_source_is_json_text_not_html_and_identity_is_removed(self):
        hostile = 'AI <img src=x onerror="alert(1)"> 合成测试昵称'
        self.ingest("hostile", hostile)
        status, headers, body = self.request(self.route())
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        text = "\n".join(row["sanitized_text"] for row in self.evidence(json.loads(body)))
        self.assertIn('<img src=x onerror="alert(1)">', text)
        self.assertNotIn("合成测试昵称", text)
        self.assertNotIn("synthetic-sender", body.decode())
        script = self.request("/app.js")[2].decode()
        self.assertNotIn("innerHTML", script)

    def test_source_changed_to_non_synthetic_and_blocked_candidate_fail_closed(self):
        with self.writer:
            self.writer.execute("UPDATE messages SET namespace='onebot.v1' WHERE account_id='synthetic-account' AND group_id='synthetic-group'")
        before = self.source.read_bytes()
        status, _, body = self.request(self.route())
        self.assertEqual(status, 400)
        self.assertEqual(set(json.loads(body)), {"code", "request_id"})
        self.assertEqual(before, self.source.read_bytes())
        with self.writer:
            self.writer.execute("UPDATE messages SET namespace='synthetic.v1',sender_name='AI' WHERE account_id='synthetic-account' AND group_id='synthetic-group'")
        status, _, body = self.request(self.route())
        self.assertEqual(status, 400)
        self.assertEqual(set(json.loads(body)), {"code", "request_id"})


if __name__ == "__main__":
    unittest.main()
