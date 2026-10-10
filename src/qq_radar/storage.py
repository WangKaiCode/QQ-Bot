"""Versioned local SQLite storage and account-scoped source queries."""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE import_batches (
 id TEXT PRIMARY KEY, file_sha256 TEXT NOT NULL, source_version TEXT NOT NULL,
 status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
 committed_line INTEGER NOT NULL DEFAULT 0, failure_code TEXT);
CREATE TABLE messages (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, group_id TEXT NOT NULL,
 external_id TEXT NOT NULL, namespace TEXT NOT NULL DEFAULT 'synthetic.v1',
 sender_id TEXT NOT NULL, sender_name TEXT, occurred_at INTEGER NOT NULL,
 original_timestamp TEXT NOT NULL, first_received_at TEXT NOT NULL,
 expires_at INTEGER NOT NULL, text TEXT NOT NULL, raw_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL, content_status TEXT NOT NULL DEFAULT 'available',
 UNIQUE(account_id, group_id, namespace, external_id));
CREATE INDEX message_order ON messages(account_id, group_id, occurred_at, external_id);
CREATE TABLE message_segments (
 message_id TEXT NOT NULL REFERENCES messages(id), path TEXT NOT NULL,
 parent_path TEXT, kind TEXT NOT NULL, state TEXT NOT NULL, metadata TEXT NOT NULL,
 PRIMARY KEY(message_id, path));
CREATE TABLE observations (
 batch_id TEXT NOT NULL REFERENCES import_batches(id), line INTEGER NOT NULL,
 state TEXT NOT NULL, error_code TEXT, field TEXT,
 message_id TEXT REFERENCES messages(id), payload_hash TEXT, raw_json TEXT,
 PRIMARY KEY(batch_id, line));
PRAGMA user_version=1;
"""


def connect(path, readonly=False):
    path = Path(path).resolve()
    if readonly:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 0 and not readonly:
        # Do not claim or mutate an unrelated existing database.
        if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            db.close()
            raise ValueError("UNRECOGNIZED_DATABASE")
        db.executescript("BEGIN;" + SCHEMA + "COMMIT;")
    elif version != 1:
        db.close()
        raise ValueError("UNSUPPORTED_DATABASE_VERSION")
    return db


def report(db, batch_id):
    row = db.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
    if row is None:
        raise KeyError("BATCH_NOT_FOUND")
    result = dict(row)
    counts = dict.fromkeys(("inserted", "matched", "failed", "excluded"), 0)
    for state, count in db.execute("SELECT state, count(*) FROM observations WHERE batch_id=? GROUP BY state", (batch_id,)):
        counts[state] = count
    result["counts"] = {"seen": sum(counts.values()), **counts}
    result["errors"] = [dict(r) for r in db.execute(
        "SELECT line, error_code, field FROM observations WHERE batch_id=? AND state='failed' ORDER BY line", (batch_id,))]
    return result


def detail(db, message_id):
    row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if row is None:
        raise KeyError("MESSAGE_NOT_FOUND")
    result = dict(row)
    result["source"] = json.loads(result.pop("raw_json"))
    result["segments"] = [dict(r) for r in db.execute(
        "SELECT path, parent_path, kind, state, metadata FROM message_segments WHERE message_id=? ORDER BY rowid", (message_id,))]
    for segment in result["segments"]:
        segment["metadata"] = json.loads(segment["metadata"])
    return result


def search(db, account, group, keyword="", since=None, until=None, limit=50, offset=0):
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError("INVALID_PAGINATION")
    conditions = ["account_id=?", "group_id=?", "instr(text, ?) > 0"]
    args = [account, group, keyword]
    for operator, value in ((">=", since), ("<", until)):
        if value is not None:
            conditions.append(f"occurred_at {operator} ?")
            args.append(value)
    return [dict(r) for r in db.execute(
        "SELECT id, account_id, group_id, external_id, sender_id, sender_name, original_timestamp, text, content_status "
        "FROM messages WHERE " + " AND ".join(conditions) +
        " ORDER BY occurred_at, external_id LIMIT ? OFFSET ?", (*args, limit, offset))]


def context(db, message_id, radius=10):
    if not 0 <= radius <= 50:
        raise ValueError("INVALID_RADIUS")
    current = detail(db, message_id)
    scope = (current["account_id"], current["group_id"], current["occurred_at"], current["external_id"], radius)
    def neighbors(operator, direction):
        return [r[0] for r in db.execute(
            f"SELECT id FROM messages WHERE account_id=? AND group_id=? AND (occurred_at, external_id) {operator} (?, ?) "
            f"ORDER BY occurred_at {direction}, external_id {direction} LIMIT ?", scope)]
    return {"before": [detail(db, mid) for mid in reversed(neighbors("<", "DESC"))],
            "message": current, "after": [detail(db, mid) for mid in neighbors(">", "ASC")]}
