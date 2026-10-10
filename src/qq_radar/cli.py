import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .domain import InvalidRecord, timestamp_ms
from .ingestion import ImportAborted, import_file
from .storage import connect, context, detail, report, search


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="QQ-Bot 合成数据离线工具（不接入 QQ / AI）")
    parser.add_argument("--db")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import", help="导入 synthetic.v1 JSONL")
    ingest.add_argument("file")
    ingest.add_argument("--allow", required=True, help="账号 / 群白名单 JSON 文件")
    batch = commands.add_parser("report")
    batch.add_argument("id")
    commands.add_parser("batches", help="列出最近 50 次导入，含未正常结束批次")
    query = commands.add_parser("query")
    query.add_argument("--account", required=True)
    query.add_argument("--group", required=True)
    query.add_argument("--keyword", default="")
    query.add_argument("--since")
    query.add_argument("--until")
    query.add_argument("--limit", type=int, default=50)
    query.add_argument("--offset", type=int, default=0)
    show = commands.add_parser("show")
    show.add_argument("id")
    around = commands.add_parser("context")
    around.add_argument("id")
    around.add_argument("--radius", type=int, default=10)
    for name, help_text in (("demo", "准备合成样本并打开本机来源阅读服务"), ("serve", "只读浏览已有合成数据库")):
        web = commands.add_parser(name, help=help_text)
        web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    db = None
    try:
        db_path = args.db or ("data/source-demo.db" if args.command == "demo" else "data/radar.db")
        if args.command in ("demo", "serve"):
            from .demo import prepare_demo
            from .server import serve
            if not 1 <= args.port <= 65535:
                raise ValueError("INVALID_PORT")
            if args.command == "demo":
                prepare_demo(db_path)
            serve(db_path, args.port)
            return 0
        if args.command == "import":
            config = json.loads(Path(args.allow).read_text(encoding="utf-8"))
            if not isinstance(config, list) or not config:
                raise ValueError("INVALID_ALLOWLIST")
            allowed = set()
            for item in config:
                if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("account_id", "group_id")):
                    raise ValueError("INVALID_ALLOWLIST")
                allowed.add((item["account_id"], item["group_id"]))
        db = connect(db_path, readonly=args.command != "import")
        if args.command == "import":
            result = import_file(db, args.file, allowed)
        elif args.command == "report":
            result = report(db, args.id)
        elif args.command == "batches":
            result = [dict(row) for row in db.execute(
                "SELECT * FROM import_batches ORDER BY started_at DESC, id LIMIT 50")]
        elif args.command == "show":
            result = detail(db, args.id)
        elif args.command == "context":
            result = context(db, args.id, args.radius)
        else:
            result = search(db, args.account, args.group, args.keyword,
                            timestamp_ms(args.since) if args.since else None,
                            timestamp_ms(args.until) if args.until else None, args.limit, args.offset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "import" and result["counts"]["failed"] else 0
    except ImportAborted as exc:
        print(json.dumps({"code": "IMPORT_ABORTED", "batch_id": exc.batch_id}), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
        # Database/filesystem errors may contain paths or input; do not echo.
        code = exc.code if isinstance(exc, InvalidRecord) else (
            exc.args[0] if isinstance(exc, KeyError) else "INVALID_INPUT_OR_STORAGE_ERROR")
        print(json.dumps({"code": code}), file=sys.stderr)
        return 2
    finally:
        if db is not None:
            db.close()
