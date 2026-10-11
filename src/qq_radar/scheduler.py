"""Sequential local scheduler for completed synthetic Mock hour/day windows."""
import sqlite3
import time
from pathlib import Path

from . import jobs
from .analysis import iso, validate_keywords, window_start

HOUR = 3600000
DAY = 86400000
SOURCE_TABLES = {"import_batches", "messages", "message_segments", "observations"}


def _source_gate(source):
    """Validate the source even when no window contains a matching message."""
    tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != SOURCE_TABLES or source.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("UNRECOGNIZED_SOURCE_DATABASE")
    # Schema probes make an empty unrelated database fail closed as well.
    source.execute("SELECT id,account_id,group_id,namespace,occurred_at,expires_at,payload_hash,content_status FROM messages LIMIT 0")
    source.execute("SELECT message_id,path,kind,state,metadata FROM message_segments LIMIT 0")
    source.execute("SELECT id,file_sha256,source_version,status,started_at,finished_at,committed_line,failure_code FROM import_batches LIMIT 0")
    source.execute("SELECT batch_id,line,state,error_code,field,message_id,payload_hash,raw_json FROM observations LIMIT 0")
    if (source.execute("SELECT 1 FROM messages WHERE namespace IS NULL OR namespace<>'synthetic.v1' LIMIT 1").fetchone()
            or source.execute("SELECT 1 FROM import_batches WHERE source_version IS NULL OR source_version<>'synthetic.v1' LIMIT 1").fetchone()):
        raise ValueError("SYNTHETIC_AVAILABLE_ONLY")


def _jobs_gate(database):
    tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != {"jobs_metadata", "analysis_jobs"} or database.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("UNRECOGNIZED_JOBS_DATABASE")
    if [row[0] for row in database.execute("SELECT magic FROM jobs_metadata")] != [jobs.MAGIC]:
        raise ValueError("UNRECOGNIZED_JOBS_DATABASE")


def _scope(account, group, topic):
    if not isinstance(account, str) or not account or not isinstance(group, str) or not group:
        raise ValueError("INVALID_JOB_SCOPE")
    if not isinstance(topic, dict) or not isinstance(topic.get("name"), str) or not topic["name"].strip():
        raise ValueError("INVALID_TOPIC")
    if "id" in topic and (not isinstance(topic["id"], str) or not topic["id"]):
        raise ValueError("INVALID_TOPIC")
    validate_keywords(topic.get("keywords"))


def tick(jobs_db, source_db, account, group, topic, as_of=None):
    """Backfill at most 72 complete hours/3 complete Beijing days, then run once.

    Source expiry and input revisions follow the existing job engine. No source
    body, account identifiers, rule text, or job identifiers enter this report.
    """
    jobs._separate(jobs_db, source_db)
    _scope(account, group, topic)
    clock = jobs._now(as_of)
    _source_gate(source_db)
    _jobs_gate(jobs_db)
    report = {"mode": "synthetic", "scheduled": True, "as_of": iso(clock), "enqueue": {}}
    for kind, duration, count in (("hourly", HOUR, 72), ("daily", DAY, 3)):
        end = window_start(clock, kind)
        result = jobs.enqueue(jobs_db, source_db, account, group, topic, kind,
                              end - count * duration, end, as_of=clock)
        report["enqueue"][kind] = {key: result[key] for key in ("inserted", "matched", "empty_windows")}
    result = jobs.run(jobs_db, source_db, as_of=clock, account=account, group=group, topic=topic)
    report["run"] = {key: result[key] for key in ("succeeded", "failed", "superseded", "expired")}
    return report


def _paths(source_path, jobs_path):
    try:
        source = Path(source_path).resolve()
        destination = Path(jobs_path).resolve()
        if source == destination or (source.exists() and destination.exists() and source.samefile(destination)):
            raise ValueError("SOURCE_JOBS_PATH_COLLISION")
        return source, destination
    except (TypeError, OSError, RuntimeError) as exc:
        raise ValueError("INVALID_SCHEDULER_PATH") from exc


def serve(source_path, jobs_path, account, group, topic, interval_seconds=60, max_ticks=None,
          *, stop_event=None, reporter=None):
    """Run foreground ticks serially; close both databases before waiting.

    ``reporter`` receives each pure statistics report. ``stop_event`` optionally
    permits an embedding process to stop during the wait. KeyboardInterrupt
    returns normally with ``interrupted=True``. Operational errors fail closed
    with a stable code, never with a database path or source text.
    """
    if not isinstance(interval_seconds, int) or isinstance(interval_seconds, bool) or not 1 <= interval_seconds <= 3600:
        raise ValueError("INVALID_SCHEDULER_INTERVAL")
    if max_ticks is not None and (not isinstance(max_ticks, int) or isinstance(max_ticks, bool) or not 1 <= max_ticks <= 10000):
        raise ValueError("INVALID_SCHEDULER_MAX_TICKS")
    _scope(account, group, topic)
    source_path, jobs_path = _paths(source_path, jobs_path)
    summary = {"mode": "synthetic", "scheduled": True, "ticks": 0, "interrupted": False}
    try:
        while max_ticks is None or summary["ticks"] < max_ticks:
            if stop_event is not None and stop_event.is_set():
                break
            source_db = jobs_db = None
            try:
                # Own the connection before schema inspection, so a corrupt
                # source is still closed by this tick's finally block.
                source_db = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=5)
                source_db.row_factory = sqlite3.Row
                _source_gate(source_db)
                jobs_db = jobs.connect(jobs_path)
                result = tick(jobs_db, source_db, account, group, topic)
            except (sqlite3.Error, OSError) as exc:
                raise ValueError("SCHEDULER_DATABASE_ERROR") from exc
            finally:
                if jobs_db is not None:
                    jobs_db.close()
                if source_db is not None:
                    source_db.close()
            summary["ticks"] += 1
            if reporter is not None:
                reporter(result)
            if max_ticks is not None and summary["ticks"] >= max_ticks:
                break
            if stop_event is None:
                time.sleep(interval_seconds)
            elif stop_event.wait(interval_seconds):
                break
    except KeyboardInterrupt:
        summary["interrupted"] = True
    return summary
