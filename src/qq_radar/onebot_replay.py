"""Explicitly synthetic, bounded offline replay; no source database or listener."""
import json
from pathlib import Path
import secrets

from .onebot import Probe


def replay(path, account, group):
    with Path(path).open("rb") as stream:
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("REPLAY_FILE_LIMIT")
    lines = raw.splitlines()
    if not lines or len(lines) > 1000:
        raise ValueError("REPLAY_LINE_LIMIT")
    token = secrets.token_urlsafe(32)
    probe = Probe({"account": account, "allowed_groups": [group], "token": token})
    errors = []
    try:
        for number, line in enumerate(lines, 1):
            try:
                frame = json.loads(line)
                if not isinstance(frame, dict) or frame.get("schema_version") != "onebot.replay.v1" or frame.get("synthetic") is not True:
                    raise ValueError("INVALID_SYNTHETIC_FRAME")
                body = json.dumps(frame["event"], ensure_ascii=False, allow_nan=False).encode("utf-8")
                result = probe.receive(body, token)
                if result["status"] in ("rejected", "stopped"):
                    errors.append({"line": number, "code": result["reason"]})
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                errors.append({"line": number, "code": "INVALID_SYNTHETIC_FRAME"})
        summary = probe.snapshot()
        probe.close()
        summary.update(synthetic=True, lines=len(lines), errors=errors,
                       snapshot_phase="before_purge", purged=True)
        return summary
    finally:
        probe.close()
