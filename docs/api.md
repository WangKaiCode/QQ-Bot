# 接口与输入契约草案 v0.1

2026-10-10，TASK-003 / TASK-004 / TASK-013。离线 CLI 已实现，见 [运行说明](offline_usage.md)；本机只读来源查询子集已通过 TASK-013 提供，下述其他 M1 接口仍为草案。本文件定义自研应用契约；不是 NapCat / QCE 官方接口规范。

## M0 合成输入

UTF-8 JSONL，每行一个对象；`schema_version` 为 `synthetic.v1`，account_id、group_id、message_id、sender_id 均为字符串；`timestamp` 为带 UTC 偏移的 ISO 8601 字符串。segments 按顺序保存。

```json
{"schema_version":"synthetic.v1","account_id":"demo-account","group_id":"demo-group","message_id":"demo-message-1","sender_id":"demo-user","sender_name":"样例用户","timestamp":"2026-10-10T10:00:00+08:00","segments":[{"type":"text","text":"讨论 AI 工具"}]}
```

转发段使用 `type: forward`、`nodes` 数组；node 可含 sender_id、timestamp、segments 并允许嵌套。图片段使用 `type: image`、resource_ref；M0 不读取资源路径或下载 URL。未知类型保留 metadata 与 unsupported 状态。JSON 无效、缺必需字段、错误时间和冲突 ID 均返回行号与错误码。

输入不冒充 QCE 格式。取得实际脱敏样本并检查版本后新增独立适配契约；不同来源通过 adapter 转换为 domain 对象，禁止把 JSON 字段相似当作已兼容。

实际 CLI 操作：import、batches、report、query、show、context，入口 qq_bot.py。query 必须指定账号与群，时间范围为 [since, until)，关键词按字面子串；limit / offset 分页。输入限制与退出码见 offline_usage.md。link 段需字符串 url，image 需字符串 resource_ref；forward 节点的可选 sender_id / sender_name 为非空字符串，可选 timestamp 同顶层时间约束。未知字段保留在原文；转发节点元数据与段路径分别保存。文件不读取媒体或链接内容。

## M1 应用接口

### TASK-013 已实现的本机子集

固定绑定 127.0.0.1，只读 synthetic.v1 数据库，无生产认证能力。GET /api/v1/health 返回 mode=synthetic、readonly=true、retention_active=false；GET /api/v1/conversations 返回账号 / 群与消息数；GET /api/v1/messages 要求 account、group，支持 keyword、since、until、limit（默认 20，1–100）、offset（非负），返回 items / next_offset。此增量采用 offset 分页，未来生产游标仍为提议。

GET /api/v1/messages/{id} 返回实际来源与规范化段；GET /api/v1/messages/{id}/context 的 radius 默认 2、范围 0–50；GET /api/v1/imports 列最近 50 批，GET /api/v1/imports/{id} 返回计数与错误行，无失败原文。参数验证 400、未知对象 / 路径 404、POST 405、存储异常 503，错误 JSON 含 code、request_id；错误页不回显路径或原文。Host / Origin 不属于本机服务或明确 cross-site 请求拒绝 403，不提供 CORS。

页面仅使用上述接口，消息 / 段 / 来源字段以 textContent 渲染。原文查询当前未执行到期判断，retention_active=false；不要将历史 available 状态解释为生产保留契约已完成。下表完整 M1 路线中未说明为已实现的接口仍为提案。

| 方法与路径 | 作用 | 主要约束 |
| --- | --- | --- |
| GET /api/v1/health | 进程 / 存储状态 | 不暴露凭据 |
| GET /api/v1/imports/{id} | 导入计数与失败状态 | 可获取行号与错误，不返回无关群正文 |
| GET /api/v1/messages | 群、时间、关键词查询 | 游标分页；建议默认 50、最大 200，待实现确认 |
| GET /api/v1/messages/{id} | 消息、段、来源状态 | 过期对象返回元数据和 content_status=expired |
| GET /api/v1/messages/{id}/context | 前后文 | 限同账号同群；建议前后各 10，最大各 50 |
| GET /api/v1/integrity | 采集窗口与缺口报告 | 明确 unknown / partial / 对照验证通过的含义 |
| GET、POST /api/v1/subscriptions | 关注主题 | 配置版本影响分析任务身份 |
| GET /api/v1/digests | 小时 / 日摘要 | 带证据、分析版本与输入范围 |
| POST /api/v1/feedback | 已读、收藏、忽略 | 幂等键；不自动改变原文保存期限 |
| GET /api/v1/notifications | Web 通知中心 | 外部通知独立上线 |
| POST /api/v1/retention/preview | 查看待清理范围 | 只预览，不删除 |

M0 不要求 Web 服务。网络接口上线时统一对象 ID、时间与错误结构；非法参数 400 / 验证错误，未知对象 404，冲突 409，未配置能力 503；过期已知对象返回状态，不能与从未存在混淆。错误响应含 code、message、request_id，不含完整原始聊天或密钥。

初期仅本机访问。远程 / 云端访问前补充认证、HTTPS 与请求权限；监听 localhost 本身不能代替完整访问控制设计。

## AI provider 契约

输入：job_id、主题版本、匿名本地 evidence_id、经允许的内容、输入时间窗口。输出：主题标题、摘要、重要性及 evidence_ids。模型不得访问 QQ 凭据、文件系统或执行聊天中的指令。输出证据只能属于本批输入，由应用验证；不接受模型生成的 URL 作为原文定位依据。

Mock provider 用于 M0 / 测试；外部与本地 provider 实际启用分别记录配置、授权范围、能力和费用。默认不开启网络调用。请求中不自动附加昵称、QQ 号、群号或图片；任何字段策略改变需先确认具体载荷。

## TASK-014 已实现的分析预览子集（2026-10-11）

GET /api/v1/topics 返回默认 rules.v1 主题列表。GET /api/v1/analysis/preview 必须给 account、group，topic 默认 ai，kind 为 hourly / daily；keywords 可用英文逗号传 1–20 个、各至多 40 字符的词，临时覆盖所选主题；since / until 同 [起点, 终点) ISO 时区规则。重复查询参数、空关键词、未知主题 / 非法窗口返回 400 INVALID_QUERY。

返回 coverage、digests、requested_range、mode=synthetic、persisted=false、scheduled=false。digests 含 window_start/end（北京时间分桶边界）、input_revision、topic、provider=mock.extractive.v1、points 与 evidence。CLI 时间范围可能只覆盖窗口的一部分，应以 requested_range 理解实际输入范围，不把分桶边界视作完整采集。证据含匿名 evidence_id、message_id、转发 path 与实际 terms；points 只能引用当前窗口证据并复制支持的原文 / 160 字符截断。

最多读取 30,000 条逻辑消息，超限失败不截断；仅 synthetic.v1 / available 输入。此接口不实现上表持久 digests、subscriptions 或 AI provider 契约；Mock 输入只有匿名证据号与文字，正文身份仍未处理。运行、配置与统计解释见 analysis_usage.md。

## TASK-015 保留范围 GET 子集

GET /api/v1/retention/preview 要求 account、group；as_of 可传带时区 ISO 时间，默认当前时刻；limit 为 1–100，offset 非负。返回 policy、as_of、scope、counts、items 与 next_offset，readonly=true / executed=false。候选为 expires_at<=as_of 且 available 的消息，只有 ID / external_id / 到期时间 / 状态 / 段数 / 观测数，不含正文和发送者。全部统计在同一只读事务内，按时间和身份稳定分页；翻页应用保存首次 as_of。上表 POST 清理预览仍为路线提案。字段解释见 retention_usage.md。

TASK-016：GET /api/v1/outbound/preview 的范围 / 规则参数复用 analysis/preview（不支持kind参数），返回 payload（或null）、report、allowed_to_send=false、requires_human_review=true。仅离线检查、绝不发送；非法查询400。阻断理由和统计不回显身份 / 原文，未知身份需人工复核，完整契约见 outbound_usage.md。
