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

## TASK-014 瞬时预览数据（2026-10-11）

本轮 schema 仍为 user_version=1，未建立摘要、订阅或作业表。分析读取 messages / message_segments，在单个只读事务中得到一致快照。input_revision 为窗口内消息 ID / payload_hash 的稳定摘要；预览 ID 包含账号、群、窗口种类、分桶起点、筛选边界、主题规则和输入版本。匿名证据号由窗口 / 消息 / 路径哈希生成，应用内映射回原文；不代表正文已去身份。预览与临时设置不持久化，终端 JSON 输出或截图的自行保存不构成应用的十天摘要存储契约。真实到期清理尚未执行。

TASK-015（2026-10-11）：无 schema 改变，只读扫描已有 expires_at；当前期限由 ingestion 按 occurred_at+3天写入，历史补录可能立即进入到期候选。预览同时计 message_segments 和 observations（重复观测也有原文副本），只报告不删除。托管媒体当前未下载，文件计数为 0 不表示媒体清理已实现。

TASK-017：原文 schema 不变；独立作业 SQLite schema v1，以 jobs_metadata 标识 qq-radar.mock-jobs.v1。jobs 保存范围 / 规则 / 修订、状态 / 尝试次数 / 五分钟租约 / claim_token、固定窗口结束加十天期限及结果引用。引用结果不复制摘录；读取信息流时按来源哈希和期限动态补充。规则与命中词自身可能敏感。两库不允许同路径 / 同文件；不宣称跨库原子事务。完整状态和到期契约见 jobs_usage.md。

TASK-018：独立 onebot.v11 内存身份 account / group / message_id / 随机会话 epoch；不写入任何数据库，不假设跨重启稳定。有限规范段与身份哈希在关闭 / 到期时清空；快照仅静态能力和计数。JSON 保留预算不代表 Python 堆大小或操作系统安全擦除，第三方缓存 / 日志未验证。真实三天持久来源能力尚未实现。

TASK-023 / 024：不改原文 / 作业 schema。周期调度复用现有修订与租约身份；DeepSeek 候选请求与模拟响应仅瞬时构造 / 校验，无密钥、用量账本或真实摘要表。结构校验后的结果不自动写入 Mock 作业库；供应商摘要持久化与十天物理清理仍需独立设计验证。

TASK-025：独立预算 SQLite schema v1，ledger_metadata magic=qq-radar.deepseek-budget.v1；api_calls 保存 UUID、北京时间月、请求 SHA256、固定预留 microCNY、reserved / succeeded / failed、静态错误、时间与纯用量 JSON，(month,request_hash) 唯一。预留先提交再发送，中断仍保留 reserved；不保存 API key、候选正文或完整响应。原文 / 作业库不迁移，成功摘要仅返回给调用者，不自动持久化。

TASK-026 不改变预算 schema；查询采用 URI mode=ro 与单事务快照。所有调用状态均计入预留，失败不退款；缺失账本返回零且不初始化。
