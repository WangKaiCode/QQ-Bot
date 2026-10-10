"""AC-010 reproducible synthetic baseline, not a production capacity promise."""
import hashlib
import json
import platform
import random
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar.ingestion import import_file
from qq_radar.storage import connect


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "synthetic-30000.jsonl"
        random_source = random.Random(410)
        start = datetime(2026, 10, 10, tzinfo=timezone.utc)
        with source.open("w", encoding="utf-8", newline="\n") as stream:
            for i in range(30000):
                row = {"schema_version": "synthetic.v1", "account_id": "benchmark-account", "group_id": "benchmark-group",
                       "message_id": f"synthetic-{i:05d}", "sender_id": f"synthetic-user-{i % 20}",
                       "timestamp": (start + timedelta(seconds=random_source.randrange(86400))).isoformat(),
                       "segments": [{"type": "text", "text": f"合成 AI 网络讨论 {random_source.randrange(100)}"}]}
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        db_path = root / "benchmark.db"
        db = connect(db_path)
        try:
            tracemalloc.start()
            begin = time.perf_counter()
            result = import_file(db, source, {("benchmark-account", "benchmark-group")})
            seconds = time.perf_counter() - begin
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            begin = time.perf_counter()
            replay = import_file(db, source, {("benchmark-account", "benchmark-group")})
            replay_seconds = time.perf_counter() - begin
            assert result["counts"] == {"seen": 30000, "inserted": 30000, "matched": 0, "failed": 0, "excluded": 0}
            assert replay["counts"]["matched"] == 30000
            assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 30000
            print(json.dumps({"system": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
                              "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                              "seed": 410, "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                              "chunk_size": 200, "import_seconds_with_tracemalloc": round(seconds, 3),
                              "replay_seconds": round(replay_seconds, 3), "python_traced_peak_bytes": peak,
                              "database_bytes_after_replay": db_path.stat().st_size,
                              "first_counts": result["counts"], "replay_counts": replay["counts"]}, indent=2))
        finally:
            db.close()


if __name__ == "__main__":
    main()
