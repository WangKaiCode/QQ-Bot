# 保留策略只读预览（TASK-015）

2026-10-11。关联 TASK-008 / REQ-012 的合成数据子集。原文 3 天、摘要 10 天已由 DEC-012 确认；本轮提供到期影响检查，不执行清理，不改变原文状态。验证见 [task015_validation.md](task015_validation.md)。

## 网页体验

在项目目录 PowerShell 中运行 `python qq_bot.py demo`，保持终端运行并打开 `http://127.0.0.1:8765`。已有合成库可运行 `python qq_bot.py --db data/source-demo.db serve --port 8765`。启动与停止说明见 [web_usage.md](web_usage.md)。

点击“保留预览”，选择账号与群。在“检查时间”中输入带时区的 ISO 时间，例如 `2026-10-15T12:00:00+08:00`，点击“检查保留范围”；留空使用服务器当前时间。页面显示逻辑消息与到期候选统计，并列出候选的消息 ID、期限、状态、段数与观测数。使用到期记录分页查看后续条目。列表没有正文、发送者或资源路径。

检查未来时间只表示到该时点哪些数据符合候选条件，不会模拟执行删除。仍可切回“原文阅读”查看当前完整合成内容，预览不隐藏过期消息。

## CLI 与 HTTP

建立演示库后，在另一个终端运行：

```powershell
python qq_bot.py --db data/source-demo.db retention-preview --account demo-account --group demo-tech
python qq_bot.py --db data/source-demo.db retention-preview --account demo-account --group demo-tech --as-of 2026-10-15T12:00:00+08:00 --limit 20 --offset 0
```

`--db` 放在子命令之前；账号和群必填。`--as-of` 为带时区时间，省略则使用当前时间；`--limit` 默认 20，允许 1–100；`--offset` 默认 0，必须为非负整数。成功输出 JSON、退出 0；无到期候选也属于成功。无效输入或存储错误向标准错误输出静态错误码，退出 2，不回显原文或文件路径。

已有网页服务提供只读 GET：

```text
/api/v1/retention/preview?account=demo-account&group=demo-tech&as_of=2026-10-15T12%3A00%3A00%2B08%3A00&limit=20&offset=0
```

HTTP 参数 `as_of` 对应 CLI 的 `--as-of`，注意 URL 中 `+` 必须编码为 `%2B`。不带 `as_of` 则使用当前时间。非法或重复参数返回 400；接口沿用本机服务的 Host / Origin 检查与禁止写操作约束，不构成生产认证。

## 期限、统计与候选范围

目前导入器将 `expires_at` 记录为顶层消息发生时间 `occurred_at + 3 天`，并非导入日再加 3 天。历史补录可能导入时已到期；转发子节点跟随所属消息期限。预览按数据库实际保存的 `expires_at <= as_of` 且 `content_status=available` 选取候选，边界时刻也计入。

一次查询在单个只读快照中计算所选账号 / 群；其他范围不计入。非 `synthetic.v1` 数据在该范围内被拒绝。逻辑消息、段和重复观测各有不同计数单位：

| `counts` 字段 | 含义 |
| --- | --- |
| `total_messages` | 所选账号 / 群全部逻辑消息，包括已不可用状态 |
| `due_messages` | 到检查时点符合 available 到期条件的逻辑消息 |
| `already_unavailable_messages` | 状态不是 available 的消息数，不自动推定全部为过期 |
| `status_counts` | 各 content_status 的实际数量；空范围为空对象 |
| `due_segments` | 到期候选的归一化段数，包括转发容器、子节点与内部段 |
| `due_observations` | 关联到期候选的全部观测行数，重复导入也计入 |
| `due_raw_observations` | 上述观测中 raw_json 非 NULL 的行数 |
| `managed_media_files` | 当前为 0；应用尚未下载托管媒体文件 |

候选 `items` 按 expires_at、external_id、id 排序，仅含 id、external_id、expires_at（+08:00）、content_status、segment_count、observation_count。`next_offset` 为下一页偏移，无后续页为 null。并行导入可能改变不同请求之间的候选页；单次请求的统计与条目来自同一快照。

输出明确标记 `readonly=true`、`executed=false`、`policy.retention_active=false`。摘要尚未持久化，因此 `digest_storage_implemented=false`；十天策略是已确认目标，不表示已有摘要清理。

## 尚未覆盖

此预览没有 DELETE、清理任务、tombstone、过期状态切换、媒体文件删除或 SQLite 空间回收；数据库 schema 仍为 user_version=1。数字是数量，不是磁盘占用估算，也不证明所有正文副本均已定位。

用户原始导入文件、应用生成的演示输入文件、终端自行保存的 JSON、备份与截图不在本次候选统计或清理范围内，应用不会自行删除用户文件。尚无收藏例外。真实保留执行前必须定义副本清单、受批准的最小来源元数据、恢复与不可逆操作边界；当前仅合成体验，不能作为生产留存保障。
