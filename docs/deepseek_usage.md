# 受控单次合成 DeepSeek 试验

2026-10-11，TASK-025 / REQ-008、013、014、018。用户已明确批准后续调用，月费用上限 20 元（DEC-032）。这里只开放手工单次合成请求，不连接真实 QQ 或周期发送任务。

## 配置与复核

本机忽略文件 `data/deepseek.local.json`：

```json
{"api_key":"","monthly_budget_cny":20}
```

用户仅在本机填写 api_key，不在聊天、命令行或 Git 提供密钥；配置只允许这两个字段。monthly_budget_cny 为 1–20 的整数，可降低、不可高于已授权值。账本默认 `data/deepseek.budget.db`，不能与原文 / 作业库、配置文件或其硬链接相同；不得复制、重置账本绕过本地限额。

先按 provider_usage.md 查看 candidate 文字。CLI provider-preview 额外输出 request_sha256（复核元数据，不是模块原始请求 envelope 的字段）。检查后执行相同范围 / 规则 / max-tokens，传入该 SHA：

```powershell
python qq_bot.py --db data/source-demo.db provider-preview --account demo-account --group demo-tech
python qq_bot.py --db data/source-demo.db deepseek-call --account demo-account --group demo-tech --config data/deepseek.local.json --review-sha256 <检查后的请求SHA256>
```

范围或候选内容变化导致哈希不同，拒绝且不读取密钥或创建账本。哈希只绑定请求内容，不证明人审已经完成或匿名化充分。当前仅允许 deepseek-flash，非思考、非流式，固定官方 HTTPS endpoint；不读取环境变量、使用自动代理或跟随重定向，保留默认 TLS 验证。

## 预算与故障

单次完整 JSON 请求至多 100,000 UTF-8 bytes、输出 max-tokens 128–4096。北京时间月键，账本先用 BEGIN IMMEDIATE 事务预留 1 元，再发一次 POST。本月预留总额不得超过配置且不高于 20 元；每次请求 SHA 在该月唯一。预算不足或重复请求在网络前拒绝。

每次试验的 1 元预留不按实际费用退款，因此最多 20 个不同请求 / 月；失败、超时、进程中断、响应校验失败也保留预留，不自动重试。网络结果不明不得删除记录重发。账本只存哈希、时间、静态状态 / 错误、用量计数，不存密钥、请求正文或完整响应。Ctrl+C 可能留下 reserved，这仍占预算并阻止重复。timeout 默认为 30 秒（1–60），是标准库网络操作超时，不宣称严格的整轮墙钟截止。

成功输出 mode=synthetic-api / sent=true 与验证后的摘要、usage 和预留统计，但不持久化摘要或接入 Mock 队列；allowed_to_send=false / requires_human_review=true 继续禁止自动转发并提示审核结果。终端输出自行保存的副本不由该模块执行十天清理。

2026-10-11 [官方人民币报价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：Flash 高峰未命中输入 2 元 / 百万 token、输出 8 元 / 百万 token。按 byte 与 token 的保守近似，本轮限额估计低于 1 元；官方没有承诺这种近似是严格上界。该账本控制本客户端预留，不是供应商账户硬预算，不覆盖其他客户端消费或账本 / 时钟人为修改。初次试验报价仅当日有效，之后返回 PRICE_RECHECK_REQUIRED，由乙方重新核对价格再推进，不自动套用陈旧报价。

标准库依据：[urllib](https://docs.python.org/3.14/library/urllib.request.html)、[TLS](https://docs.python.org/3.14/library/ssl.html)，许可沿用 DEC-016 的 PSF 记录，无新 SDK。接口 / JSON / 服务条款证据仍见 provider_usage.md。真实正文、自动批量调用、精确实际费用核算与摘要持久化不在本次已实现范围。

## 只读预算查询（TASK-026）

```powershell
python qq_bot.py deepseek-budget
python qq_bot.py deepseek-budget --monthly-budget 10 --as-of 2026-10-11T22:00:00+08:00
```

返回北京时间月份、显示上限、本月预留、剩余预留额度及 reserved / succeeded / failed 次数。--monthly-budget 只改变显示计算，不修改调用配置或账本；应与调用配置保持一致，剩余下界为零。不读取密钥、不打开来源库、不联网、不要求当日报价。账本不存在返回零且不创建路径；已有账本使用只读快照，损坏 / 陌生库拒绝。账本保护自身历史，不是供应商实际账单。

2026-10-11 单次专属合成试验在 TLS 阶段失败，当前本月预留 1 元、剩余 19 元、failed=1；没有响应 / 用量 / 扣费确认。同一请求不重发、不重置账本。用户确认使用 Clash Verge TUN；保持网络开启，不因排查中断会话，不关闭 TLS 验证。
