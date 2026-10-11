"""Local-only, conservative candidate payload inspection; never sends data."""
import json
import re

from .analysis import mock_provider, preview

MAX_EVIDENCE = 1000
MAX_TEXT_CHARS = 10000
MAX_TOTAL_CHARS = 200000
MASK = "[已屏蔽]"
IDENTITY_FIELDS = ("account_id", "group_id", "sender_id", "sender_name")
PATTERNS = (
    ("url", re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"']+", re.I)),
    ("email", re.compile(r"[\w.+-]+@[\w.-]+\.[\w-]+", re.UNICODE)),
    ("qq_context", re.compile(r"(?:QQ(?:号|号码)?|企鹅号|群号)\s*[:：=]?\s*\d(?:[\d -]{1,30}\d)?", re.I)),
    ("phone", re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)")),
    ("number", re.compile(r"\d{5,}")),
)


def _known_identities(db, account, group, since, until):
    conditions, args = ["account_id=?", "group_id=?"], [account, group]
    for operator, value in ((">=", since), ("<", until)):
        if value is not None:
            conditions.append(f"occurred_at {operator} ?")
            args.append(value)
    rows = db.execute("SELECT id,account_id,group_id,sender_id,sender_name FROM messages WHERE " +
                      " AND ".join(conditions), args)
    values = set()
    for row in rows:
        values.update(row[key] for key in IDENTITY_FIELDS if row[key])
        for segment in db.execute("SELECT metadata FROM message_segments WHERE message_id=? AND kind='forward_node'",
                                  (row["id"],)):
            node = json.loads(segment["metadata"])
            values.update(node[key] for key in IDENTITY_FIELDS if isinstance(node.get(key), str) and node[key])
    return sorted(values, key=lambda value: (-len(value), value))


def _sanitize(text, identities, counts):
    # Short identities cannot be distinguished reliably from ordinary words.
    if any(len(value) <= 2 and value.casefold() in text.casefold() for value in identities):
        raise ValueError("AMBIGUOUS_SHORT_IDENTITY")
    for value in identities:
        if len(value) <= 2:
            continue
        expression = re.escape(value)
        if re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            expression = r"(?<![a-zA-Z0-9_])" + expression + r"(?![a-zA-Z0-9_])"
        text, count = re.subn(expression, MASK, text, flags=re.I)
        counts["known_identity"] += count
    # Embedded identity strings are blocked rather than silently misclassified.
    if any(value.casefold() in text.casefold() for value in identities):
        raise ValueError("RESIDUAL_KNOWN_IDENTITY")
    for category, pattern in PATTERNS:
        text, count = pattern.subn(MASK, text)
        counts[category] += count
    if any(value.casefold() in text.casefold() for value in identities):
        raise ValueError("RESIDUAL_KNOWN_IDENTITY")
    return text


def prepare(db, account, group, topic, since=None, until=None):
    """Return a local candidate and count-only report, or an atomic blocked result.

    Uses analysis.preview's read transaction, reading identities and evidence in
    its provider callback before rollback. Never commits, truncates, or sends.
    Invalid scope/rules/database inputs raise the existing preview ValueErrors.
    Candidate inspection failures return payload=None with a static reason.
    """
    counts = {key: 0 for key in ("known_identity", "url", "email", "qq_context", "phone", "number")}
    report = {"blocked": False, "blocked_reason": None, "selected_evidence": 0,
              "candidate_evidence": 0, "empty_after_redaction": 0, "redactions": counts}
    candidate = {"schema_version": "outbound.preview.v1", "keywords": [], "evidence": []}
    identities = None
    total_chars = 0

    def inspect(items):
        nonlocal identities, total_chars
        if identities is None:
            identities = _known_identities(db, account, group, since, until)
            candidate["keywords"] = [_sanitize(word, identities, counts) for word in topic["keywords"]]
            if any(MASK in word for word in candidate["keywords"]):
                raise ValueError("SENSITIVE_KEYWORD")
        report["selected_evidence"] += len(items)
        if report["selected_evidence"] > MAX_EVIDENCE:
            raise ValueError("OUTBOUND_EVIDENCE_LIMIT")
        for item in items:
            text = item["text"]
            total_chars += len(text)
            if len(text) > MAX_TEXT_CHARS or total_chars > MAX_TOTAL_CHARS:
                raise ValueError("OUTBOUND_TEXT_LIMIT")
            sanitized = _sanitize(text, identities, counts)
            if not sanitized.replace(MASK, "").strip(" \t\r\n,，。:：;；.!！?？-_"):
                report["empty_after_redaction"] += 1
                continue
            candidate["evidence"].append({"evidence_id": "e" + str(len(candidate["evidence"]) + 1),
                                          "sanitized_text": sanitized})
        return mock_provider(items)

    inspection_errors = {"AMBIGUOUS_SHORT_IDENTITY", "RESIDUAL_KNOWN_IDENTITY", "SENSITIVE_KEYWORD",
                         "OUTBOUND_EVIDENCE_LIMIT", "OUTBOUND_TEXT_LIMIT"}
    try:
        preview(db, account, group, topic, since=since, until=until, provider=inspect)
        if not candidate["evidence"]:
            report.update(blocked=True, blocked_reason="NO_REVIEWABLE_EVIDENCE")
    except ValueError as exc:
        if str(exc) not in inspection_errors:
            raise
        report.update(blocked=True, blocked_reason=str(exc))
    report["candidate_evidence"] = 0 if report["blocked"] else len(candidate["evidence"])
    return {"mode": "synthetic", "persisted": False, "allowed_to_send": False,
            "requires_human_review": True, "payload": None if report["blocked"] else candidate,
            "report": report,
            "limitations": ["Unknown names and indirect identifying context require human review.",
                            "This local preview is not proof of anonymization and never authorizes sending."]}
