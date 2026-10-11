# 离线候选载荷检查

日期：2026-10-11。关联 TASK-016、REQ-013、DEC-013。该工具只检查合成来源，不调用 AI 或网络，不持久化、不发送。外部服务商、费用与真实来源的接入仍需具体方案。

`qq_radar.outbound.prepare(db, account, group, topic, since=None, until=None)` 返回本地候选及报告；连接可直接使用 `storage.connect(path, readonly=True)`。主题沿用 `analysis.load_rules()` 中的配置，时间边界为毫秒，使用 `timestamp_ms()` 转换带时区的 ISO 时间；区间含开始、不含结束。主程序命令与网页入口如已集成，以 [api.md](api.md) 和 `python qq_bot.py --help` 为准。

输出的 `payload` 只包含固定 schema 版本、已检查的关键词、匿名编号 `e1…` 与 `sanitized_text`；不包含来源账号、群、消息 ID、昵称字段、转发结构、图片或资源地址字段。匿名编号仅在本次候选内有意义，不是原文查询接口的来源 ID。原文及结构化身份始终留在本机数据库。

身份范围为本次账号／群／时间选择内所有父消息及转发节点的可知 `account_id`、`group_id`、`sender_id`、`sender_name`，包含未命中关键词的消息。检查在筛选预览的同一只读快照中执行，结束回滚；不改变既有事务，调用时已有事务会报 `ACTIVE_TRANSACTION`。

已知身份按最长优先屏蔽，ASCII 身份使用单词边界防止直接破坏无关单词；残留的嵌入身份会阻断整批，不当作安全内容放行。长度不超过 2 的身份只要在关键词或候选正文出现，就按歧义阻断。网址（带协议或 `www.`）、邮箱、明确 QQ／群号上下文、常见手机号，以及连续 5 位以上数字均保守屏蔽；数字屏蔽会误伤日期、版本和技术数字。去屏蔽后没有内容的证据被省略，全批无可审查证据则阻断。

`report` 仅包含计数、分类屏蔽次数和固定阻断码，不回显敏感词或正文。`payload=None` 表示整批阻断：`AMBIGUOUS_SHORT_IDENTITY`、`RESIDUAL_KNOWN_IDENTITY`、`SENSITIVE_KEYWORD`、`OUTBOUND_EVIDENCE_LIMIT`、`OUTBOUND_TEXT_LIMIT` 或 `NO_REVIEWABLE_EVIDENCE`。输入账号／群／主题／时间错误沿用分析预览的异常，不回传原文。

`selected_evidence` 和 `redactions` 是截至首次阻断时已进入检查的计数，不是整个账号／群／时间范围的总数；阻断后停止检查并舍弃此前候选，`candidate_evidence=0`。不得据这些计数推断未检查内容已经安全。

上限为 30,000 条选中来源（继承分析预览）、1,000 个命中文字段、单字段 10,000 字符和整批 200,000 字符。超限阻断且不截断、不返回半批候选。注入式文字只当普通数据；本工具没有执行模型指令的能力。

所有结果固定 `allowed_to_send=false`、`requires_human_review=true`、`persisted=false`。未知昵称、暗示身份、经过变形的联系方式及正文语境无法由这些规则完全识别；候选存在也不是实际脱敏安全证明。真实外发前仍需人工审阅、供应商及预算配置，并独立验证发送边界。报告只用于本机检查，不表示已实现外部 AI。

独立检查：`python -m unittest discover -s tests -p test_outbound.py -v`。本次实际覆盖身份／联系方式屏蔽、嵌套转发与未命中消息身份、账号群时间隔离、短词和嵌入词阻断、敏感关键词、去身份后空文、注入文字、媒体排除、长度／数量限制、重复性、只读连接及既有事务保护。

## 实际集成入口

CLI：`python qq_bot.py --db data/source-demo.db payload-preview --account demo-account --group demo-tech --topic ai`；可用 --rules / --since / --until。网页“摘要预览”底部的“检查当前关键词的候选载荷”读取当前账号 / 群和关注词，只在本机显示候选 / 阻断提示。GET /api/v1/outbound/preview 支持 account、group、topic、keywords、since、until；没有发送接口。验证见 task016_validation.md。
