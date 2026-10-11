# TASK-025 受控调用验证

2026-10-11，Windows / Python 3.14.7。关联 REQ-008、013、014、018，预算授权见 DEC-032。

完整 `python -m unittest discover -s tests -v`：156 项通过（10.128 秒），含 test_deepseek_client.py 14 项新增。网络全部 mock，API key 为合成测试字符串。覆盖单 POST、固定 endpoint / Flash / TLS、禁代理与重定向、请求冻结、预算预留 / 重复阻断、失败与中断不退款、100k 限长、响应校验、非法配置 / 日期 / 预算、陌生账本拒绝、CLI 哈希匹配及错哈希在配置读取前阻断、原文 / 作业 / 配置及硬链接碰撞保护。账本无密钥、原文或完整响应。

独立审查额外用 8 个 Python 进程竞争同一 2 元账本（mock发送）：恰 2 次成功、6 次 MONTHLY_BUDGET_EXCEEDED，账本 2 条 / 2,000,000 microCNY。实际 urllib 默认错误处理链模拟 301 / 302 / 303 / 307 / 308 均拒绝跳转；默认 TLS check_hostname=true、CERT_REQUIRED。HTTPError 已补显式 close。编译、CLI help 和 Git 差异检查通过。

没有真实 API 连通或扣费证据。本机空密钥配置已创建并确认被 Git 忽略，用户需在本机填写后回复；此时不读取 / 输出真实密钥。真实验证仍待该前置和审查过的合成候选。TASK-025 受控入口已实现待验收，不能标记真实 AI 摘要整体完成、供应商全账户账单受控或产品已验收。
