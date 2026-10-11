"""Read-only, deterministic rule filtering and extractive mock digest preview."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .domain import encode

SHANGHAI = timezone(timedelta(hours=8))
DEFAULT_RULES = Path(__file__).with_name("topics.json")


def load_rules(path=DEFAULT_RULES):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != "rules.v1":
        raise ValueError("INVALID_RULES")
    topics = config.get("topics")
    if not isinstance(topics, list) or not 1 <= len(topics) <= 20:
        raise ValueError("INVALID_RULES")
    seen = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise ValueError("INVALID_TOPIC")
        for key in ("id", "name"):
            if not isinstance(topic.get(key), str) or not 1 <= len(topic[key].strip()) <= 80:
                raise ValueError("INVALID_TOPIC")
        if topic["id"] in seen:
            raise ValueError("DUPLICATE_TOPIC")
        seen.add(topic["id"])
        topic["keywords"] = validate_keywords(topic.get("keywords"))
    return config


def validate_keywords(words):
    if not isinstance(words, list) or not 1 <= len(words) <= 20:
        raise ValueError("INVALID_KEYWORDS")
    result = []
    for word in words:
        if not isinstance(word, str) or not 1 <= len(word.strip()) <= 40:
            raise ValueError("INVALID_KEYWORDS")
        if word.strip().casefold() not in [item.casefold() for item in result]:
            result.append(word.strip())
    return result


def matched_terms(text, words):
    result = []
    for word in words:
        if re.fullmatch(r"[a-zA-Z0-9_]+", word):
            matched = re.search(r"(?<![a-zA-Z0-9_])" + re.escape(word) + r"(?![a-zA-Z0-9_])", text, re.IGNORECASE)
        else:
            matched = word.casefold() in text.casefold()
        if matched:
            result.append(word)
    return result


def window_start(occurred, kind):
    duration = 3600000 if kind == "hourly" else 86400000
    offset = 8 * 3600000
    return (occurred + offset) // duration * duration - offset


def iso(value):
    try:
        return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)).astimezone(SHANGHAI).isoformat()
    except (OverflowError, ValueError) as exc:
        raise ValueError("INVALID_WINDOW") from exc


def mock_provider(evidence):
    # Provider input contains anonymous references and matched text only.
    # This is an extractive test provider, not a model or an outbound payload.
    return [{"evidence_id": item["evidence_id"], "excerpt": item["text"][:160] + ("…" if len(item["text"]) > 160 else "")}
            for item in evidence[:3]]


def validate_output(output, evidence):
    available = {item["evidence_id"]: item["text"] for item in evidence}
    if not isinstance(output, list) or not output:
        raise ValueError("INVALID_PROVIDER_OUTPUT")
    seen = set()
    for item in output:
        if not isinstance(item, dict):
            raise ValueError("INVALID_PROVIDER_OUTPUT")
        key, excerpt = item.get("evidence_id"), item.get("excerpt")
        if not isinstance(key, str) or key not in available or key in seen or not isinstance(excerpt, str) or not excerpt:
            raise ValueError("INVALID_EVIDENCE")
        truncated = available[key][:160] + "…" if len(available[key]) > 160 else available[key]
        if excerpt != available[key] and excerpt != truncated:
            raise ValueError("UNSUPPORTED_EXCERPT")
        seen.add(key)


def preview(db, account, group, topic, kind="hourly", since=None, until=None, provider=mock_provider):
    if not account or not group or kind not in ("hourly", "daily"):
        raise ValueError("INVALID_ANALYSIS_SCOPE")
    if since is not None and until is not None and since >= until:
        raise ValueError("INVALID_WINDOW")
    for boundary in (since, until):
        if boundary is not None:
            iso(boundary)
    words = validate_keywords(topic.get("keywords"))
    if not isinstance(topic.get("name"), str) or not topic["name"].strip():
        raise ValueError("INVALID_TOPIC")
    topic = {"id": topic.get("id", "custom"), "name": topic["name"], "keywords": words}
    conditions, args = ["account_id=?", "group_id=?"], [account, group]
    for operator, value in ((">=", since), ("<", until)):
        if value is not None:
            conditions.append(f"occurred_at {operator} ?")
            args.append(value)
    if db.in_transaction:
        raise ValueError("ACTIVE_TRANSACTION")
    db.execute("BEGIN")
    try:
        rows = db.execute("SELECT id, namespace, occurred_at, payload_hash, content_status FROM messages WHERE " +
                          " AND ".join(conditions) + " ORDER BY occurred_at,external_id LIMIT 30001", args).fetchall()
        if len(rows) > 30000:
            raise ValueError("PREVIEW_LIMIT_EXCEEDED")
        coverage = {"messages": len(rows), "matched_messages": 0, "image_segments": 0,
                    "unsupported_segments": 0, "empty_text_messages": 0}
        windows = {}
        for row in rows:
            if row["namespace"] != "synthetic.v1" or row["content_status"] != "available":
                raise ValueError("SYNTHETIC_AVAILABLE_ONLY")
            start = window_start(row["occurred_at"], kind)
            bucket = windows.setdefault(start, {"revision": [], "evidence": []})
            bucket["revision"].append((row["id"], row["payload_hash"]))
            message_matched, has_text = False, False
            for segment in db.execute("SELECT path,kind,state,metadata FROM message_segments WHERE message_id=? ORDER BY rowid", (row["id"],)):
                coverage["image_segments"] += segment["kind"] == "image"
                coverage["unsupported_segments"] += segment["state"] == "unsupported"
                if segment["kind"] != "text":
                    continue
                text = json.loads(segment["metadata"])["text"]
                has_text = has_text or bool(text.strip())
                terms = matched_terms(text, words)
                if terms:
                    message_matched = True
                    bucket["evidence"].append({"message_id": row["id"], "path": segment["path"], "terms": terms, "text": text})
            coverage["matched_messages"] += message_matched
            coverage["empty_text_messages"] += not has_text
        digests = []
        for start, bucket in sorted(windows.items(), reverse=True):
            evidence = bucket["evidence"]
            if not evidence:
                continue
            for item in evidence:
                item["evidence_id"] = hashlib.sha256(encode([kind, start, item["message_id"], item["path"]]).encode()).hexdigest()
            output = provider([{"evidence_id": item["evidence_id"], "text": item["text"]} for item in evidence])
            validate_output(output, evidence)
            revision = hashlib.sha256(encode(bucket["revision"]).encode()).hexdigest()
            identity = encode([account, group, kind, start, since, until, topic, revision, "mock.extractive.v1"])
            digests.append({"id": str(uuid5(NAMESPACE_URL, identity)), "window_start": iso(start),
                            "window_end": iso(start + (3600000 if kind == "hourly" else 86400000)),
                            "input_revision": revision, "provider": "mock.extractive.v1", "topic": topic,
                            "points": output, "evidence": [{k: v for k, v in item.items() if k != "text"} for item in evidence]})
        return {"mode": "synthetic", "persisted": False, "scheduled": False, "kind": kind,
                "requested_range": {"since": iso(since) if since is not None else None, "until": iso(until) if until is not None else None},
                "account_id": account, "group_id": group, "coverage": coverage, "digests": digests}
    finally:
        db.rollback()
