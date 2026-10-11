# 本机合成 Mock 周期调度

2026-10-11，TASK-023 / REQ-008、015、018。沿用标准库与现有独立作业库，只处理 synthetic.v1。它在前台运行，退出进程后不再调度。

已有合成库可以运行：

```powershell
python qq_bot.py --db data/source-demo.db jobs-schedule --account demo-account --group demo-tech --interval 60
```

先按 web_usage.md 准备演示库。`--jobs-db` 可指定独立作业库，否则使用原文库旁 `.jobs.db`。`--rules` / `--topic` 沿用已有主题配置；`--max-ticks 1` 只处理一轮后退出。interval 为每轮完成后的等待秒数（1–3600），max-ticks 为 1–10000；这不是精确固定墙钟频率。Ctrl+C 安全退出，最后输出完成轮数与 interrupted。出错停止，不回显路径、异常正文、账号、群或关键词。

每轮重新打开只读原文库与可写作业库，关闭连接后再等待；轮次不重叠。全库 namespace / 批次源版本与 schema 门禁拒绝混入真实输入，即使该输入已经过期或不在选定群。不会把真实 QQ 库标成合成数据。

每轮按当前北京时间回扫最近 72 个完整小时与 3 个完整日窗口，只入队已经结束的窗口，然后执行一次同账号 / 群 / 主题规则的候选作业，最多 200 个。其他范围任务不受本轮执行影响；未来结束窗口不执行。来源到期精确排除，停机补齐不能恢复已经过期或从未采集的内容。重复轮次复用身份，迟到数据产生修订，租约与失败重试沿用 jobs_usage.md。

每轮输出一行 JSON 统计：mode=synthetic、scheduled=true、as_of、enqueue.hourly / daily 的 inserted / matched / empty_windows、run 的 succeeded / failed / superseded / expired；不包含正文、任务 ID 或身份。运行结束后输出 summary。若 run.failed>0，表示该轮存在处理失败，具体作业状态通过 jobs-list 查看，最多三次尝试。

这是本机 Mock 周期调度，不提供操作系统开机自启、进程守护、真实 AI、通知或删除。网页仍只读；feed 的 scheduled=false 描述查询本身不触发调度，不能作为另一个前台进程运行状态探针。无需修改原文或作业 schema。
