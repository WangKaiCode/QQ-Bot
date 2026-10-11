"""All OneBot events here are synthetic; tests never contact QQ or resources."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.onebot import Probe, normalize_event

TOKEN = "synthetic-test-token-32-characters-only"
CONFIG = {"account": "100001", "allowed_groups": ["200001"], "token": TOKEN}


def event(**changes):
    value = {"self_id": 100001, "post_type": "message", "message_type": "group", "group_id": 200001,
             "message_id": -42, "user_id": 300001, "time": 1791640800,
             "sender": {"nickname": "合成昵称"}, "message": [{"type": "text", "data": {"text": "synthetic AI discussion"}}]}
    value.update(changes)
    return value


def body(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class OneBotTests(unittest.TestCase):
    def probe(self, config=CONFIG):
        probe = Probe(config)
        self.addCleanup(probe.close)
        return probe

    def normalize(self, value):
        return normalize_event(value, "100001", ["200001"], "synthetic-epoch")

    def test_numeric_identity_namespace_and_utc_time(self):
        value = self.normalize(event(self_id="100001", group_id="200001", message_id="-42"))
        self.assertEqual(value["namespace"], "onebot.v11")
        self.assertEqual(value["schema_version"], "onebot.probe.v1")
        self.assertEqual(value["identity"]["message_id"], "-42")
        self.assertTrue(value["timestamp"].endswith("+00:00"))
        self.assertEqual(value["content_status"], "available")

    def test_scope_excluded_before_invalid_or_private_content(self):
        for changes, reason in (({"self_id": 100002}, "ACCOUNT_OUTSIDE_SCOPE"),
                                ({"message_type": "private"}, "NOT_GROUP_MESSAGE"),
                                ({"group_id": 200002}, "GROUP_OUTSIDE_SCOPE")):
            result = self.normalize(event(message=object(), **changes))
            self.assertEqual(result, {"excluded": True, "reason": reason})
            self.assertNotIn("sender", result)

    def test_invalid_ids_time_and_sender_rejected(self):
        for key, values in (("self_id", [True, 1.0, " 100001", "1e5", "١٠٠٠٠١", 2 ** 63]),
                            ("group_id", [False, "0", "-3"]), ("message_id", [False, 1.5, "+42"]),
                            ("time", [True, 1.5, -1, 253402300800])):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.normalize(event(**{key: value}))
        with self.assertRaises(ValueError):
            self.normalize(event(sender="private nick"))

    def test_media_refs_mentions_reply_unknown_and_missing_forward(self):
        message = [{"type": "image", "data": {"url": "https://private.test/image", "file": "private-image"}},
                   {"type": "record", "data": {"file": "https://private.test/audio"}},
                   {"type": "at", "data": {"qq": "all"}}, {"type": "reply", "data": {"id": "-123"}},
                   {"type": "forward", "data": {"id": "synthetic-reference"}},
                   {"type": "json", "data": {"data": "private unknown contents"}}]
        result = self.normalize(event(message=message))
        self.assertEqual(result["content_status"], "pending")
        self.assertEqual(result["segments"][4]["state"], "pending")
        self.assertEqual(result["segments"][3]["state"], "reference_only")
        self.assertNotIn("https://private.test", json.dumps(result))
        self.assertNotIn("private unknown contents", json.dumps(result))

    def test_inline_forward_extension_and_cq_string_not_complete(self):
        nested = [{"type": "forward", "data": {"content": [{"type": "node", "data": {
            "user_id": "300002", "nickname": "合成转发者", "content": [{"type": "text", "data": {"text": "nested synthetic"}}]}}]}}]
        result = self.normalize(event(message=nested))
        self.assertEqual(result["content_status"], "partial")
        self.assertIn("inline_forward_extension_unverified", result["gaps"])
        result = self.normalize(event(message="hello [CQ:image,file=private]"))
        self.assertEqual(result["content_status"], "partial")
        self.assertNotIn("private", json.dumps(result))

    def test_config_requires_explicit_scope_token_and_upper_limits(self):
        for changes in ({"account": ""}, {"allowed_groups": []}, {"allowed_groups": "200001"},
                        {"token": "short"}, {"max_messages": 101}, {"max_bytes": 1048577},
                        {"max_retained_bytes": 262145}, {"duration_seconds": 3601}, {"max_messages": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Probe({**CONFIG, **changes})

    def test_auth_size_and_invalid_json_static_responses(self):
        probe = self.probe({**CONFIG, "max_bytes": 500})
        self.assertEqual(probe.receive(b"private payload", "wrong")["reason"], "UNAUTHORIZED")
        self.assertEqual(probe.receive(b"x" * 501, TOKEN)["reason"], "REQUEST_LIMIT")
        self.assertEqual(probe.receive(b"not json private payload", TOKEN)["reason"], "INVALID_EVENT")
        with patch("qq_radar.onebot.hmac.compare_digest", wraps=__import__("hmac").compare_digest) as compare:
            probe.receive(body(event()), TOKEN)
            compare.assert_called_once()
        self.assertNotIn("payload", json.dumps(probe.snapshot()))

    def test_dedup_conflict_retains_original_and_snapshot_no_identity(self):
        probe = self.probe()
        result = probe.receive(body(event()), TOKEN)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(probe.receive(body(event()), TOKEN)["status"], "matched")
        self.assertEqual(probe.receive(body(event(message="different private text")), TOKEN)["status"], "conflicts")
        detail = probe.detail(result["local_id"])
        self.assertEqual(detail["segments"][0]["text"], "synthetic AI discussion")
        detail["segments"][0]["text"] = "mutated"
        self.assertNotEqual(probe.detail(result["local_id"])["segments"][0]["text"], "mutated")
        snapshot = json.dumps(probe.snapshot(), ensure_ascii=False)
        for text in ("100001", "200001", "300001", "合成昵称", "synthetic AI discussion", result["local_id"]):
            self.assertNotIn(text, snapshot)
        self.assertFalse(probe.snapshot()["external_ai_allowed"])

    def test_message_and_retention_limits_no_unbounded_capture(self):
        probe = self.probe({**CONFIG, "max_messages": 1})
        probe.receive(body(event()), TOKEN)
        self.assertEqual(probe.receive(body(event(message_id=43)), TOKEN)["reason"], "SESSION_LIMIT")
        self.assertEqual(probe.snapshot()["retained_messages"], 1)
        probe = self.probe({**CONFIG, "max_retained_bytes": 10})
        self.assertEqual(probe.receive(body(event()), TOKEN)["reason"], "SESSION_LIMIT")
        self.assertEqual(probe.snapshot()["retained_bytes"], 0)

    def test_expiry_close_purge_and_new_epoch(self):
        with patch("qq_radar.onebot.time.monotonic", return_value=10):
            probe = self.probe({**CONFIG, "duration_seconds": 1})
            accepted = probe.receive(body(event()), TOKEN)
            old_epoch = probe.detail(accepted["local_id"])["identity"]["epoch"]
        with patch("qq_radar.onebot.time.monotonic", return_value=11):
            self.assertTrue(probe.snapshot()["closed"])
            self.assertEqual(probe.snapshot()["retained_messages"], 0)
            with self.assertRaises(KeyError):
                probe.detail(accepted["local_id"])
            self.assertEqual(probe.receive(body(event()), TOKEN)["reason"], "SESSION_CLOSED")
            new_probe = self.probe()
            accepted = new_probe.receive(body(event()), TOKEN)
            self.assertNotEqual(old_epoch, new_probe.detail(accepted["local_id"])["identity"]["epoch"])
            new_probe.close()
            self.assertEqual(new_probe.snapshot()["retained_bytes"], 0)

    def test_malformed_large_nested_and_nan_inputs_fail_without_body_echo(self):
        probe = self.probe()
        self.assertEqual(probe.receive(body(event(extra=float("nan"))), TOKEN)["reason"], "INVALID_EVENT")
        invalid_unicode = json.dumps(event(message=[{"type": "text", "data": {"text": "\ud800"}}])).encode("utf-8")
        self.assertEqual(probe.receive(invalid_unicode, TOKEN)["reason"], "INVALID_EVENT")
        too_many = [{"type": "text", "data": {"text": "x"}}] * 1001
        self.assertEqual(probe.receive(body(event(message=too_many)), TOKEN)["reason"], "INVALID_EVENT")

    def test_idle_session_timer_clears_content_without_new_requests(self):
        with patch("qq_radar.onebot.threading.Timer") as timer:
            probe = self.probe()
            received = probe.receive(body(event()), TOKEN)
            timer.assert_called_once()
            self.assertEqual(timer.call_args.args[0], 3600)
            timer.return_value.start.assert_called_once()
            timer.call_args.args[1]()
            self.assertTrue(probe.snapshot()["closed"])
            self.assertEqual(probe.snapshot()["retained_bytes"], 0)
            with self.assertRaises(KeyError):
                probe.detail(received["local_id"])

    def test_parsing_crossing_deadline_never_accepts_or_records_conflict(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                with patch("qq_radar.onebot.time.monotonic", return_value=10):
                    probe = self.probe({**CONFIG, "duration_seconds": 1})
                    if duplicate:
                        probe.receive(body(event()), TOKEN)
                with patch("qq_radar.onebot.time.monotonic", side_effect=[10.5, 11.0]):
                    result = probe.receive(body(event(message="different content")), TOKEN)
                self.assertEqual(result, {"status": "stopped", "reason": "SESSION_CLOSED"})
                snapshot = probe.snapshot()
                self.assertEqual(snapshot["retained_messages"], 0)
                self.assertEqual(snapshot["counts"]["accepted"], int(duplicate))
                self.assertEqual(snapshot["counts"]["conflicts"], 0)


if __name__ == "__main__":
    unittest.main()
