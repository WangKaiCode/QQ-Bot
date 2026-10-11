"""Synthetic scheduling recovery, closed-window and retention boundary checks."""
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar import cli, jobs, scheduler
from qq_radar.domain import timestamp_ms
from qq_radar.ingestion import import_file
from qq_radar.storage import connect

TOPIC = {"id": "ai", "name": "AI", "keywords": ["AI"]}
HOUR = 3600000
DAY = 24 * HOUR
MIDNIGHT = timestamp_ms("2026-10-11T00:00:00+08:00")


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_path = self.root / "source.db"
        self.jobs_path = self.root / "jobs.db"
        self.writer = connect(self.source_path)
        self.addCleanup(self.writer.close)
        self.source = connect(self.source_path, readonly=True)
        self.addCleanup(self.source.close)
        self.db = jobs.connect(self.jobs_path)
        self.addCleanup(self.db.close)

    def ingest(self, mid, when, text="AI private synthetic text", account="a", group="g"):
        row = {"schema_version": "synthetic.v1", "account_id": account, "group_id": group,
               "message_id": mid, "sender_id": "synthetic-user", "timestamp": when,
               "segments": [{"type": "text", "text": text}]}
        path = self.root / "input.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual(import_file(self.writer, path, {(account, group)})["counts"]["failed"], 0)

    def tick(self, clock=MIDNIGHT):
        return scheduler.tick(self.db, self.source, "a", "g", TOPIC, as_of=clock)

    def test_midnight_closes_previous_day_and_hour_only(self):
        self.ingest("previous", "2026-10-10T23:59:59.999+08:00")
        self.ingest("current", "2026-10-10T16:00:00Z")
        result = self.tick()
        self.assertEqual((result["mode"], result["scheduled"]), ("synthetic", True))
        self.assertEqual(result["as_of"], "2026-10-11T00:00:00+08:00")
        self.assertEqual(result["run"]["succeeded"], 2)
        rows = jobs.list_jobs(self.db, "a", "g")
        self.assertEqual({(row["kind"], row["window_start"], row["window_end"]) for row in rows},
                         {("hourly", MIDNIGHT - HOUR, MIDNIGHT), ("daily", MIDNIGHT - DAY, MIDNIGHT)})
        cards = jobs.feed(self.db, self.source, "a", "g", MIDNIGHT)["items"]
        self.assertTrue(all(len(card["evidence"]) == 1 for card in cards))

    def test_partial_hour_is_not_scheduled_until_exact_close(self):
        self.ingest("active", "2026-10-11T00:15:00+08:00")
        self.assertEqual(self.tick(MIDNIGHT + HOUR - 1)["run"]["succeeded"], 0)
        self.assertEqual(self.tick(MIDNIGHT + HOUR)["run"]["succeeded"], 1)
        rows = jobs.list_jobs(self.db, "a", "g")
        self.assertEqual([(row["kind"], row["window_end"]) for row in rows], [("hourly", MIDNIGHT + HOUR)])

    def test_bounded_lookback_is_aligned_to_closed_beijing_windows(self):
        clock = MIDNIGHT + HOUR + 12345
        with patch.object(scheduler.jobs, "enqueue", wraps=jobs.enqueue) as enqueue:
            self.tick(clock)
        self.assertEqual(enqueue.call_count, 2)
        hourly, daily = enqueue.call_args_list
        self.assertEqual(hourly.args[5:8], ("hourly", MIDNIGHT + HOUR - 72 * HOUR, MIDNIGHT + HOUR))
        self.assertEqual(daily.args[5:8], ("daily", MIDNIGHT - 3 * DAY, MIDNIGHT))

    def test_restart_is_idempotent_and_source_and_output_remain_private(self):
        self.ingest("one", "2026-10-10T23:15:00+08:00")
        before = list(self.source.iterdump())
        self.assertEqual(self.tick()["run"]["succeeded"], 2)
        fresh = jobs.connect(self.jobs_path)
        try:
            result = scheduler.tick(fresh, self.source, "a", "g", TOPIC, as_of=MIDNIGHT)
            self.assertEqual(result["run"]["succeeded"], 0)
            self.assertEqual(result["enqueue"]["hourly"]["matched"], 1)
            self.assertEqual(result["enqueue"]["daily"]["matched"], 1)
            self.assertEqual(len(jobs.list_jobs(fresh, "a", "g")), 2)
            self.assertNotIn("private synthetic text", "\n".join(fresh.iterdump()))
            self.assertNotIn("private synthetic text", json.dumps(result))
            self.assertNotIn("job_ids", json.dumps(result))
        finally:
            fresh.close()
        self.assertEqual(before, list(self.source.iterdump()))

    def test_downtime_backfills_only_unexpired_sources(self):
        self.ingest("expired", "2026-10-08T00:00:00+08:00")
        self.ingest("old-live", "2026-10-08T00:00:00.001+08:00")
        self.ingest("recent", "2026-10-10T22:00:00+08:00")
        result = self.tick()
        self.assertEqual(result["enqueue"]["hourly"]["inserted"], 2)
        self.assertEqual(result["enqueue"]["daily"]["inserted"], 2)
        self.assertEqual(result["run"]["succeeded"], 4)
        cards = jobs.feed(self.db, self.source, "a", "g", MIDNIGHT)["items"]
        self.assertTrue(all(len(card["evidence"]) == 1 for card in cards))

    def test_late_input_revises_closed_hour_and_day_without_duplicate_cards(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        self.tick()
        self.ingest("late", "2026-10-10T23:20:00+08:00")
        self.assertEqual(self.tick()["run"]["succeeded"], 2)
        cards = jobs.feed(self.db, self.source, "a", "g", MIDNIGHT)["items"]
        self.assertEqual(len(cards), 2)
        self.assertTrue(all(len(card["evidence"]) == 2 and not card["update_pending"] for card in cards))
        self.assertEqual(len(jobs.list_jobs(self.db, "a", "g")), 4)

    def test_real_namespace_rejected_even_outside_active_window(self):
        self.ingest("old", "2026-10-01T00:00:00+08:00")
        with self.writer:
            self.writer.execute("UPDATE messages SET namespace='onebot.v1'")
        before = list(self.db.iterdump())
        with self.assertRaises(ValueError):
            self.tick()
        self.assertEqual(before, list(self.db.iterdump()))

    def test_non_synthetic_batch_rejected_before_creating_job_database(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        with self.writer:
            self.writer.execute("UPDATE import_batches SET source_version='onebot.v1'")
        output = self.root / "never-created.db"
        with self.assertRaises(ValueError):
            scheduler.serve(self.source_path, output, "a", "g", TOPIC, max_ticks=1)
        self.assertFalse(output.exists())

    def test_unknown_version_one_source_rejected_without_claiming_it(self):
        unknown = self.root / "unrelated.db"
        with closing(sqlite3.connect(unknown)) as db, db:
            db.execute("CREATE TABLE unrelated (private_value TEXT)")
            db.execute("INSERT INTO unrelated VALUES ('private unrelated data')")
            db.execute("PRAGMA user_version=1")
        before = unknown.read_bytes()
        output = self.root / "never-created.db"
        with self.assertRaises(ValueError):
            scheduler.serve(unknown, output, "a", "g", TOPIC, max_ticks=1)
        self.assertEqual(before, unknown.read_bytes())
        self.assertFalse(output.exists())

    def test_tick_reclaims_expired_lease_but_preserves_active_worker(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        self.tick()
        with self.db:
            self.db.execute("UPDATE analysis_jobs SET status='running',attempts=1,claim_token='crashed',lease_until=?",
                            (MIDNIGHT + 300000,))
        self.assertEqual(self.tick(MIDNIGHT + 299999)["run"]["succeeded"], 0)
        self.assertEqual(self.tick(MIDNIGHT + 300000)["run"]["succeeded"], 2)
        self.assertTrue(all(row["status"] == "succeeded" and row["attempts"] == 2
                            for row in jobs.list_jobs(self.db, "a", "g")))

    def test_shared_job_database_preserves_other_account_group_and_topic(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        self.ingest("other-account", "2026-10-10T23:10:00+08:00", account="b")
        self.ingest("other-group", "2026-10-10T23:10:00+08:00", group="other")
        other_topic = {**TOPIC, "id": "other", "name": "Other"}
        preserved = []
        for account, group, topic in (("b", "g", TOPIC), ("a", "other", TOPIC), ("a", "g", other_topic)):
            result = jobs.enqueue(self.db, self.source, account, group, topic, "hourly",
                                  MIDNIGHT - HOUR, MIDNIGHT, as_of=MIDNIGHT)
            preserved.extend(result["job_ids"])
        self.assertEqual(self.tick()["run"]["succeeded"], 2)
        for job_id in preserved:
            row = self.db.execute("SELECT status,attempts FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
            self.assertEqual(tuple(row), ("pending", 0))

    def test_future_prequeued_window_stays_pending_until_it_closes(self):
        self.ingest("future", "2026-10-11T00:10:00+08:00")
        job_id = jobs.enqueue(self.db, self.source, "a", "g", TOPIC, "hourly",
                              MIDNIGHT, MIDNIGHT + HOUR, as_of=MIDNIGHT + HOUR)["job_ids"][0]
        self.assertEqual(self.tick()["run"]["succeeded"], 0)
        row = self.db.execute("SELECT status,attempts FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(tuple(row), ("pending", 0))
        self.assertEqual(self.tick(MIDNIGHT + HOUR)["run"]["succeeded"], 1)

    def test_database_collision_rejected_without_source_mutation(self):
        before = list(self.source.iterdump())
        with self.assertRaises(ValueError):
            scheduler.tick(self.source, self.source, "a", "g", TOPIC, as_of=MIDNIGHT)
        with self.assertRaises(ValueError):
            scheduler.serve(self.source_path, self.source_path, "a", "g", TOPIC, max_ticks=1)
        self.assertEqual(before, list(self.source.iterdump()))

    def test_finite_loop_reports_counts_and_sleeps_only_between_ticks(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        reports = []
        with patch.object(scheduler.time, "time", return_value=MIDNIGHT / 1000), \
                patch.object(scheduler.time, "sleep") as sleep:
            result = scheduler.serve(self.source_path, self.jobs_path, "a", "g", TOPIC,
                                     interval_seconds=2, max_ticks=2, reporter=reports.append)
        self.assertEqual(result["ticks"], 2)
        self.assertFalse(result["interrupted"])
        sleep.assert_called_once_with(2)
        self.assertEqual([row["run"]["succeeded"] for row in reports], [2, 0])
        self.assertNotIn("private synthetic text", json.dumps(reports))

    def test_loop_stop_and_keyboard_interrupt_exit_cleanly(self):
        stopped = threading.Event()
        stopped.set()
        result = scheduler.serve(self.source_path, self.jobs_path, "a", "g", TOPIC,
                                 max_ticks=2, stop_event=stopped)
        self.assertEqual(result["ticks"], 0)
        with patch.object(scheduler.time, "sleep", side_effect=KeyboardInterrupt):
            result = scheduler.serve(self.source_path, self.jobs_path, "a", "g", TOPIC, max_ticks=2)
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["ticks"], 1)

    def test_invalid_loop_arguments_fail_before_database_creation(self):
        output = self.root / "never-created.db"
        for name, values in (("interval_seconds", (True, 0, -1, 3601, 1.5, "2")),
                             ("max_ticks", (True, 0, -1, 10001, 1.5, "2"))):
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        scheduler.serve(self.source_path, output, "a", "g", TOPIC, **{name: value})
                    self.assertFalse(output.exists())

    def test_invalid_clock_fails_without_job_writes(self):
        before = list(self.db.iterdump())
        for clock in (True, 1.5, "2", 10 ** 30):
            with self.subTest(clock=clock):
                with self.assertRaises(ValueError):
                    self.tick(clock)
        self.assertEqual(before, list(self.db.iterdump()))

    def run_cli(self, output, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["--db", str(self.source_path), "--jobs-db", str(output), "jobs-schedule",
                "--account", "a", "--group", "g", "--max-ticks", "1", *options]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_single_tick_restart_has_no_duplicate_work(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        before = list(self.source.iterdump())
        with patch.object(scheduler.time, "time", return_value=MIDNIGHT / 1000):
            first = self.run_cli(self.jobs_path)
            second = self.run_cli(self.jobs_path)
        for code, output, error in (first, second):
            self.assertEqual((code, error), (0, ""))
            lines = output.splitlines()
            summary = json.loads("\n".join(lines[1:]))
            self.assertEqual(summary["ticks"], 1)
            self.assertTrue(summary["scheduled"])
            self.assertNotIn("private synthetic text", output)
        self.assertEqual(json.loads(first[1].splitlines()[0])["run"]["succeeded"], 2)
        self.assertEqual(json.loads(second[1].splitlines()[0])["run"]["succeeded"], 0)
        self.assertEqual(len(jobs.list_jobs(self.db, "a", "g")), 2)
        self.assertEqual(before, list(self.source.iterdump()))

    def test_cli_invalid_parameters_and_unknown_topic_do_not_create_database(self):
        output = self.root / "never-created.db"
        for options in (("--interval", "0"), ("--interval", "3601"),
                        ("--max-ticks", "0"), ("--max-ticks", "10001"),
                        ("--topic", "unknown")):
            with self.subTest(options=options):
                code, stdout, stderr = self.run_cli(output, *options)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr)
                self.assertFalse(output.exists())

    def test_cli_non_synthetic_source_is_rejected_without_creating_database(self):
        self.ingest("one", "2026-10-10T23:10:00+08:00")
        with self.writer:
            self.writer.execute("UPDATE messages SET namespace='onebot.v1'")
        output = self.root / "never-created.db"
        code, stdout, stderr = self.run_cli(output)
        self.assertEqual((code, stdout), (2, ""))
        self.assertNotIn("private synthetic text", stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
