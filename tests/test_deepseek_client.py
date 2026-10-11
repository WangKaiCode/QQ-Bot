"""Mocked transport, strict local budget ledger and no-private-data checks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar import cli, deepseek_client, jobs, outbound, providers
from qq_radar.domain import timestamp_ms
from qq_radar.ingestion import import_file
from qq_radar.storage import connect

CLOCK = timestamp_ms("2026-10-11T12:00:00+08:00")
KEY = "synthetic-test-key-never-real"
TOPIC = {"id": "ai", "name": "AI", "keywords": ["AI"]}


class FakeResponse(io.BytesIO):
    status = 200
    def getcode(self):
        return self.status


class DeepSeekClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_path = self.root / "source.db"
        self.db = connect(self.source_path)
        self.addCleanup(self.db.close)
        self.ledger = self.root / "budget.db"
        row = {"schema_version": "synthetic.v1", "account_id": "synthetic-account",
               "group_id": "synthetic-group", "message_id": "one", "sender_id": "synthetic-sender",
               "timestamp": "2026-10-11T10:00:00+08:00",
               "segments": [{"type": "text", "text": "AI private synthetic source body."}]}
        path = self.root / "input.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual(import_file(self.db, path, {("synthetic-account", "synthetic-group")})["counts"]["failed"], 0)
        self.candidate = outbound.prepare(self.db, "synthetic-account", "synthetic-group", TOPIC)
        self.request = providers.build_request(self.candidate)

    def reply_bytes(self):
        result = {"title": "AI update", "summary": "A synthetic update.",
                  "points": [{"text": "AI was discussed.", "evidence_ids": ["e1"]}]}
        return json.dumps({"choices": [{"index": 0, "finish_reason": "stop",
                                        "message": {"role": "assistant", "content": json.dumps(result)}}],
                           "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}).encode()

    def transport(self, data=None, failure=None):
        opener = MagicMock()
        if failure is not None:
            opener.open.side_effect = failure
        else:
            body = self.reply_bytes() if data is None else data
            opener.open.side_effect = lambda *args, **kwargs: FakeResponse(body)
        return patch("urllib.request.build_opener", return_value=opener), opener

    def call(self, request=None, **kwargs):
        return deepseek_client.call(self.request if request is None else request, KEY, self.ledger,
                                    as_of=CLOCK, **kwargs)

    def ledger_rows(self):
        with closing(sqlite3.connect(self.ledger)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM api_calls")]

    def test_success_sends_one_canonical_post_with_disabled_proxy_and_reserves_budget(self):
        before = list(self.db.iterdump())
        transport, opener = self.transport()
        with transport as factory:
            result = self.call()
        self.assertEqual(result["mode"], "synthetic-api")
        self.assertTrue(result["sent"])
        self.assertTrue(result["validated"])
        self.assertEqual(result["budget"]["month"], "2026-10")
        self.assertEqual(result["budget"]["reserved_cny"], 1)
        self.assertEqual(result["budget"]["monthly_reserved_cny"], 1)
        opener.open.assert_called_once()
        actual_request = opener.open.call_args.args[0]
        self.assertEqual(actual_request.get_method(), "POST")
        self.assertEqual(actual_request.full_url, self.request["endpoint"])
        self.assertEqual(json.loads(actual_request.data), self.request["request"])
        self.assertEqual(actual_request.get_header("Authorization"), "Bearer " + KEY)
        handlers = factory.call_args.args
        proxy = [handler for handler in handlers if hasattr(handler, "proxies")]
        self.assertEqual(len(proxy), 1)
        self.assertEqual(proxy[0].proxies, {})
        redirects = [handler for handler in handlers if isinstance(handler, HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsNone(redirects[0].redirect_request(actual_request, None, 302, "Redirect", {},
                                                      "https://untrusted.invalid"))
        rows = self.ledger_rows()
        self.assertEqual([(row["status"], row["reserved_micros"]) for row in rows], [("succeeded", 1000000)])
        with closing(sqlite3.connect(self.ledger)) as db:
            contents = "\n".join(db.iterdump())
        for private in (KEY, "private synthetic source body", "synthetic-account", "synthetic-group", "AI was discussed"):
            self.assertNotIn(private, contents)
        self.assertEqual(before, list(self.db.iterdump()))

    def test_duplicate_request_same_month_is_not_sent_or_reserved_twice(self):
        transport, opener = self.transport()
        with transport:
            self.call()
            with self.assertRaises(ValueError):
                self.call()
        opener.open.assert_called_once()
        self.assertEqual(len(self.ledger_rows()), 1)

    def test_timeout_http_and_invalid_replies_keep_reservation_without_retry(self):
        for index, failure in enumerate((TimeoutError("synthetic private timeout"), URLError("synthetic private URL"),
                                         HTTPError(self.request["endpoint"], 429, "synthetic private error", {}, None))):
            self.ledger = self.root / f"failure-{index}.db"
            transport, opener = self.transport(failure=failure)
            with self.subTest(failure=type(failure).__name__), transport:
                with self.assertRaises(ValueError) as captured:
                    self.call()
                self.assertNotIn("synthetic private", str(captured.exception))
                opener.open.assert_called_once()
            self.assertEqual(self.ledger_rows()[0]["reserved_micros"], 1000000)
            self.assertEqual(self.ledger_rows()[0]["status"], "failed")
        for index, data in enumerate((b"", b"{invalid", b"x" * 100001,
                                      json.dumps({"choices": [], "usage": {}}).encode())):
            self.ledger = self.root / f"invalid-{index}.db"
            transport, opener = self.transport(data=data)
            with self.subTest(data_length=len(data)), transport, self.assertRaises(ValueError):
                self.call()
            opener.open.assert_called_once()
            self.assertEqual([(row["status"], row["reserved_micros"]) for row in self.ledger_rows()], [("failed", 1000000)])

    def test_concurrent_distinct_attempts_cannot_exceed_monthly_cap(self):
        requests = []
        for index in range(6):
            candidate = deepcopy(self.candidate)
            candidate["payload"]["evidence"][0]["sanitized_text"] += f" scenario {index}"
            requests.append(providers.build_request(candidate))
        def attempt(request):
            try:
                return self.call(request, monthly_budget_cny=2)
            except ValueError:
                return None
        transport, opener = self.transport()
        with transport, ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, requests))
        self.assertEqual(sum(result is not None for result in results), 2)
        self.assertEqual(opener.open.call_count, 2)
        rows = self.ledger_rows()
        self.assertEqual(sum(row["reserved_micros"] for row in rows), 2000000)

    def test_failed_attempt_blocks_duplicate_and_still_consumes_budget(self):
        transport, opener = self.transport(data=b"{invalid")
        with transport:
            with self.assertRaises(ValueError):
                self.call(monthly_budget_cny=1)
            with self.assertRaises(ValueError):
                self.call(monthly_budget_cny=1)
            other = deepcopy(self.candidate)
            other["payload"]["evidence"][0]["sanitized_text"] += " different request"
            with self.assertRaises(ValueError):
                self.call(providers.build_request(other), monthly_budget_cny=1)
        opener.open.assert_called_once()
        self.assertEqual(sum(row["reserved_micros"] for row in self.ledger_rows()), 1000000)

    def test_truncated_reply_is_rejected_after_one_post_and_budget_is_retained(self):
        reply = json.loads(self.reply_bytes())
        reply["choices"][0]["finish_reason"] = "length"
        transport, opener = self.transport(data=json.dumps(reply).encode())
        with transport, self.assertRaises(ValueError):
            self.call()
        opener.open.assert_called_once()
        self.assertEqual(self.ledger_rows()[0]["reserved_micros"], 1000000)

    def test_interrupted_transport_keeps_reservation_and_database_can_reopen(self):
        transport, opener = self.transport(failure=KeyboardInterrupt)
        with transport:
            with self.assertRaises(KeyboardInterrupt):
                self.call()
        opener.open.assert_called_once()
        self.assertEqual([(row["status"], row["reserved_micros"]) for row in self.ledger_rows()], [("reserved", 1000000)])
        transport, opener = self.transport()
        with transport, self.assertRaises(ValueError):
            self.call()
        opener.open.assert_not_called()

    def test_invalid_budget_key_timeout_and_price_date_do_not_send_or_create_ledger(self):
        transport, opener = self.transport()
        with transport:
            for budget in (True, 0, -1, 21, 1.5, "20"):
                with self.subTest(budget=budget), self.assertRaises(ValueError):
                    self.call(monthly_budget_cny=budget)
                self.assertFalse(self.ledger.exists())
            for timeout in (True, 0, -1, "30"):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    self.call(timeout_seconds=timeout)
                self.assertFalse(self.ledger.exists())
            for key in ("", "line\nbreak", "line\rbreak", "control\x00key", None):
                with self.subTest(key=repr(key)), self.assertRaises(ValueError):
                    deepseek_client.call(self.request, key, self.ledger, as_of=CLOCK)
                self.assertFalse(self.ledger.exists())
            with self.assertRaisesRegex(ValueError, "PRICE_RECHECK_REQUIRED"):
                deepseek_client.call(self.request, KEY, self.ledger, as_of=CLOCK + 86400000)
            self.assertFalse(self.ledger.exists())
        opener.open.assert_not_called()

    def test_source_jobs_and_unrelated_ledgers_are_rejected_without_mutation(self):
        job_path = self.root / "jobs.db"
        job_db = jobs.connect(job_path)
        job_db.close()
        unrelated = self.root / "unrelated.db"
        with closing(sqlite3.connect(unrelated)) as db, db:
            db.execute("CREATE TABLE private (value TEXT)")
            db.execute("INSERT INTO private VALUES ('synthetic private')")
        transport, opener = self.transport()
        with transport:
            for path in (self.source_path, job_path, unrelated):
                before = path.read_bytes()
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    deepseek_client.call(self.request, KEY, path, as_of=CLOCK)
                self.assertEqual(before, path.read_bytes())
        opener.open.assert_not_called()

    def test_pro_model_and_tampered_endpoint_are_rejected_before_sending(self):
        values = [providers.build_request(self.candidate, model="deepseek-v4-pro")]
        changed = deepcopy(self.request)
        changed["endpoint"] = "https://untrusted.invalid"
        values.append(changed)
        transport, opener = self.transport()
        with transport:
            for request in values:
                with self.assertRaises(ValueError):
                    self.call(request)
                self.assertFalse(self.ledger.exists())
        opener.open.assert_not_called()

    def cli_command(self, command, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = ["--db", str(self.source_path), command, "--account", "synthetic-account",
                     "--group", "synthetic-group", *options]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def reviewed_hash(self):
        code, output, error = self.cli_command("provider-preview")
        self.assertEqual((code, error), (0, ""))
        return json.loads(output)["request_sha256"]

    def cli_call(self, config, review_hash, ledger=None):
        return self.cli_command("deepseek-call", "--config", str(config), "--ledger", str(ledger or self.ledger),
                                "--review-sha256", review_hash)

    def config(self, **changes):
        path = self.root / "synthetic-config.json"
        value = {"api_key": KEY, "monthly_budget_cny": 20}
        value.update(changes)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_cli_preview_review_and_fake_call_leave_source_and_secret_unchanged(self):
        review_hash = self.reviewed_hash()
        config = self.config()
        before, secret_before = list(self.db.iterdump()), config.read_bytes()
        transport, opener = self.transport()
        with transport, patch.object(deepseek_client.time, "time", return_value=CLOCK / 1000):
            code, output, error = self.cli_call(config, review_hash)
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertTrue(result["sent"])
        self.assertTrue(result["validated"])
        self.assertEqual(result["budget"]["monthly_reserved_cny"], 1)
        self.assertNotIn(KEY, output)
        self.assertEqual(before, list(self.db.iterdump()))
        self.assertEqual(secret_before, config.read_bytes())
        opener.open.assert_called_once()

    def test_cli_wrong_review_hash_fails_before_reading_secret_or_creating_ledger(self):
        config = self.config()
        real_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == config:
                raise AssertionError("configuration was read before review check")
            return real_open(path, *args, **kwargs)
        transport, opener = self.transport()
        with transport, patch.object(Path, "open", guarded_open):
            code, output, error = self.cli_call(config, "0" * 64)
        self.assertEqual((code, output), (2, ""))
        self.assertEqual(set(json.loads(error)), {"code"})
        self.assertFalse(self.ledger.exists())
        opener.open.assert_not_called()

    def test_cli_ledger_collision_protects_source_jobs_config_and_hardlink(self):
        review_hash = self.reviewed_hash()
        config = self.config()
        job_path = self.source_path.with_suffix(".jobs.db")
        database = jobs.connect(job_path)
        database.close()
        hardlink = self.root / "config-alias.db"
        os.link(config, hardlink)
        transport, opener = self.transport()
        with transport:
            for path in (self.source_path, job_path, config, hardlink):
                before = path.read_bytes()
                with self.subTest(path=path.name):
                    code, output, error = self.cli_call(config, review_hash, path)
                    self.assertEqual((code, output), (2, ""))
                    self.assertEqual(set(json.loads(error)), {"code"})
                    self.assertEqual(before, path.read_bytes())
        opener.open.assert_not_called()

    def test_cli_invalid_secret_and_config_limits_never_send_or_create_ledger(self):
        review_hash = self.reviewed_hash()
        transport, opener = self.transport()
        with transport:
            for value in ({"api_key": "bad\nkey"}, {"api_key": None},
                          {"monthly_budget_cny": True}, {"monthly_budget_cny": 21},
                          {"extra": "private extra"}):
                config = self.config(**value)
                with self.subTest(config=value):
                    code, output, error = self.cli_call(config, review_hash)
                    self.assertEqual((code, output), (2, ""))
                    self.assertEqual(set(json.loads(error)), {"code"})
                    self.assertNotIn(KEY, error)
                    self.assertFalse(self.ledger.exists())
            config.write_bytes(b"x" * 65537)
            code, output, error = self.cli_call(config, review_hash)
            self.assertEqual((code, output), (2, ""))
            self.assertEqual(set(json.loads(error)), {"code"})
            self.assertFalse(self.ledger.exists())
        opener.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
