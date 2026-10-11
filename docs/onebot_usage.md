# OneBot 11 受限探针核心

日期：2026-10-11。TASK-018，关联 TASK-005 的本机试验准备、REQ-001 / 002 / 003 / 015 / 018。当前仅离线解析与内存会话，未安装 NapCat、登录 QQ、开启 HTTP / WebSocket、获取历史或请求资源。测试事件均为合成数据，不能作为真实兼容性或完整采集的证明。

## 可运行合成回放

`python qq_bot.py onebot-replay tests/fixtures/onebot.synthetic.jsonl --account 100001 --group 200001`

回放文件每行是 `schema_version=onebot.replay.v1`、`synthetic=true` 与 `event`。此标记声明合成来源，不会自动匿名化真实数据；禁止把真实聊天改标后回放。单文件最多 1 MiB、1,000 行；内存会话仍最多 100 条。回放生成随机会话 token，不打印或保存；最终只输出计数、缺口、行号与静态错误码，不输出身份、正文或 local_id。返回前清空会话，finally 也保证异常清空；输出 snapshot_phase=before_purge 表明计数取自清空前，purged=true 表明已清空。成功退出 0，有行错误退出 1，文件 / 配置错误退出 2。`--db` 不会被打开，不创建来源 / 作业库。

用户批准范围仍为独立测试账号和一个白名单群；模块可配置列表的上限不扩大该授权。组件许可和真实接收入口尚待明确，见 real_ingestion_proposal.md。

协议依据为 [OneBot 11 官方群消息事件](https://raw.githubusercontent.com/botuniverse/onebot-11/master/event/message.md) 与 [官方消息段](https://raw.githubusercontent.com/botuniverse/onebot-11/master/message/segment.md)，2026-10-11 读取。协议给出身份、时间和消息段字段；转发引用需要额外动作取得正文，本核心不会执行该动作。协议网页入口当次无法打开，使用同仓库原文；NapCat 对应版本与 QQ 运行能力仍需单独实测。

`normalize_event(event, account, allowed_groups, epoch)` 首先校验接入账号和群范围，再读取正文。群外、私聊及非消息事件只返回 `{excluded:true,reason:静态码}`，不包含正文、昵称、来源 ID 或 raw payload。ID 只接受 ASCII 十进制整数或其字符串，不接受布尔、浮点、空白和科学记数；账号／群／发送者必须为正的 int64，消息 ID 可为有符号 int64。时间必须为非负整数 UTC 秒且可转换为日期。

接纳结果使用独立 `schema_version=onebot.probe.v1`、`namespace=onebot.v11`，包含 `identity={account,group,message_id,epoch}`、UTC ISO 时间、有限发送者信息、segments、content_status 和 gaps。不转换成 synthetic.v1，不写既有合成库，不假设跨 QQ / NapCat 重启消息 ID 稳定。

已支持数组文字、图片／语音占位、at 和 reply 引用、forward / node 引用，以及显式内联 content 的有限递归解析。图片／语音地址及未知段正文不保留或抓取。forward 缺 content 时状态是 pending，reply 仅 reference_only；内联转发属于待实际验证的扩展并保持 partial。含 CQ 码的字符串暂标 unsupported，避免当作完整文字解析。最多 1,000 个段和 8 层递归；未知、资源未获取和引用未解决都有缺口，不表示 OCR、转发恢复或精确 QQ 跳转已实现。

`Probe(config)` 必须显式提供 `account`、非空列表 `allowed_groups`（最多 20 项）、长度 32–256 UTF-8 字节的 `token`；未填写拒绝启动。可选配置：`max_messages` 默认 100 且最大 100，`max_bytes` 默认及最大 1,048,576 字节，`max_retained_bytes` 默认及最大 262,144 字节，`duration_seconds` 默认及最大 3,600 秒。保留预算计算整个规范结果的 UTF-8 序列化尺寸，包含正文和元数据，不只是文字字符数。

`max_retained_bytes` 是规范化 JSON 的字节预算，不是 Python 对象、解释器或整个进程的堆内存上限；解析请求及临时对象也占内存。解析／规范化／哈希处理后会再次检查截止时间，越过截止的请求不会返回 accepted、matched 或 conflicts，也不会保留新内容。

- `receive(body:bytes, token:str)`：常量时间核验 token，检查单次字节限额，只接纳范围内消息。结果为静态状态／原因，成功时附随机 `local_id`。不包含自动回复或任何 OneBot 快速操作。
- `snapshot()`：仅计数、静态能力／缺口、保留数量／字节，不含账号、群、消息 ID、昵称、正文、token 或 local_id。固定 `external_ai_allowed=false`、`qq_reply_enabled=false`、`persisted=false`。
- `detail(local_id)`：仅供将来的本机会话审阅返回白名单规范内容的深拷贝；HTTP 集成必须另做本机认证，不能公开这个接口。
- `close()`：清空内容和身份映射，后续接收返回 SESSION_CLOSED。单调时钟检查和后台到期计时器保证停止后的内容不可再查询；无新请求的空闲会话也会由计时器清空。

每次新会话生成随机 epoch，同一会话身份重复且整个接纳事件内容哈希相同计为 matched；不同内容计 conflicts，保留首次规范内容，不保存或回显冲突原文。计数和 hash 留在内存，关闭清空正文。未知字段变化也可能保守地计为冲突，不能用这项指标推定上游身份规则已验证。

核心不创建日志、文件或数据库，不执行 QQ 动作、不调用外部 AI、不访问链接。字节限额、群白名单和会话限额属于本应用范围；未来受限 listener 的绑定地址、传输认证、调用日志及实际 NapCat 自身缓存 / 日志保留另行核验。进程内清空不能承诺操作系统交换文件、第三方软件缓存或手工复制的数据已被安全擦除。

检查命令：`python -m unittest discover -s tests -p test_onebot.py -v`。实际测试范围为合成协议字段、范围排除顺序、身份／时间验证、媒体与引用缺口、内联转发、CQ 字符串、配置／鉴权／限额、去重冲突、纯计数快照、截止关闭与 epoch 重建、异常 JSON／Unicode、空闲清空。真实 QQ / NapCat 试验结果需独立记录。

核心 13 项、回放 / CLI 4 项测试通过，包含解析跨过截止点后不得接收或记录冲突。完整验证见 task018_validation.md。
