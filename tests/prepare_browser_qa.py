"""Create an isolated synthetic QA database for manual browser verification."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.demo import prepare_demo
from qq_radar.ingestion import import_file
from qq_radar.storage import connect


def main():
    path = Path("data/browser-qa.db")
    prepare_demo(path)
    source = path.parent / "browser-qa.synthetic.jsonl"
    rows = [{"schema_version": "synthetic.v1", "account_id": "synthetic-qa-account", "group_id": "synthetic-qa-group",
             "message_id": f"qa-{i:02d}", "sender_id": "synthetic-qa-user", "sender_name": "合成边界测试",
             "timestamp": f"2026-10-10T11:{i:02d}:00+08:00",
             "segments": [{"type": "text", "text": '<script>alert("synthetic")</script><img src=x onerror=alert("synthetic")>' if i == 0 else f"合成分页样本 {i}"}]}
            for i in range(25)]
    source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    db = connect(path)
    try:
        result = import_file(db, source, {("synthetic-qa-account", "synthetic-qa-group")})
        print(json.dumps(result["counts"]))
    finally:
        db.close()


if __name__ == "__main__":
    main()
