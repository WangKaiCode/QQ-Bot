# TASK-024 DeepSeek 离线契约验证

2026-10-11，Windows / Python 3.14.7，REQ-008、013、014、018。没有读取凭据或发送网络请求。

最终 `python -m unittest discover -s tests -v`：142 项通过（9.435 秒），其中 test_providers.py 新增 22 项。覆盖候选屏蔽到请求到模拟响应闭环、数据库只读、CLI 成功 / 阻断 / 非法参数、网络函数禁用、裸载荷和标记篡改拒绝、媒体 / 身份额外字段拒绝、输入限额、未知 / 重复证据、截断 / 空 / 非法 / 重复键 JSON 与非有限数拒绝、深嵌套拒绝、结果长度、用量及缓存一致性、官方嵌套 details、无对象别名、可选官方 model / object 与输出 token 上限。

独立审查发现初版拒绝官方 prompt_tokens_details / completion_tokens_details，已补限定字段、整数与一致性校验及官方形状合成测试。提示已补 JSON 示例；验证结果保留 allowed_to_send=false / requires_human_review=true。可选 model / object 不一致和完成 token 超出请求上限均拒绝。编译、help 和提交前差异检查单独核验。

结构与本批引用验证不能证明摘要事实正确、匿名化充分或防提示注入有效。本轮没有实际 API 兼容 / 费用 / 模型质量实测，不把模拟响应算作 DeepSeek 连通；未持久化摘要、改 Mock 作业库或开放 HTTP 发送接口。TASK-024 已实现离线子集待验收，实际调用需预算与合成验证方案，真实正文外发仍按现有隐私边界。
