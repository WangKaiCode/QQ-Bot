"""Synthetic retention impact preview; never execute deletion or hide sources."""
from datetime import datetime, timezone

from .analysis import iso


def preview(db, account, group, as_of=None, limit=20, offset=0):
    """Count due data in one snapshot and return metadata-only candidate pages."""
    if (not isinstance(account, str) or not account.strip() or
            not isinstance(group, str) or not group.strip()):
        raise ValueError("INVALID_RETENTION_SCOPE")
    if (type(limit) is not int or not 1 <= limit <= 100 or
            type(offset) is not int or offset < 0 or offset > 2 ** 63 - 1):
        raise ValueError("INVALID_PAGINATION")
    if as_of is None:
        as_of = int(datetime.now(timezone.utc).timestamp() * 1000)
    if type(as_of) is not int:
        raise ValueError("INVALID_AS_OF")
    try:
        displayed_time = iso(as_of)
    except ValueError as exc:
        raise ValueError("INVALID_AS_OF") from exc
    if db.in_transaction:
        raise ValueError("ACTIVE_TRANSACTION")
    db.execute("BEGIN")
    try:
        scope = (account, group)
        if db.execute("SELECT 1 FROM messages WHERE account_id=? AND group_id=? "
                      "AND namespace!='synthetic.v1' LIMIT 1", scope).fetchone():
            raise ValueError("SYNTHETIC_ONLY")
        statuses = dict(db.execute("SELECT content_status,count(*) FROM messages "
                                   "WHERE account_id=? AND group_id=? GROUP BY content_status", scope))
        due = "account_id=? AND group_id=? AND expires_at<=? AND content_status='available'"
        args = (*scope, as_of)
        due_messages = db.execute("SELECT count(*) FROM messages WHERE " + due, args).fetchone()[0]
        due_ids = "SELECT id FROM messages WHERE " + due
        due_segments = db.execute("SELECT count(*) FROM message_segments WHERE message_id IN (" +
                                  due_ids + ")", args).fetchone()[0]
        observations = db.execute("SELECT count(*),count(raw_json) FROM observations WHERE message_id IN (" +
                                   due_ids + ")", args).fetchone()
        items = []
        for row in db.execute("SELECT id,external_id,expires_at,content_status,"
                              "(SELECT count(*) FROM message_segments WHERE message_id=messages.id) AS segment_count,"
                              "(SELECT count(*) FROM observations WHERE message_id=messages.id) AS observation_count "
                              "FROM messages WHERE " + due +
                              " ORDER BY expires_at,external_id,id LIMIT ? OFFSET ?", (*args, limit, offset)):
            item = dict(row)
            item["expires_at"] = iso(item["expires_at"])
            items.append(item)
        return {"mode": "synthetic", "readonly": True, "executed": False,
                "as_of": displayed_time,
                "policy": {"raw_days": 3, "digest_days": 10, "digest_storage_implemented": False,
                           "retention_active": False},
                "scope": {"account_id": account, "group_id": group},
                "counts": {"total_messages": sum(statuses.values()), "due_messages": due_messages,
                           "already_unavailable_messages": sum(value for key, value in statuses.items() if key != "available"),
                           "status_counts": statuses, "due_segments": due_segments,
                           "due_observations": observations[0], "due_raw_observations": observations[1],
                           "managed_media_files": 0},
                "items": items, "next_offset": offset + len(items) if offset + len(items) < due_messages else None}
    finally:
        db.rollback()
