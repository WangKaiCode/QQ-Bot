"""Read-only local budget reporting and Beijing-month boundary checks."""
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar import cli, deepseek_client, jobs
from qq_radar.domain import timestamp_ms
from qq_radar.storage import connect

CLOCK = timestamp_ms("2026-10-11T12:00:00+08:00")


class BudgetStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / "budget.db"

    def create_ledger(self, records):
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.executescript(deepseek_client.SCHEMA)
            db.execute("INSERT INTO ledger_metadata VALUES (?)", (deepseek_client.MAGIC,))
            for index, (month, status) in enumerate(records):
                db.execute("INSERT INTO api_calls(id,month,request_hash,reserved_micros,status,error_code,created_at,usage_json) "
                           "VALUES (?,?,?,1000000,?,?,?,?)",
                           (f"private-uuid-{index}", month, f"private-hash-{index}", status,
                            "DEEPSEEK_NETWORK_ERROR" if status == "failed" else None, CLOCK,
                            json.dumps({"prompt_tokens": 100}) if status == "succeeded" else None))

    def status(self, **kwargs):
        return deepseek_client.budget_status(self.ledger, as_of=CLOCK, **kwargs)

    def test_reserved_failed_and_successful_attempts_all_consume_budget(self):
        self.create_ledger([("2026-10", "reserved"), ("2026-10", "failed"), ("2026-10", "succeeded"),
                            ("2026-10", "failed"), ("2026-09", "succeeded")])
        result = self.status()
        self.assertEqual(result, {"month": "2026-10", "monthly_limit_cny": 20, "monthly_reserved_cny": 4,
                                  "remaining_cny": 16, "counts": {"reserved": 1, "succeeded": 1, "failed": 2}})
        for private in ("private-hash", "private-uuid", "DEEPSEEK_NETWORK_ERROR", "prompt_tokens"):
            self.assertNotIn(private, json.dumps(result))

    def test_beijing_month_changes_at_local_midnight_and_needs_no_current_quote(self):
        self.create_ledger([("2026-10", "failed"), ("2026-11", "reserved"), ("2026-11", "succeeded")])
        boundary = timestamp_ms("2026-10-31T16:00:00Z")
        old = deepseek_client.budget_status(self.ledger, as_of=boundary - 1)
        new = deepseek_client.budget_status(self.ledger, as_of=boundary)
        self.assertEqual((old["month"], old["monthly_reserved_cny"]), ("2026-10", 1))
        self.assertEqual((new["month"], new["monthly_reserved_cny"]), ("2026-11", 2))
        future = deepseek_client.budget_status(self.ledger, as_of=timestamp_ms("2030-01-01T00:00:00+08:00"))
        self.assertEqual(future["monthly_reserved_cny"], 0)
        self.assertEqual(future["remaining_cny"], 20)

    def test_remaining_is_zero_when_requested_limit_is_below_previous_reservations(self):
        self.create_ledger([("2026-10", "failed")] * 3)
        result = self.status(monthly_budget_cny=1)
        self.assertEqual(result["monthly_reserved_cny"], 3)
        self.assertEqual(result["monthly_limit_cny"], 1)
        self.assertEqual(result["remaining_cny"], 0)

    def test_missing_ledger_returns_zero_without_creating_parent_or_files(self):
        self.ledger = self.root / "uncreated" / "nested" / "budget.db"
        result = self.status(monthly_budget_cny=2)
        self.assertEqual(result["monthly_reserved_cny"], 0)
        self.assertEqual(result["remaining_cny"], 2)
        self.assertEqual(result["counts"], {"reserved": 0, "failed": 0, "succeeded": 0})
        self.assertFalse((self.root / "uncreated").exists())

    def test_reporting_is_readonly_repeatable_has_no_network_and_closes_connection(self):
        self.create_ledger([("2026-10", "succeeded"), ("2026-10", "reserved")])
        before = self.ledger.read_bytes()
        files_before = {path.name for path in self.root.iterdir()}
        with patch("urllib.request.build_opener", side_effect=AssertionError("network forbidden")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            first = self.status()
            self.assertEqual(first, self.status())
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual({path.name for path in self.root.iterdir()}, files_before)
        # A fresh writer confirms report has not retained a transaction or handle.
        with closing(sqlite3.connect(self.ledger, timeout=0)) as db, db:
            db.execute("UPDATE api_calls SET status='failed' WHERE status='reserved'")
        self.assertEqual(self.status()["counts"]["failed"], 1)

    def test_invalid_budget_and_clock_do_not_create_missing_ledger(self):
        for budget in (True, 0, -1, 21, 1.5, "20", None):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.status(monthly_budget_cny=budget)
        for clock in (True, 1.5, "2", 10 ** 30, -(10 ** 30)):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                deepseek_client.budget_status(self.ledger, as_of=clock)
        self.assertFalse(self.ledger.exists())

    def test_unrelated_source_jobs_and_corrupt_files_are_not_modified(self):
        source = self.root / "source.db"
        db = connect(source)
        db.close()
        job_path = self.root / "jobs.db"
        db = jobs.connect(job_path)
        db.close()
        corrupt = self.root / "corrupt.db"
        corrupt.write_bytes(b"synthetic private corrupt database")
        empty = self.root / "empty.db"
        empty.write_bytes(b"")
        for path in (source, job_path, corrupt, empty):
            before = path.read_bytes()
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                deepseek_client.budget_status(path, as_of=CLOCK)
            self.assertEqual(before, path.read_bytes())

    def test_tampered_ledger_magic_and_invalid_reservation_fail_closed(self):
        self.create_ledger([("2026-10", "failed")])
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("UPDATE ledger_metadata SET magic='untrusted'")
        before = self.ledger.read_bytes()
        with self.assertRaises(ValueError):
            self.status()
        self.assertEqual(before, self.ledger.read_bytes())
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("UPDATE ledger_metadata SET magic=?", (deepseek_client.MAGIC,))
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE api_calls SET reserved_micros=-1000000")
        before = self.ledger.read_bytes()
        with self.assertRaises(ValueError):
            self.status()
        self.assertEqual(before, self.ledger.read_bytes())

    def cli_status(self, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--db", str(self.root / "missing-source.db"), "deepseek-budget",
                             "--ledger", str(self.ledger), "--as-of", "2026-10-11T12:00:00+08:00", *options])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_reports_without_source_key_or_network_and_leaves_files_unchanged(self):
        self.create_ledger([("2026-10", "failed")])
        before = self.ledger.read_bytes()
        files_before = {path.name for path in self.root.iterdir()}
        with patch("urllib.request.build_opener", side_effect=AssertionError("network forbidden")):
            code, output, error = self.cli_status("--monthly-budget", "2")
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertEqual(result["monthly_reserved_cny"], 1)
        self.assertEqual(result["remaining_cny"], 1)
        self.assertEqual(before, self.ledger.read_bytes())
        self.assertEqual({path.name for path in self.root.iterdir()}, files_before)
        self.assertFalse((self.root / "missing-source.db").exists())

    def test_cli_missing_ledger_and_invalid_budget_do_not_create_any_database(self):
        with patch("urllib.request.build_opener", side_effect=AssertionError("network forbidden")):
            code, output, error = self.cli_status()
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output)["monthly_reserved_cny"], 0)
            for value in ("0", "21", "-1"):
                with self.subTest(value=value):
                    code, output, error = self.cli_status("--monthly-budget", value)
                    self.assertEqual((code, output), (2, ""))
                    self.assertEqual(set(json.loads(error)), {"code"})
        self.assertFalse(self.ledger.exists())
        self.assertFalse((self.root / "missing-source.db").exists())


if __name__ == "__main__":
    unittest.main()
