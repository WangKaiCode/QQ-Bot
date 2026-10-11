"""Business boundary checks for read-only synthetic rule/digest previews."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.analysis import iso, load_rules, matched_terms, preview, validate_output
from qq_radar.domain import timestamp_ms
from qq_radar.ingestion import import_file
from qq_radar.storage import connect, detail


TOPIC = {"id": "ai", "name": "人工智能", "keywords": ["AI"]}


def record(mid, text="AI discussion", timestamp="2026-10-10T10:00:00+08:00", **changes):
    value = {"schema_version": "synthetic.v1", "account_id": "a", "group_id": "g",
             "message_id": mid, "sender_id": "synthetic-user", "timestamp": timestamp,
             "segments": [{"type": "text", "text": text}]}
    value.update(changes)
    return value


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "analysis.db")
        self.addCleanup(self.db.close)

    def ingest(self, records):
        path = self.root / "input.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n", encoding="utf-8")
        result = import_file(self.db, path, {(row["account_id"], row["group_id"]) for row in records})
        self.assertEqual(result["counts"]["failed"], 0)
        return result

    def test_ascii_word_boundaries_and_chinese_keywords(self):
        for text in ("AI", "ai!", "关于AI讨论", "(AI)"):
            with self.subTest(text=text):
                self.assertEqual(matched_terms(text, ["AI"]), ["AI"])
        for text in ("chair", "AI2", "my_AI", "AIM", "AI_tool"):
            with self.subTest(text=text):
                self.assertEqual(matched_terms(text, ["AI"]), [])
        self.assertEqual(matched_terms("讨论计算机网络和 DNS", ["网络", "dns"]), ["网络", "dns"])

    def test_nested_forward_evidence_resolves_exact_source_segment(self):
        self.ingest([record("nested", segments=[{"type": "forward", "nodes": [{"segments": [
            {"type": "forward", "nodes": [{"segments": [{"type": "text", "text": "nested AI evidence"}]}]}]}]}])])
        digest = preview(self.db, "a", "g", TOPIC)["digests"][0]
        evidence = digest["evidence"][0]
        expected = "segments/0/nodes/0/segments/0/nodes/0/segments/0"
        self.assertEqual(evidence["path"], expected)
        source = detail(self.db, evidence["message_id"])
        segment = next(item for item in source["segments"] if item["path"] == expected)
        self.assertEqual(segment["metadata"]["text"], digest["points"][0]["excerpt"])

    def test_scope_isolated_with_colliding_external_ids(self):
        self.ingest([record("same", "AI account a"), record("same", "AI account b", account_id="b"),
                     record("same", "AI other group", group_id="other")])
        for account, group, expected in (("a", "g", "AI account a"), ("b", "g", "AI account b"),
                                         ("a", "other", "AI other group")):
            result = preview(self.db, account, group, TOPIC)
            self.assertEqual(result["coverage"]["messages"], 1)
            self.assertEqual(result["digests"][0]["points"][0]["excerpt"], expected)
        self.assertEqual(preview(self.db, "missing", "g", TOPIC)["digests"], [])

    def test_beijing_hour_day_and_half_open_range(self):
        self.ingest([record("before", timestamp="2026-10-10T23:59:59.999+08:00"),
                     record("midnight", timestamp="2026-10-10T16:00:00Z"),
                     record("next-hour", timestamp="2026-10-11T01:00:00+08:00")])
        hourly = preview(self.db, "a", "g", TOPIC)["digests"]
        self.assertEqual([item["window_start"] for item in hourly],
                         ["2026-10-11T01:00:00+08:00", "2026-10-11T00:00:00+08:00", "2026-10-10T23:00:00+08:00"])
        daily = preview(self.db, "a", "g", TOPIC, "daily")["digests"]
        self.assertEqual([len(item["evidence"]) for item in daily], [2, 1])
        self.assertEqual(daily[0]["window_start"], "2026-10-11T00:00:00+08:00")
        result = preview(self.db, "a", "g", TOPIC, since=timestamp_ms("2026-10-11T00:00:00+08:00"),
                         until=timestamp_ms("2026-10-11T01:00:00+08:00"))
        self.assertEqual(result["coverage"]["messages"], 1)

    def test_preview_is_repeatable_readonly_and_does_not_persist(self):
        self.ingest([record("one"), record("two", "AI second")])
        before = list(self.db.iterdump())
        changed = self.db.total_changes
        first = preview(self.db, "a", "g", TOPIC)
        self.assertEqual(first, preview(self.db, "a", "g", TOPIC))
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.db.total_changes, changed)
        self.assertFalse(self.db.in_transaction)
        self.assertFalse(first["persisted"])
        readonly = connect(self.root / "analysis.db", readonly=True)
        try:
            self.assertEqual(first, preview(readonly, "a", "g", TOPIC))
        finally:
            readonly.close()

    def test_late_arrival_changes_only_affected_window_revision(self):
        self.ingest([record("one"), record("other", timestamp="2026-10-10T11:00:00+08:00")])
        before = preview(self.db, "a", "g", TOPIC)["digests"]
        self.ingest([record("late", "unrelated late message", timestamp="2026-10-10T10:15:00+08:00")])
        after = preview(self.db, "a", "g", TOPIC)["digests"]
        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before[1]["input_revision"], after[1]["input_revision"])
        self.assertNotEqual(before[1]["id"], after[1]["id"])
        self.assertEqual(before[1]["points"], after[1]["points"])

    def test_provider_sees_only_anonymous_text_and_rejects_forgery(self):
        self.ingest([record("one")])
        captured = []
        def provider(items):
            captured.extend(items)
            return [{"evidence_id": "forged", "excerpt": items[0]["text"]}]
        with self.assertRaisesRegex(ValueError, "INVALID_EVIDENCE"):
            preview(self.db, "a", "g", TOPIC, provider=provider)
        self.assertEqual(set(captured[0]), {"evidence_id", "text"})
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(preview(self.db, "a", "g", TOPIC)["coverage"]["messages"], 1)

    def test_cross_window_provider_evidence_rejected(self):
        self.ingest([record("one"), record("two", timestamp="2026-10-10T11:00:00+08:00")])
        previous = []
        def stale_provider(items):
            if previous:
                return previous
            previous.extend([{"evidence_id": items[0]["evidence_id"], "excerpt": items[0]["text"]}])
            return previous
        with self.assertRaisesRegex(ValueError, "INVALID_EVIDENCE"):
            preview(self.db, "a", "g", TOPIC, provider=stale_provider)

    def test_output_rejects_unsupported_excerpt_and_duplicate_evidence(self):
        evidence = [{"evidence_id": "e1", "text": "AI source"}]
        for output, code in (([{"evidence_id": "e1", "excerpt": "AI invented"}], "UNSUPPORTED_EXCERPT"),
                             ([{"evidence_id": "e1", "excerpt": "AI source…"}], "UNSUPPORTED_EXCERPT"),
                             ([{"evidence_id": "e1", "excerpt": "AI source"}] * 2, "INVALID_EVIDENCE"),
                             ([], "INVALID_PROVIDER_OUTPUT")):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, code):
                    validate_output(output, evidence)

    def test_long_source_truncation_remains_supported_and_traceable(self):
        text = "AI " + "合成证据" * 60
        self.ingest([record("long", text)])
        digest = preview(self.db, "a", "g", TOPIC)["digests"][0]
        point = digest["points"][0]
        self.assertEqual(point["excerpt"], text[:160] + "…")
        self.assertEqual(point["evidence_id"], digest["evidence"][0]["evidence_id"])
        self.assertEqual(detail(self.db, digest["evidence"][0]["message_id"])["text"], text)

    def test_image_and_unknown_segments_remain_unknown_not_negative(self):
        self.ingest([record("image", segments=[{"type": "image", "resource_ref": "synthetic://image"}]),
                     record("unknown", segments=[{"type": "future_format", "text": "AI unsupported"}]),
                     record("text", "AI known")])
        result = preview(self.db, "a", "g", TOPIC)
        self.assertEqual(result["coverage"], {"messages": 3, "matched_messages": 1, "image_segments": 1,
                                              "unsupported_segments": 1, "empty_text_messages": 2})
        self.assertEqual(len(result["digests"][0]["evidence"]), 1)

    def test_invalid_config_scope_and_window(self):
        invalid = [None, {}, {"schema_version": "rules.v1", "topics": []},
                   {"schema_version": "rules.v1", "topics": [TOPIC, TOPIC]},
                   {"schema_version": "rules.v1", "topics": [{**TOPIC, "keywords": [""]}]}]
        path = self.root / "rules.json"
        for config in invalid:
            with self.subTest(config=config):
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_rules(path)
        for kwargs in ({"kind": "weekly"}, {"since": 1, "until": 1}, {"since": 2, "until": 1}):
            with self.assertRaises(ValueError):
                preview(self.db, "a", "g", TOPIC, **kwargs)
        with self.assertRaisesRegex(ValueError, "INVALID_ANALYSIS_SCOPE"):
            preview(self.db, "", "g", TOPIC)
        with self.assertRaisesRegex(ValueError, "INVALID_KEYWORDS"):
            preview(self.db, "a", "g", {**TOPIC, "keywords": []})

    def test_extreme_dates_are_rejected_and_epoch_is_supported(self):
        self.assertEqual(iso(0), "1970-01-01T08:00:00+08:00")
        self.assertEqual(iso(timestamp_ms("0001-01-02T00:00:00+08:00")), "0001-01-02T00:00:00+08:00")
        for value in (10 ** 30, -(10 ** 30), timestamp_ms("9999-12-31T23:59:59Z")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "INVALID_WINDOW"):
                    iso(value)
                with self.assertRaisesRegex(ValueError, "INVALID_WINDOW"):
                    preview(self.db, "a", "g", TOPIC, since=value)
        # Even a valid stored date may have a rounded window end beyond year 9999.
        self.ingest([record("far-future", timestamp="9999-12-31T23:59:59+08:00")])
        with self.assertRaisesRegex(ValueError, "INVALID_WINDOW"):
            preview(self.db, "a", "g", TOPIC)
        self.assertFalse(self.db.in_transaction)

    def test_preview_message_limit_accepts_30000_rejects_30001(self):
        self.ingest([record("seed")])
        seed_id = self.db.execute("SELECT id FROM messages").fetchone()[0]
        # Lightweight SQL fixtures exercise the actual query limit without
        # generating or importing thirty thousand JSON source records.
        sql = """INSERT INTO messages
            SELECT ?, account_id, group_id, ?, namespace, sender_id, sender_name,
                   occurred_at, original_timestamp, first_received_at, expires_at,
                   text, raw_json, payload_hash, content_status
            FROM messages WHERE id=?"""
        with self.db:
            self.db.executemany(sql, [(f"limit-{index}", f"limit-{index}", seed_id) for index in range(29999)])
        result = preview(self.db, "a", "g", TOPIC)
        self.assertEqual(result["coverage"]["messages"], 30000)
        self.assertEqual(result["coverage"]["matched_messages"], 1)
        with self.db:
            self.db.execute(sql, ("overflow", "overflow", seed_id))
        before = self.db.total_changes
        with self.assertRaisesRegex(ValueError, "PREVIEW_LIMIT_EXCEEDED"):
            preview(self.db, "a", "g", TOPIC)
        self.assertEqual(self.db.total_changes, before)
        self.assertFalse(self.db.in_transaction)

    def test_non_synthetic_or_unavailable_sources_are_rejected(self):
        self.ingest([record("one")])
        for column, value in (("namespace", "onebot.v1"), ("content_status", "expired")):
            with self.subTest(column=column):
                with self.db:
                    self.db.execute(f"UPDATE messages SET {column}=?", (value,))
                with self.assertRaisesRegex(ValueError, "SYNTHETIC_AVAILABLE_ONLY"):
                    preview(self.db, "a", "g", TOPIC)
                self.assertFalse(self.db.in_transaction)
                with self.db:
                    self.db.execute("UPDATE messages SET namespace='synthetic.v1',content_status='available'")


if __name__ == "__main__":
    unittest.main()
