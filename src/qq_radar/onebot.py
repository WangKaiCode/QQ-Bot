"""Bounded, memory-only OneBot 11 inspection; no network or QQ actions."""
import copy
import hashlib
import hmac
import json
import re
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

from .domain import encode


def _id(value, signed=False):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("INVALID_ID")
    if isinstance(value, str) and not re.fullmatch(r"-?[0-9]{1,19}" if signed else r"[0-9]{1,19}", value):
        raise ValueError("INVALID_ID")
    number = int(value)
    if not (-(2 ** 63) <= number < 2 ** 63) or (not signed and number <= 0):
        raise ValueError("INVALID_ID")
    return str(number)


def _reference(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return _id(value, signed=True)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value):
        raise ValueError("INVALID_REFERENCE")
    return value


def normalize_event(event, account, allowed_groups, epoch):
    account = _id(account)
    groups = {_id(value) for value in allowed_groups}
    if not groups or not isinstance(epoch, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", epoch):
        raise ValueError("INVALID_SCOPE")
    if not isinstance(event, dict):
        raise ValueError("INVALID_EVENT")
    if _id(event.get("self_id")) != account:
        return {"excluded": True, "reason": "ACCOUNT_OUTSIDE_SCOPE"}
    if event.get("post_type") != "message" or event.get("message_type") != "group":
        return {"excluded": True, "reason": "NOT_GROUP_MESSAGE"}
    group = _id(event.get("group_id"))
    if group not in groups:
        return {"excluded": True, "reason": "GROUP_OUTSIDE_SCOPE"}
    message_id = _id(event.get("message_id"), signed=True)
    seconds = event.get("time")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 253402300799:
        raise ValueError("INVALID_TIME")
    try:
        timestamp = datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        raise ValueError("INVALID_TIME") from None
    sender = {"sender_id": _id(event.get("user_id"))}
    metadata = event.get("sender", {})
    if not isinstance(metadata, dict):
        raise ValueError("INVALID_SENDER")
    for key in ("nickname", "card"):
        if key in metadata:
            if not isinstance(metadata[key], str) or len(metadata[key]) > 256:
                raise ValueError("INVALID_SENDER")
            sender[key] = metadata[key]
    gaps = set()
    count = 0

    def segments(items, depth=0):
        nonlocal count
        if depth > 8:
            raise ValueError("DEPTH_LIMIT")
        if isinstance(items, str):
            if "[CQ:" in items:
                gaps.add("cq_string_unparsed")
                return [{"type": "cq_string", "state": "unsupported"}]
            items = [{"type": "text", "data": {"text": items}}]
        if not isinstance(items, list):
            raise ValueError("INVALID_SEGMENTS")
        result = []
        for segment in items:
            count += 1
            if count > 1000:
                raise ValueError("SEGMENT_LIMIT")
            if not isinstance(segment, dict) or not isinstance(segment.get("type"), str):
                raise ValueError("INVALID_SEGMENT")
            kind, data = segment["type"], segment.get("data", {})
            if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", kind) or not isinstance(data, dict):
                raise ValueError("INVALID_SEGMENT")
            item = {"type": kind, "state": "parsed"}
            if kind == "text":
                if not isinstance(data.get("text"), str):
                    raise ValueError("INVALID_TEXT")
                item["text"] = data["text"]
            elif kind in ("image", "record"):
                # Resource addresses and binary data are deliberately not retained.
                item["state"] = "not_fetched"
                gaps.add("media_not_fetched")
            elif kind == "at":
                item["target"] = "all" if data.get("qq") == "all" else _id(data.get("qq"))
            elif kind == "reply":
                item.update(reference=_id(data.get("id"), signed=True), state="reference_only")
                gaps.add("reply_unresolved")
            elif kind in ("forward", "node"):
                if "id" in data:
                    item["reference"] = _reference(data["id"])
                if "content" in data:
                    item["segments"] = segments(data["content"], depth + 1)
                    for key in ("user_id", "nickname"):
                        if key in data:
                            value = data[key]
                            if key == "user_id":
                                value = _id(value)
                            elif not isinstance(value, str) or len(value) > 256:
                                raise ValueError("INVALID_SENDER")
                            item[key] = value
                    gaps.add("inline_forward_extension_unverified")
                else:
                    item["state"] = "pending"
                    gaps.add("forward_unresolved")
            else:
                item["state"] = "unsupported"
                gaps.add("unsupported_segment")
            result.append(item)
        return result

    normalized = segments(event.get("message"))
    return {"schema_version": "onebot.probe.v1", "namespace": "onebot.v11",
            "identity": {"account": account, "group": group, "message_id": message_id, "epoch": epoch},
            "timestamp": timestamp, "sender": sender, "segments": normalized,
            "content_status": "pending" if "forward_unresolved" in gaps else "partial" if gaps else "available",
            "gaps": sorted(gaps)}


class Probe:
    """Local inspection session. Caller must enforce transport security separately."""
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("INVALID_CONFIG")
        self._account = _id(config.get("account"))
        allowed = config.get("allowed_groups")
        if not isinstance(allowed, list) or not 1 <= len(allowed) <= 20:
            raise ValueError("INVALID_SCOPE")
        self._groups = {_id(value) for value in allowed}
        token = config.get("token")
        if not isinstance(token, str) or not 32 <= len(token.encode("utf-8")) <= 256 or token.strip() != token:
            raise ValueError("INVALID_TOKEN")
        self._token = token.encode("utf-8")
        for key, default, maximum in (("max_messages", 100, 100), ("max_bytes", 1048576, 1048576),
                                      ("max_retained_bytes", 262144, 262144), ("duration_seconds", 3600, 3600)):
            value = config.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError("INVALID_LIMIT")
            setattr(self, "_" + key, value)
        self._epoch = str(uuid4())
        self._deadline = time.monotonic() + self._duration_seconds
        self._items, self._identities = {}, {}
        self._retained = 0
        self._observed_gaps = set()
        self._counts = dict.fromkeys(("accepted", "matched", "conflicts", "excluded", "invalid", "unauthorized", "limited"), 0)
        self._closed = False
        self._lock = threading.RLock()
        self._timer = threading.Timer(self._duration_seconds, self.close)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self):
        if time.monotonic() >= self._deadline:
            self.close()

    def close(self):
        with self._lock:
            self._closed = True
            self._items.clear()
            self._identities.clear()
            self._retained = 0
            self._timer.cancel()
            self._token = b""

    def receive(self, body, token):
        with self._lock:
            self._expire()
            if self._closed:
                return {"status": "stopped", "reason": "SESSION_CLOSED"}
            try:
                supplied = token.encode("utf-8") if isinstance(token, str) and len(token) <= 256 else b""
            except UnicodeError:
                supplied = b""
            if not hmac.compare_digest(supplied, self._token):
                self._counts["unauthorized"] += 1
                return {"status": "rejected", "reason": "UNAUTHORIZED"}
            if not isinstance(body, bytes) or len(body) > self._max_bytes:
                self._counts["limited"] += 1
                return {"status": "rejected", "reason": "REQUEST_LIMIT"}
            try:
                event = json.loads(body)
                result = normalize_event(event, self._account, self._groups, self._epoch)
            except (ValueError, TypeError, RecursionError):
                self._counts["invalid"] += 1
                return {"status": "rejected", "reason": "INVALID_EVENT"}
            if result.get("excluded"):
                self._counts["excluded"] += 1
                return {"status": "excluded", "reason": result["reason"]}
            identity = encode(result["identity"])
            # Hash full admitted event to detect changes even in unsupported data.
            try:
                digest = hashlib.sha256(encode(event).encode("utf-8")).hexdigest()
                retained = len(encode(result).encode("utf-8"))
            except (ValueError, UnicodeError):
                self._counts["invalid"] += 1
                return {"status": "rejected", "reason": "INVALID_EVENT"}
            # Parsing can outlive the admission deadline while holding the lock.
            # Recheck before reporting a match/conflict or retaining new content.
            self._expire()
            if self._closed:
                return {"status": "stopped", "reason": "SESSION_CLOSED"}
            if identity in self._identities:
                original_digest = self._identities[identity]
                category = "matched" if original_digest == digest else "conflicts"
                self._counts[category] += 1
                return {"status": category}
            if len(self._items) >= self._max_messages or self._retained + retained > self._max_retained_bytes:
                self._counts["limited"] += 1
                return {"status": "rejected", "reason": "SESSION_LIMIT"}
            local_id = str(uuid4())
            self._items[local_id] = result
            self._identities[identity] = digest
            self._retained += retained
            self._observed_gaps.update(result["gaps"])
            self._counts["accepted"] += 1
            return {"status": "accepted", "local_id": local_id}

    def snapshot(self):
        with self._lock:
            self._expire()
            return {"mode": "onebot_probe", "persisted": False, "closed": self._closed,
                    "counts": dict(self._counts), "retained_messages": len(self._items), "retained_bytes": self._retained,
                    "capabilities": ["whitelist", "memory_only", "epoch_identity", "bounded_requests"],
                    "gaps": sorted(self._observed_gaps),
                    "external_ai_allowed": False, "qq_reply_enabled": False}

    def detail(self, local_id):
        with self._lock:
            self._expire()
            if local_id not in self._items:
                raise KeyError("PROBE_MESSAGE_NOT_FOUND")
            return copy.deepcopy(self._items[local_id])
