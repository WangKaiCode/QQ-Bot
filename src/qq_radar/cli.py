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
    parser = argparse.ArgumentParser(description="QQ-Bot 本机受限开发工具（不自动启动 QQ 或调用 AI）")
    parser.add_argument("--db")
    parser.add_argument("--jobs-db", help="独立作业库；默认原文库旁的 .jobs.db")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("onebot-replay", help="只读合成 OneBot JSONL 回放；不连接 QQ 或写数据库")
    replay.add_argument("file")
    replay.add_argument("--account", required=True)
    replay.add_argument("--group", required=True)
    probe_server = commands.add_parser("probe-serve", help="受限本机内存探针；不启动 QQ / NapCat")
    probe_server.add_argument("--config", required=True, help="仅本地保存的配置文件；不得提交真实凭据")
    probe_server.add_argument("--port", type=int, default=8766)
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
    analysis = commands.add_parser("analyze", help="离线规则筛选与 Mock 摘录预览，不写库")
    analysis.add_argument("--account", required=True)
    analysis.add_argument("--group", required=True)
    analysis.add_argument("--rules")
    analysis.add_argument("--topic", default="ai")
    analysis.add_argument("--kind", choices=("hourly", "daily"), default="hourly")
    analysis.add_argument("--since")
    analysis.add_argument("--until")
    payload = commands.add_parser("payload-preview", help="本地检查候选文字载荷，不发送")
    payload.add_argument("--account", required=True)
    payload.add_argument("--group", required=True)
    payload.add_argument("--rules")
    payload.add_argument("--topic", default="ai")
    payload.add_argument("--since")
    payload.add_argument("--until")
    retention = commands.add_parser("retention-preview", help="只读查看到期范围，不删除")
    retention.add_argument("--account", required=True)
    retention.add_argument("--group", required=True)
    retention.add_argument("--as-of", help="带时区的检查时间；默认当前时间")
    retention.add_argument("--limit", type=int, default=20)
    retention.add_argument("--offset", type=int, default=0)
    queued = commands.add_parser("jobs-enqueue", help="为已关闭完整窗口建立离线 Mock 作业")
    queued.add_argument("--account", required=True)
    queued.add_argument("--group", required=True)
    queued.add_argument("--rules")
    queued.add_argument("--topic", default="ai")
    queued.add_argument("--kind", choices=("hourly", "daily"), default="hourly")
    queued.add_argument("--since", required=True)
    queued.add_argument("--until", required=True)
    queued.add_argument("--as-of")
    runner = commands.add_parser("jobs-run", help="一次性运行或恢复本地 Mock 作业")
    runner.add_argument("--as-of")
    for name in ("jobs-list", "feed"):
        listing = commands.add_parser(name)
        listing.add_argument("--account", required=True)
        listing.add_argument("--group", required=True)
        listing.add_argument("--limit", type=int, default=50 if name == "jobs-list" else 20)
        if name == "feed":
            listing.add_argument("--offset", type=int, default=0)
            listing.add_argument("--as-of")
    for name, help_text in (("demo", "准备合成样本并打开本机来源阅读服务"), ("serve", "只读浏览已有合成数据库")):
        web = commands.add_parser(name, help=help_text)
        web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    db = jobs_db = None
    try:
        if args.command == "probe-serve":
            from .probe_server import serve
            with Path(args.config).open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("CONFIG_LIMIT")
            config = json.loads(raw)
            keys = {"account", "allowed_groups", "token", "max_messages", "max_bytes", "max_retained_bytes", "duration_seconds"}
            if not isinstance(config, dict) or set(config) - keys or not isinstance(config.get("allowed_groups"), list) or len(config["allowed_groups"]) != 1:
                raise ValueError("INVALID_PROBE_CONFIG")
            if not 1 <= args.port <= 65535:
                raise ValueError("INVALID_PORT")
            serve(config, args.port)
            return 0
        if args.command == "onebot-replay":
            from .onebot_replay import replay
            result = replay(args.file, args.account, args.group)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["errors"] else 0
        db_path = args.db or ("data/source-demo.db" if args.command == "demo" else "data/radar.db")
        jobs_path = Path(args.jobs_db) if args.jobs_db else Path(db_path).with_suffix(".jobs.db")
        if args.command in ("demo", "serve"):
            from .demo import prepare_demo, prepare_jobs
            from .server import serve
            if not 1 <= args.port <= 65535:
                raise ValueError("INVALID_PORT")
            if args.command == "demo":
                prepare_demo(db_path)
                prepare_jobs(db_path, jobs_path)
            serve(db_path, args.port, jobs_path)
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
        elif args.command == "retention-preview":
            from .retention import preview
            result = preview(db, args.account, args.group, timestamp_ms(args.as_of) if args.as_of else None,
                             args.limit, args.offset)
        elif args.command in ("jobs-enqueue", "jobs-run", "jobs-list", "feed"):
            from . import jobs
            jobs_db = jobs.connect(jobs_path, readonly=args.command in ("jobs-list", "feed"))
            as_of = timestamp_ms(args.as_of) if hasattr(args, "as_of") and args.as_of else None
            if args.command == "jobs-enqueue":
                from .analysis import load_rules
                rules = load_rules(args.rules) if args.rules else load_rules()
                topic = next((item for item in rules["topics"] if item["id"] == args.topic), None)
                if topic is None:
                    raise ValueError("UNKNOWN_TOPIC")
                result = jobs.enqueue(jobs_db, db, args.account, args.group, topic, args.kind,
                                      timestamp_ms(args.since), timestamp_ms(args.until), as_of)
            elif args.command == "jobs-run":
                result = jobs.run(jobs_db, db, as_of)
            elif args.command == "jobs-list":
                result = jobs.list_jobs(jobs_db, args.account, args.group, args.limit)
            else:
                result = jobs.feed(jobs_db, db, args.account, args.group, as_of, args.limit, args.offset)
        elif args.command in ("analyze", "payload-preview"):
            from .analysis import load_rules, preview
            rules = load_rules(args.rules) if args.rules else load_rules()
            topic = next((item for item in rules["topics"] if item["id"] == args.topic), None)
            if topic is None:
                raise ValueError("UNKNOWN_TOPIC")
            since = timestamp_ms(args.since) if args.since else None
            until = timestamp_ms(args.until) if args.until else None
            if args.command == "payload-preview":
                from .outbound import prepare
                result = prepare(db, args.account, args.group, topic, since, until)
            else:
                result = preview(db, args.account, args.group, topic, args.kind, since, until)
        else:
            result = search(db, args.account, args.group, args.keyword,
                            timestamp_ms(args.since) if args.since else None,
                            timestamp_ms(args.until) if args.until else None, args.limit, args.offset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "import" and result["counts"]["failed"] else 0
    except ImportAborted as exc:
        print(json.dumps({"code": "IMPORT_ABORTED", "batch_id": exc.batch_id}), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, ValueError, KeyError, RecursionError) as exc:
        # Database/filesystem errors may contain paths or input; do not echo.
        code = exc.code if isinstance(exc, InvalidRecord) else (
            exc.args[0] if isinstance(exc, KeyError) else "INVALID_INPUT_OR_STORAGE_ERROR")
        print(json.dumps({"code": code}), file=sys.stderr)
        return 2
    finally:
        if db is not None:
            db.close()
        if jobs_db is not None:
            jobs_db.close()
