# 最小数据模型草案 v0.1

2026-10-10，TASK-003 / TASK-004。下表保留完整设计提案；TASK-004 已实现下述最小 schema，后续实体仍未实现。数据库使用 PRAGMA user_version=1，仅初始化新空库；拒绝未知版本与已有非本应用表的未版本化库，当前无历史版本升级迁移。

## TASK-004 实际 schema v1

实现定义见 src/qq_radar/storage.py。messages 直接保存 account_id、group_id、namespace 固定 synthetic.v1、external_id，并以这四项唯一；不依赖内容哈希合并身份。原始行 raw_json（去行末换行）、canonical JSON SHA-256、发送者快照、原始时间、UTC 毫秒、首次接收时间、expires_at（消息时间 + 3 天）及 available 状态保存于 messages。canonical 哈希忽略对象键顺序 / 空白，但任何字段值变化均报身份冲突，不自动覆盖旧文。

message_segments 通过消息外键及唯一 path 保存段 / forward_node、父路径、状态和元数据；text 聚合字段仅用于查询，不替代原文。import_batches 保存源版本、文件哈希、状态和已提交行；observations 以批次 / 行号唯一保存终态、错误码、消息关联及合法白名单观测的原始行和哈希。无效行仅保存错误元数据；excluded 不保存正文或哈希。报告计数从已提交 observations 聚合。一个事务块内消息、段、观测和进度同时提交。

此离线最小实现没有独立 accounts、conversations、message_keys、observation_messages、附件表或 ambiguous 身份匹配。显式账号 / 群限定实现隔离；真实 adapter 上线前重新设计 namespace / epoch 与迁移，不能将 synthetic 身份保证扩展到 QQ。未自动清理到期正文；详情当前仍返回 available，真实保留及 expired 查询状态归 TASK-008。

## 基本约定

本地对象使用独立 UUID 字符串；所有上游 ID（含账号、群、用户、消息、序号）作为字符串保留，不依赖整数精度或连续性。时间使用 UTC epoch 毫秒，显示与任务窗口按 Asia/Shanghai；上游原始时间及其单位保留并验证，无法解析不编造时间。

| 实体 | 核心字段与约束 | 增量 |
| --- | --- | --- |
| accounts | id、platform、external_account_id、display_name；平台 + 账号唯一；无凭据 | M0 |
| conversations | id、account_id、kind、external_peer_id、name；账号 + 类型 + peer 唯一 | M0 |
| import_batches | id、source、source_version、file_sha256、status、seen / inserted / matched / ambiguous / failed / excluded 计数、时间 | M0 |
| observations | id、batch_id、source_record_key、payload_hash、raw_json、received_at、parse_status、error_code；批次内来源记录键唯一 | M0 |
| messages | id、conversation_id、sender_external_id、sender_name、occurred_at、first_received_at、text、content_status、expires_at | M0 |
| message_keys | message_id、account_id、conversation_id、source_namespace、external_id、identity_epoch；组合唯一，用于经验证的来源身份映射 | M0 |
| observation_messages | observation_id、message_id、match_method、confidence / state；保留观测到消息的关联 | M0 |
| message_segments | id、message_id、parent_segment_id、node_path、kind、text / metadata、state；消息内路径唯一 | M0 |
| attachments | id、segment_id、resource_ref、managed_path、sha256、size、fetch_state、expires_at | M1；M0 可仅保留资源引用 |
| collection_runs / gaps | 账号 / 群、起止、连接状态、断线区间、恢复状态、证据与错误 | M1 |
| checkpoints | 账号 / 群 / 接入源 / scope、上游游标、最后提交批次、更新时间 | M1 |
| subscriptions | 主题描述、关键词、启用状态、配置版本 | M1 |
| analysis_jobs | kind、window、subscription_version、input_revision、provider、status、lease、attempt、next_retry、cost、error | M1 |
| digests / evidence | 摘要、版本、任务 ID；证据指向消息或段的本地 ID，含可用状态 | M1 |
| feedback / notifications | 阅读 / 收藏 / 忽略动作；通知渠道、去重键、发送状态 | M1 / M2 |

账号和会话外键不可省略。sender_name 是观测快照，不能以昵称推定同一人。forward 子节点保存嵌套来源信息和节点顺序，未知字段在保留周期内保留。

## 去重与身份匹配

1. 同一文件哈希 + 源记录键重复导入保证幂等；保留每次导入的计数，不重复新增逻辑消息。
2. 同一来源的稳定 ID，仅在经验证的 namespace 和 identity_epoch 内匹配；重启后 ID 稳定性未知时使用新的 epoch，不盲目合并。
3. 跨 OneBot / QCE 匹配优先使用已验证的原生 ID / 序号映射。同时间、同发送人、同文本的消息可能重复发送，内容 hash 不能作为唯一身份。
4. 无可信映射时记录待匹配候选和原因，保留两份观测，不删除所谓重复。待实测确定后再合并映射；统计应区分确认消息数与不确定重复。

M0 的去重保证限于已定义的合成输入身份和同文件重导；不能宣传跨工具去重已解决。

## 数据提交与计数

导入批次允许分批事务，记录已提交位置。每条观测都有明确终态或待处理状态。解析失败保留可追踪记录；非白名单正文不持久化，计数仅记录排除数量。批次成功不代表上游完整。

采集检查点与同批观测的持久化一起提交；分析检查点只在输出与证据提交成功后推进。数据库空间不足、锁超时、无效字段等失败必须可见。

## 过期与引用

源正文到期后可保留受批准的最小来源元数据和 tombstone，使摘要引用显示 expired，而不是返回虚构正文。撤回、媒体缺失、来源失效、未知身份分别记录，不混作过期。

raw_json、转发文本、OCR、副本、导入文件、附件与索引都应纳入数据清单和清理策略；用户原始导出文件只读，应用不得自行删除。应用托管副本与备份需有独立期限，不能靠 SQLite 行删除保证所有副本已经清除。

具体正文 3 天、摘要 10 天已由 DEC-012 确认；收藏例外及媒体副本规则仍待甲方确认。
