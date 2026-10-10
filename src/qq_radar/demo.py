"""Repeatable synthetic reading scenarios; never uses real message data."""
import json
from pathlib import Path

from .ingestion import import_file
from .storage import connect


def demo_records():
    def message(mid, text, minute, group="demo-tech", account="demo-account", segments=None):
        return {"schema_version": "synthetic.v1", "account_id": account, "group_id": group,
                "message_id": mid, "sender_id": "synthetic-reader", "sender_name": "合成用户 · 林",
                "timestamp": f"2026-10-10T10:{minute:02d}:00+08:00",
                "segments": segments if segments is not None else [{"type": "text", "text": text}]}
    first = message("sample-01", "周末想试一试本地模型，先整理内存占用和推理速度的测试方法。", 0)
    return [first,
            message("sample-02", "AI 工具怎么选？比起参数大小，更想知道自己的工作流能省多少时间。", 3),
            message("sample-03", "", 5, segments=[{"type": "forward", "nodes": [
                {"sender_name": "合成转发者 · 陈", "sender_id": "synthetic-forward", "timestamp": "2026-10-10T09:42:00+08:00", "segments": [
                    {"type": "text", "text": "合成转发：评估本地 AI 的三个维度：准确性、延迟和资源占用。"},
                    {"type": "forward", "nodes": [{"sender_name": "合成转发者 · 周", "segments": [
                        {"type": "text", "text": "网络条件也要单独测量，避免把下载耗时算成推理耗时。"},
                        {"type": "image", "resource_ref": "synthetic://benchmark-chart"}]}]}]},
                {"segments": [{"type": "text", "text": "原始链接保留作参考，当前不会抓取网页。"},
                              {"type": "link", "url": "https://example.com/synthetic-ai-notes"}]}]}]),
            message("sample-04", "赞同，先用一组固定问题对照，再看是否值得投入。", 7),
            message("sample-05", "", 10, segments=[{"type": "image", "resource_ref": "synthetic://network-screenshot"}]),
            message("sample-06", "", 12, segments=[{"type": "future_segment", "label": "合成的新消息格式"}]),
            message("sample-07", "计算机网络：路由规则修改后，需要核对 DNS 与连接延迟。", 15, group="demo-network"),
            message("sample-02", "第二账号的 AI 讨论；消息 ID 相同，内容独立。", 3, account="demo-second-account"),
            first, message("sample-02", "同身份但内容不同的合成冲突，用于检查导入报告。", 3),
            "{synthetic invalid json", message("sample-excluded", "白名单外的合成正文不会保存。", 20, group="demo-excluded")]


def prepare_demo(db_path):
    path = Path(db_path).resolve()
    source = path.parent / "reading-demo.synthetic.jsonl"
    content = "\n".join(row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in demo_records()) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if source.exists() and source.read_text(encoding="utf-8") != content:
        raise ValueError("DEMO_SOURCE_CHANGED")
    if not source.exists():
        source.write_text(content, encoding="utf-8", newline="\n")
    db = connect(path)
    try:
        return import_file(db, source, {("demo-account", "demo-tech"), ("demo-account", "demo-network"),
                                       ("demo-second-account", "demo-tech")})
    finally:
        db.close()
