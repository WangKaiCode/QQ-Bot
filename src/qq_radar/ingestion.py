"""Stream JSONL with atomic chunk checkpoints; safe replay after interruption."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .domain import InvalidRecord, normalize
from .storage import report


def now():
    return datetime.now(timezone.utc).isoformat()


def reject_constant(value):
    raise ValueError("NON_JSON_CONSTANT")


def source_lines(stream, digest):
    """Bound memory even when a bad source has a giant physical line."""
    limit = 1024 * 1024
    while raw := stream.readline(limit + 1):
        digest.update(raw)
        if len(raw) > limit and not raw.endswith(b"\n"):
            while tail := stream.readline(limit + 1):
                digest.update(tail)
                if tail.endswith(b"\n"):
                    break
        yield raw


def process_line(db, batch_id, line_no, raw, allowed):
    state, code, field, mid, digest, stored = "failed", None, None, None, None, None
    try:
        if len(raw) > 1024 * 1024:
            raise InvalidRecord("LINE_LIMIT", "root")
        try:
            record = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise InvalidRecord("INVALID_JSON", "root") from None
        if not isinstance(record, dict):
            raise InvalidRecord("INVALID_RECORD", "root")
        # Exclude before validation; never persist unapproved group bodies.
        pair = (record.get("account_id"), record.get("group_id"))
        if not all(isinstance(v, str) and v.strip() for v in pair):
            raise InvalidRecord("INVALID_FIELD", "account_id/group_id")
        if pair not in allowed:
            state = "excluded"
        else:
            occurred, text, segments, digest = normalize(record)
            stored = raw.decode("utf-8").rstrip("\r\n")
            existing = db.execute(
                "SELECT id, payload_hash FROM messages WHERE account_id=? AND group_id=? AND namespace='synthetic.v1' AND external_id=?",
                (*pair, record["message_id"])).fetchone()
            if existing:
                mid = existing["id"]
                if existing["payload_hash"] != digest:
                    raise InvalidRecord("IDENTITY_CONFLICT", "message_id")
                state = "matched"
            else:
                mid = str(uuid4())
                db.execute(
                    "INSERT INTO messages(id, account_id, group_id, external_id, sender_id, sender_name, occurred_at, original_timestamp, "
                    "first_received_at, expires_at, text, raw_json, payload_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mid, *pair, record["message_id"], record["sender_id"], record.get("sender_name"), occurred,
                     record["timestamp"], now(), occurred + 3 * 86400000, text, stored, digest))
                db.executemany("INSERT INTO message_segments VALUES (?,?,?,?,?,?)", [(mid, *s) for s in segments])
                state = "inserted"
    except InvalidRecord as exc:
        code, field = exc.code, exc.field
    except (RecursionError, ValueError):
        code, field = "INVALID_RECORD", "root"
    db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
               (batch_id, line_no, state, code, field, mid, digest, stored))


def import_file(db, path, allowed, chunk_size=200):
    if not allowed or chunk_size < 1:
        raise ValueError("EMPTY_ALLOWLIST_OR_INVALID_CHUNK")
    # Hash and import the same open file, then detect changes before final commit.
    with open(path, "rb") as stream:
        file_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        batch_id = str(uuid4())
        with db:
            db.execute("INSERT INTO import_batches(id,file_sha256,source_version,status,started_at) VALUES (?,?,?,'running',?)",
                       (batch_id, file_hash, "synthetic.v1", now()))
        try:
            line_no, observed_hash = 0, hashlib.sha256()
            for line_no, raw in enumerate(source_lines(stream, observed_hash), 1):
                process_line(db, batch_id, line_no, raw, allowed)
                db.execute("UPDATE import_batches SET committed_line=? WHERE id=?", (line_no, batch_id))
                if line_no % chunk_size == 0:
                    db.commit()
            if observed_hash.hexdigest() != file_hash:
                raise ValueError("INPUT_CHANGED")
            failed = db.execute("SELECT count(*) FROM observations WHERE batch_id=? AND state='failed'", (batch_id,)).fetchone()[0]
            db.execute("UPDATE import_batches SET status=?,finished_at=? WHERE id=?",
                       ("completed_with_errors" if failed else "completed", now(), batch_id))
            db.commit()
        except (OSError, sqlite3.Error, ValueError):
            db.rollback()
            # A hard crash leaves 'running' with only committed progress.
            # On a storage failure even this status update may fail; CLI still
            # exposes batch_id so the last committed report can be inspected.
            try:
                with db:
                    db.execute("UPDATE import_batches SET status='interrupted',failure_code='IMPORT_ABORTED',finished_at=? WHERE id=?", (now(), batch_id))
            except sqlite3.Error:
                pass
            raise ImportAborted(batch_id) from None
        return report(db, batch_id)


class ImportAborted(RuntimeError):
    def __init__(self, batch_id):
        self.batch_id = batch_id
        super().__init__("IMPORT_ABORTED")
