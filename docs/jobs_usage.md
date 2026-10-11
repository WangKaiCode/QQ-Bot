# 离线可恢复 Mock 作业与信息流

2026-10-11，TASK-017，关联 REQ-008 / 009 / 012。仅用于 synthetic.v1。没有真实 AI、通知发送、后台定时器或自动删除。实现位于 `src/qq_radar/jobs.py`；CLI 与页面已集成。

## 使用入口

运行 `python qq_bot.py demo`，首次准备合成原文与独立的 `data/source-demo.jobs.db`，为已关闭的小时 / 日窗口入队并执行一次，之后提供只读网页。重复启动复用作业，不增加同输入卡片。默认信息流支持账号 / 群切换、来源回看、分页和作业记录。

已有库可以分别调用 `jobs-enqueue --account ... --group ... --since ... --until ...`、`jobs-run`、`jobs-list --account ... --group ...` 和 `feed --account ... --group ...`；每条命令之前可指定 `--db` 与 `--jobs-db`。enqueue 默认 ai / hourly，也可传 `--topic`、`--rules` 和 `--kind daily`。时间需带时区；窗口必须完整且已结束。`serve`、`jobs-list`、`feed` 不创建或写入作业库，缺失作业库时页面显示未准备。详见命令 `--help`。

## 最小调用契约

作业库使用 `jobs.connect(path, readonly=False)`，有独立 `jobs_metadata` 标识与 schema v1。只接受空库或本模块数据库，拒绝原文库、陌生库、版本不符及两个连接指向同一文件。原文连接使用 `storage.connect(source_path, readonly=True)`。信息流查询及作业记录浏览可用只读作业连接。

- `enqueue(jobs, source, account, group, topic, kind, since, until, as_of=None)`：按完整北京时间窗口生成 pending 作业；返回 inserted、matched、empty_windows、job_ids。UTC 毫秒 since / until 必须对齐窗口，左闭右开，until 不得超过 as_of。单次最多 72 个小时窗或 3 个日窗。无匹配文字的窗口不创建作业。
- `run(jobs, source, as_of=None)`：每次处理候选快照最多 200 个作业，返回 succeeded、failed、superseded、expired 计数；不会持续运行。运行时发现新输入修订会创建新 pending 作业，下一次 run 再处理。
- `feed(jobs, source, account, group, as_of=None, limit=20, offset=0)`：返回 items 和 next_offset；每个账号 / 群 / 窗口种类 / 窗口 / 主题规则族仅展示最新成功修订。新修订尚未成功时，旧卡片标记 update_pending；即使尚未 enqueue，迟到输入改变当前修订也会标记 input_changed，查询不会自动建立任务。主题规则改变属于不同规则族。
- `list_jobs(jobs, account, group, limit=50)`：查看任务状态、修订、尝试次数及稳定错误码，不返回来源正文。

as_of 默认实际当前时间，测试可注入固定 UTC 毫秒；界面显示时间为北京时间。所有来源读取排除 `expires_at <= as_of`，原文期限沿用消息发生时间加三天，不按导入或作业处理时间续期。非合成或不可用来源仍受原有分析门禁约束。

## 幂等、恢复与失败

作业 ID 复用分析预览 ID，包含账号、群、完整窗口、主题规则、输入修订和 Mock 提供方版本。相同输入重复 enqueue 不增加任务；迟到数据产生不同修订。旧输入任务尚未运行时遇到变化，记录 superseded，并建立新任务。

认领使用短事务、五分钟租约、随机 claim_token 与尝试计数；输出完成时以令牌比较更新。租约过期后可恢复，旧工作者无法覆盖新工作者结果。最多尝试三次，失败终态为 failed_terminal；错误仅记录 JOB_PROCESSING_FAILED 或 ATTEMPT_LIMIT，不保存异常正文、路径或聊天内容。队列及结果写入作业库，原文库始终不被修改。

## 三天原文与十天摘要边界

作业库不复制摘录正文或完整来源正文。持久结果只含主题、输入修订、点的 evidence_id、来源消息 ID / 段路径 / 命中词 / payload_hash；规则 name / keywords / terms 是用户配置，本身可能包含敏感文字，不能宣称数据库绝无任何原文字句。显示期间按来源仍可用、未过期、身份范围和哈希吻合，动态生成最多三条 160 字摘录；与本地 Mock 原样摘录规则一致。

来源过期时保留卡片及证据状态，points 不含 excerpt；不能以“十天摘要”为由保存或重新显示过期原文。来源缺失、内容变化、来源过期分别标记 missing、changed、expired。摘要到期时间固定为窗口结束加十天，迟到、重试与重启均不续期；摘要到期只返回 expired 元数据，无摘录。

这提供可恢复任务与引用信息流的合成闭环，尚未提供来源过期后仍能阅读的真实 AI 摘要。可视到期也不等于物理清理；TASK-008 的实际删除、备份及副本清理仍独立处理。收藏不赋予永久保存权。

## 本模块实际验证

2026-10-11：10 项核心测试及 4 项 CLI / HTTP 集成测试通过，完整套件 68 项通过；浏览器证据见 task017_validation.md。覆盖重复触发、迟到修订及同时间戳最新卡片、未入队的迟到输入提示、旧失败不影响新成功、库内不复制摘录、原文库不变、账号隔离、来源哈希变化、三天 / 十天精确边界、三次失败、过期租约恢复、旧工作者令牌隔离、错误库、完整窗口与分页参数限制。信息流在两个只读快照中分别读取来源与作业状态；不宣称跨两库分布式事务。甲方验收待反馈。
