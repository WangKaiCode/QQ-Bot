"""synthetic.v1 validation and lossless segment normalization."""
import hashlib
import json
from datetime import datetime, timezone


class InvalidRecord(ValueError):
    def __init__(self, code, field):
        self.code, self.field = code, field
        super().__init__(f"{code}: {field}")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def timestamp_ms(value, field="timestamp"):
    try:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError()
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
        delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    except (ValueError, OverflowError):
        raise InvalidRecord("INVALID_TIMESTAMP", field) from None


def string(obj, key, path="", required=True):
    if key not in obj and not required:
        return
    if not isinstance(obj.get(key), str) or not obj[key].strip():
        raise InvalidRecord("INVALID_FIELD", path + key)


def normalize(record):
    if not isinstance(record, dict):
        raise InvalidRecord("INVALID_RECORD", "root")
    if record.get("schema_version") != "synthetic.v1":
        raise InvalidRecord("UNSUPPORTED_SCHEMA", "schema_version")
    for key in ("account_id", "group_id", "message_id", "sender_id"):
        string(record, key)
    string(record, "sender_name", required=False)
    occurred = timestamp_ms(record.get("timestamp"))
    segments, texts = [], []

    def walk(items, parent=None, prefix="segments", depth=0):
        if depth > 16:
            raise InvalidRecord("DEPTH_LIMIT", prefix)
        if not isinstance(items, list):
            raise InvalidRecord("INVALID_FIELD", prefix)
        for i, item in enumerate(items):
            path = f"{prefix}/{i}"
            if len(segments) >= 10000:
                raise InvalidRecord("SEGMENT_LIMIT", path)
            if not isinstance(item, dict):
                raise InvalidRecord("INVALID_FIELD", path)
            string(item, "type", path + "/")
            kind = item["type"]
            state = "parsed"
            if kind == "text":
                if not isinstance(item.get("text"), str):
                    raise InvalidRecord("INVALID_FIELD", path + "/text")
                texts.append(item["text"])
            elif kind == "image":
                string(item, "resource_ref", path + "/")
                state = "not_fetched"
            elif kind == "link":
                string(item, "url", path + "/")
                texts.append(item["url"])
            elif kind != "forward":
                state = "unsupported"
            # Full source content lives once in raw_json; normalized metadata
            # excludes child arrays to avoid quadratic storage for forwards.
            metadata = {k: v for k, v in item.items() if k != "nodes"}
            segments.append((path, parent, kind, state, encode(metadata)))
            if kind == "forward":
                nodes = item.get("nodes")
                if not isinstance(nodes, list):
                    raise InvalidRecord("INVALID_FIELD", path + "/nodes")
                for n, node in enumerate(nodes):
                    node_path = f"{path}/nodes/{n}"
                    if len(segments) >= 10000:
                        raise InvalidRecord("SEGMENT_LIMIT", node_path)
                    if not isinstance(node, dict):
                        raise InvalidRecord("INVALID_FIELD", node_path)
                    for key in ("sender_id", "sender_name"):
                        string(node, key, node_path + "/", required=False)
                    if "timestamp" in node:
                        timestamp_ms(node["timestamp"], node_path + "/timestamp")
                    segments.append((node_path, path, "forward_node", "parsed",
                                     encode({k: v for k, v in node.items() if k != "segments"})))
                    walk(node.get("segments"), node_path, node_path + "/segments", depth + 1)

    walk(record.get("segments"))
    canonical = encode(record)
    return occurred, "\n".join(texts), segments, hashlib.sha256(canonical.encode()).hexdigest()
