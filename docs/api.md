# 接口与输入契约草案 v0.1

2026-10-10，TASK-003。未实现、未开放任何服务。本文件定义自研应用契约；不是 NapCat / QCE 官方接口规范。

## M0 合成输入

UTF-8 JSONL，每行一个对象；`schema_version` 为 `synthetic.v1`，account_id、group_id、message_id、sender_id 均为字符串；`timestamp` 为带 UTC 偏移的 ISO 8601 字符串。segments 按顺序保存。

```json
{"schema_version":"synthetic.v1","account_id":"demo-account","group_id":"demo-group","message_id":"demo-message-1","sender_id":"demo-user","sender_name":"样例用户","timestamp":"2026-10-10T10:00:00+08:00","segments":[{"type":"text","text":"讨论 AI 工具"}]}
```

转发段使用 `type: forward`、`nodes` 数组；node 可含 sender_id、timestamp、segments 并允许嵌套。图片段使用 `type: image`、resource_ref；M0 不读取资源路径或下载 URL。未知类型保留 metadata 与 unsupported 状态。JSON 无效、缺必需字段、错误时间和冲突 ID 均返回行号与错误码。

输入不冒充 QCE 格式。取得实际脱敏样本并检查版本后新增独立适配契约；不同来源通过 adapter 转换为 domain 对象，禁止把 JSON 字段相似当作已兼容。

拟定 CLI 操作：导入指定文件与白名单、读取批次报告、按本地消息 ID 查看原文及上下文、按关键词 / 群 / 时间查询、回放合成样本。最终命令以实现后的运行文档为准。

## M1 应用接口

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
