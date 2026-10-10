# TASK-004 实现验证记录

日期：2026-10-10。关联 REQ-001、002、003、010、015、018。乙方实现验证通过，待甲方体验与验收。复现命令见 [运行说明](offline_usage.md)。实现入口 qq_bot.py，核心模块 src/qq_radar/，测试 tests/test_offline.py；全部合成数据。

环境：Windows 11 10.0.22631 AMD64；处理器报告 AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD；Python 3.14.7，SQLite 3.50.4。未接真实服务或上传 GitHub。

## 自动化与操作验证

`python -m unittest discover -s tests -v`：10 个测试通过。首轮曾因 observations INSERT 占位符数量错误失败；修复后重新执行通过。以下覆盖与测试代码对应：

| 案例 | 结果与证据 |
| --- | --- |
| AC-001、007 | replay_identity_and_conflict：重导 3 条全部 matched，同文不同 ID 保留；equivalent_key_order_matches_and_cli_row_failure：JSON 键序不影响匹配 |
| AC-002、003 | order_and_context_isolation：跨账号 / 群隔离，乱序与同时间按确定规则排序；replay_identity_and_conflict 覆盖跨账号同 ID |
| AC-004、008 | nested_source_and_missing_media：嵌套转发路径、来源字段、未获取图片与未知段；order_and_context_isolation 验证前后文 |
| AC-005、009 | errors_and_allowlist_never_store_excluded_body：6 行计数可对账，错误定位到行，数据库 dump 不含排除正文标记 |
| AC-006 | commit_failure_rolls_back_and_replay_recovers：SQLite trigger 实际拒绝观测写入，当前消息和检查点回滚，重导 1 matched + 2 inserted；process_termination_has_committed_progress_only：子进程 os._exit(37) 后仅已提交 1 行，重新打开数据库重导无重复 |
| 边界 | size_depth_and_nonstandard_json：超长行、过深转发、NaN 报错且后续合法行继续；time_filters_and_invalid_utf8：时间范围、UTC 等价与坏编码；cli_roundtrip_and_exit_codes 与额外错误 CLI 检查批次查询、退出码 |

另外实际执行示例导入：3 seen / 3 inserted / 0 failed；按“网络”查得 m1 嵌套转发原文，UTF-8 输出复查通过。CLI 演示库 data/demo.db 被忽略，不提交。交付前核对 22 个 Markdown 文件的本地相对链接，无断链；`git diff --check` 通过。

## AC-010 合成量基线

`python tests/benchmark_offline.py` 使用种子 410，生成 30,000 条含乱序时间的文本记录，在临时目录导入并重导；程序对计数与消息总量作断言，运行结束关闭数据库并清除临时文件。

- 输入 SHA-256：`829eeddccc5ec09584a064d0e72d0841a745d2bafb86a5ea9d8a7a11431abbae`。
- 默认事务块 200 行；首轮 30,000 inserted，重导 30,000 matched；两次均 0 failed / excluded；逻辑消息总数 30,000。
- 首次导入 12.033 秒（启用 tracemalloc，含追踪开销），重导 2.799 秒（不启用追踪）。
- 首轮 Python 追踪内存峰值 568,422 字节；此指标不含 SQLite 原生内存或进程全部内存，不等同 RSS。
- 两轮后数据库 59,875,328 字节；包含两份批次观测和消息 / 段，不能据此推算含媒体的真实数据容量。

结论限于本机、该合成输入与短时离线回放；未验证真实 30,000 条 / 天持续运行、峰值、2GB 云服务器或多 writer 压力，属于 TASK-010 后续实测。

## 限制与待验收

合成身份 namespace 固定为 synthetic.v1；真实来源稳定 ID / epoch、跨工具身份匹配未实现。本次 schema 简化了草案中的账号 / 会话 / 身份关联实体，使用显式账号群组合与外键保留最小闭环，见 data_model.md。无真实留存清理、媒体处理、QQ 跳转或 Web 展示。甲方尚未确认产品验收，不将自动化通过记为已验收。
