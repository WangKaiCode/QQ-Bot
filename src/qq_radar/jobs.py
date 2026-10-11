"""Recoverable local Mock jobs; persisted results contain references, never excerpts."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from .analysis import iso, preview, window_start
from .domain import encode

MAGIC = "qq-radar.mock-jobs.v1"
SCHEMA = """
CREATE TABLE jobs_metadata (magic TEXT PRIMARY KEY);
CREATE TABLE analysis_jobs (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, group_id TEXT NOT NULL,
 kind TEXT NOT NULL, window_start INTEGER NOT NULL, window_end INTEGER NOT NULL,
 topic_json TEXT NOT NULL, input_revision TEXT NOT NULL,
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 claim_token TEXT, lease_until INTEGER, error_code TEXT,
 created_at INTEGER NOT NULL, completed_at INTEGER, result_json TEXT);
CREATE INDEX jobs_scope ON analysis_jobs(account_id,group_id,window_start);
PRAGMA user_version=1;
"""


def connect(path, readonly=False):
    path = Path(path).resolve()
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) if readonly else sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if not tables and version == 0 and not readonly:
            db.executescript("BEGIN;" + SCHEMA)
            db.execute("INSERT INTO jobs_metadata VALUES (?)", (MAGIC,))
            db.commit()
        elif version != 1 or tables != {"jobs_metadata", "analysis_jobs"}:
            raise ValueError("UNRECOGNIZED_JOBS_DATABASE")
        if [row[0] for row in db.execute("SELECT magic FROM jobs_metadata")] != [MAGIC]:
            raise ValueError("UNRECOGNIZED_JOBS_DATABASE")
        db.execute("SELECT id,claim_token,result_json FROM analysis_jobs LIMIT 0")
        return db
    except Exception:
        db.close()
        raise


def _now(value):
    value = int(time.time() * 1000) if value is None else value
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("INVALID_AS_OF")
    iso(value)
    return value


def _separate(jobs, source):
    paths = []
    for db in (jobs, source):
        path = db.execute("PRAGMA database_list").fetchone()[2]
        if not path:
            raise ValueError("FILE_DATABASE_REQUIRED")
        paths.append(Path(path).resolve())
    if paths[0] == paths[1]:
        raise ValueError("SOURCE_JOBS_PATH_COLLISION")
    # Also catch hard links, where supported.
    if paths[0].samefile(paths[1]):
        raise ValueError("SOURCE_JOBS_PATH_COLLISION")
    if jobs.in_transaction or source.in_transaction:
        raise ValueError("ACTIVE_TRANSACTION")


def _window(source, account, group, topic, kind, start, end, clock):
    result = preview(source, account, group, topic, kind, start, end, expires_after=clock)
    if not result["digests"]:
        return None
    digest = result["digests"][0]
    # Verify the separate metadata read describes the same preview snapshot.
    rows = source.execute("SELECT id,payload_hash FROM messages WHERE account_id=? AND group_id=? "
                          "AND occurred_at>=? AND occurred_at<? AND expires_at>? ORDER BY occurred_at,external_id",
                          (account, group, start, end, clock)).fetchall()
    revision = hashlib.sha256(encode([(row["id"], row["payload_hash"]) for row in rows]).encode()).hexdigest()
    if revision != digest["input_revision"]:
        raise ValueError("INPUT_CHANGED")
    hashes = {row["id"]: row["payload_hash"] for row in rows}
    for evidence in digest["evidence"]:
        evidence["payload_hash"] = hashes[evidence["message_id"]]
    digest["points"] = [{"evidence_id": item["evidence_id"]} for item in digest["points"]]
    return digest


def enqueue(jobs, source, account, group, topic, kind, since, until, as_of=None):
    _separate(jobs, source)
    clock = _now(as_of)
    duration = 3600000 if kind == "hourly" else 86400000
    maximum = 72 if kind == "hourly" else 3
    if kind not in ("hourly", "daily") or not account or not group:
        raise ValueError("INVALID_JOB_SCOPE")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (since, until)):
        raise ValueError("INVALID_JOB_WINDOW")
    if since >= until or until > clock or window_start(since, kind) != since or window_start(until, kind) != until or (until - since) // duration > maximum:
        raise ValueError("INVALID_JOB_WINDOW")
    iso(since)
    iso(until)
    inserted = matched = empty = 0
    ids = []
    for start in range(since, until, duration):
        digest = _window(source, account, group, topic, kind, start, start + duration, clock)
        if digest is None:
            empty += 1
            continue
        with jobs:
            cursor = jobs.execute("INSERT OR IGNORE INTO analysis_jobs "
                                  "(id,account_id,group_id,kind,window_start,window_end,topic_json,input_revision,status,created_at) "
                                  "VALUES (?,?,?,?,?,?,?,?,'pending',?)",
                                  (digest["id"], account, group, kind, start, start + duration,
                                   encode(digest["topic"]), digest["input_revision"], clock))
        inserted += cursor.rowcount
        matched += not cursor.rowcount
        ids.append(digest["id"])
    return {"mode": "synthetic", "scheduled": False, "inserted": inserted, "matched": matched, "empty_windows": empty, "job_ids": ids}


def run(jobs, source, as_of=None):
    _separate(jobs, source)
    clock = _now(as_of)
    counts = {"succeeded": 0, "failed": 0, "superseded": 0, "expired": 0}
    # Bound one invocation; concurrently enqueued work is handled next time.
    candidates = jobs.execute("SELECT id FROM analysis_jobs WHERE status IN ('pending','failed') "
                              "OR (status='running' AND lease_until<=?) ORDER BY created_at,id LIMIT 200", (clock,)).fetchall()
    for candidate in candidates:
        token = str(uuid4())
        with jobs:
            claimed = jobs.execute("UPDATE analysis_jobs SET status='running',attempts=attempts+1,claim_token=?,lease_until=?,error_code=NULL "
                                   "WHERE id=? AND attempts<3 AND (status IN ('pending','failed') OR (status='running' AND lease_until<=?))",
                                   (token, clock + 300000, candidate["id"], clock)).rowcount
            if not claimed:
                jobs.execute("UPDATE analysis_jobs SET status='failed_terminal',error_code='ATTEMPT_LIMIT' WHERE id=? "
                             "AND attempts>=3 AND (status='failed' OR (status='running' AND lease_until<=?))", (candidate["id"], clock))
                continue
        row = jobs.execute("SELECT * FROM analysis_jobs WHERE id=?", (candidate["id"],)).fetchone()
        result, error = None, None
        try:
            if row["window_end"] + 10 * 86400000 <= clock:
                status = "expired"
            else:
                result = _window(source, row["account_id"], row["group_id"], json.loads(row["topic_json"]), row["kind"],
                                 row["window_start"], row["window_end"], clock)
                if result is None:
                    status = "expired"
                elif result["input_revision"] != row["input_revision"]:
                    status = "superseded"
                    enqueue(jobs, source, row["account_id"], row["group_id"], json.loads(row["topic_json"]), row["kind"],
                            row["window_start"], row["window_end"], clock)
                    result = None
                else:
                    status = "succeeded"
        except (ValueError, sqlite3.Error, OSError):
            status = "failed_terminal" if row["attempts"] >= 3 else "failed"
            error = "JOB_PROCESSING_FAILED"
            result = None
        with jobs:
            updated = jobs.execute("UPDATE analysis_jobs SET status=?,completed_at=?,result_json=?,error_code=?,lease_until=NULL "
                                   "WHERE id=? AND status='running' AND claim_token=?",
                                   (status, clock, encode(result) if result is not None else None, error, row["id"], token)).rowcount
        if updated:
            counts["failed" if status.startswith("failed") else status] += 1
    return {"mode": "synthetic", "scheduled": False, **counts}


def list_jobs(jobs, account, group, limit=50):
    if not account or not group or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ValueError("INVALID_JOB_SCOPE")
    return [dict(row) for row in jobs.execute("SELECT id,kind,window_start,window_end,input_revision,status,attempts,error_code,created_at,completed_at "
                                            "FROM analysis_jobs WHERE account_id=? AND group_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?",
                                            (account, group, limit))]


def feed(jobs, source, account, group, as_of=None, limit=20, offset=0):
    _separate(jobs, source)
    source.execute("BEGIN")
    try:
        jobs.execute("BEGIN")
        try:
            return _feed(jobs, source, account, group, as_of, limit, offset)
        finally:
            jobs.rollback()
    finally:
        source.rollback()


def _feed(jobs, source, account, group, as_of, limit, offset):
    clock = _now(as_of)
    if (not account or not group or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100
            or not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 9223372036854775807):
        raise ValueError("INVALID_FEED_SCOPE")
    # Latest successful revision for each rule/window family, without duplicate cards.
    selected = jobs.execute("WITH revisions AS (SELECT *,rowid AS ordinal,ROW_NUMBER() OVER "
                            "(PARTITION BY kind,window_start,topic_json ORDER BY rowid DESC) AS revision_rank "
                            "FROM analysis_jobs WHERE account_id=? AND group_id=? AND status='succeeded') "
                            "SELECT * FROM revisions WHERE revision_rank=1 ORDER BY window_start DESC,ordinal DESC LIMIT ? OFFSET ?",
                            (account, group, limit + 1, offset)).fetchall()
    items = []
    for row in selected[:limit]:
        digest = json.loads(row["result_json"])
        expired = row["window_end"] + 10 * 86400000 <= clock
        digest["state"] = "expired" if expired else "available"
        digest["expires_at"] = iso(row["window_end"] + 10 * 86400000)
        revision_rows = source.execute("SELECT id,payload_hash FROM messages WHERE account_id=? AND group_id=? "
                                       "AND occurred_at>=? AND occurred_at<? AND expires_at>? ORDER BY occurred_at,external_id LIMIT 30001",
                                       (account, group, row["window_start"], row["window_end"], clock)).fetchall()
        current_revision = hashlib.sha256(encode([(item["id"], item["payload_hash"]) for item in revision_rows]).encode()).hexdigest()
        digest["input_changed"] = current_revision != row["input_revision"]
        digest["update_pending"] = bool(jobs.execute("SELECT 1 FROM analysis_jobs WHERE account_id=? AND group_id=? AND kind=? "
                                                    "AND window_start=? AND topic_json=? AND rowid>? AND status IN ('pending','running','failed','failed_terminal') LIMIT 1",
                                                    (account, group, row["kind"], row["window_start"], row["topic_json"], row["ordinal"])).fetchone())
        evidence_map = {}
        for evidence in digest["evidence"]:
            message = source.execute("SELECT account_id,group_id,expires_at,content_status,payload_hash,namespace FROM messages WHERE id=?",
                                     (evidence["message_id"],)).fetchone()
            state = "missing"
            if expired or (message is not None and message["expires_at"] <= clock):
                state = "expired"
            elif message is not None and message["account_id"] == account and message["group_id"] == group:
                state = "available" if message["content_status"] == "available" and message["namespace"] == "synthetic.v1" and message["payload_hash"] == evidence["payload_hash"] else "changed"
            evidence["source_state"] = state
            evidence_map[evidence["evidence_id"]] = evidence
        for point in digest["points"]:
            evidence = evidence_map[point["evidence_id"]]
            point["source_state"] = evidence["source_state"]
            if point["source_state"] == "available":
                segment = source.execute("SELECT kind,metadata FROM message_segments WHERE message_id=? AND path=?",
                                         (evidence["message_id"], evidence["path"])).fetchone()
                if segment is None or segment["kind"] != "text":
                    point["source_state"] = evidence["source_state"] = "missing"
                else:
                    text = json.loads(segment["metadata"])["text"]
                    point["excerpt"] = text[:160] + ("…" if len(text) > 160 else "")
        items.append(digest)
    return {"mode": "synthetic", "persisted": True, "scheduled": False, "items": items,
            "next_offset": offset + limit if len(selected) > limit else None}
