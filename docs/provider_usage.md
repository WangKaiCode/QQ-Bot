# DeepSeek 离线接口预览

2026-10-11，TASK-024 / REQ-008、013、014、018。用户明确已有 DeepSeek API；本增量准备可切换 provider 的接口和响应验证，不读取密钥、不联网或扣费。

## 本机请求预览

```powershell
python qq_bot.py --db data/source-demo.db provider-preview --account demo-account --group demo-tech
```

也可传 `--rules`、`--topic`、`--since`、`--until`，输入范围复用 payload-preview。先运行候选载荷屏蔽，再构造官方请求结构；屏蔽阻断或超出接口限额则拒绝，不绕过。请求包含筛选后候选文字，输出供用户本机检查；自行重定向保存文件属于用户保存副本，不改变现有留存契约。

默认模型 deepseek-flash，也支持离线选择 deepseek-v4-pro；max-tokens 默认 1024，本地上限与参数见 CLI help 和源码。模型价格 / 能力可能改变，真正启用前需再次核验。当前 endpoint 固定为官方 https://api.deepseek.com/chat/completions，没有自定义 URL、API key 或 Authorization 字段。

build_request 仅接受完整 synthetic 的 outbound preview 契约，allowed_to_send=false、requires_human_review=true，拒绝裸载荷、阻断预览、多余媒体 / 身份字段及伪造格式。输出仍为 mode=offline、allowed_to_send=false、requires_human_review=true，不构成真实调用授权；字典结构校验不能证明其来源不可伪造，也不能证明完整匿名化。

## 响应校验

模块 validate_response 在本机校验模拟官方响应与原请求预览：非流式单一 choice、正常 stop、非空 JSON 内容；业务字段为 title / summary / points，每点引用本次 evidence_id。未知 / 重复 / 空证据、工具调用、截断、字段与长度越界、无效 token 统计拒绝，错误只含固定分类。统计保留 prompt / completion / total 及成对 cache hit / miss；不猜测账单费用。

结果 mode=offline、validated=true、persisted=false，仅说明结构和引用属于本批，不能证明摘要事实正确、文字全部有证据支持或没有身份泄漏。没有接到现有 Mock 作业库，也不改变摘录保留机制。聊天中的指令作为不可信数据包装；提示文本不保证阻止所有模型提示注入。

## 官方依据与启用前置

2026-10-11 核验 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)、[模型与定价](https://api-docs.deepseek.com/quick_start/pricing/) 和 [Open Platform 服务条款](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html)。当前使用托管 API 契约，未采用 SDK 或复制模型权重；模型开源许可不能代替服务条款。JSON 模式需要提示中包含 json 和输出例子，官方仍提示可能空响应或截断，因此本机再次校验。

真实调用前：用户设定费用上限，密钥通过本机忽略配置提供；先明确合成样本调用方案和每次请求限额，再实施网络超时 / 重试 / 使用量与预算控制；真实正文还需人工复核候选去身份质量。当前仅供应商方向已定，不开启真实数据、周期外发或计费请求。

后续更新：用户已明确月费用上限 20 元（DEC-032），TASK-025 新增独立受控合成单次入口，见 deepseek_usage.md；本模块 build_request / validate_response 仍保持离线，不读取密钥或发送。CLI provider-preview 额外输出 request_sha256 供单次调用绑定复核内容；原模块 envelope 不含该复核元数据。

## 网页请求复核（TASK-027）

运行合成 demo 或 serve，在“摘要预览”中点击“查看 DeepSeek 候选请求”，查看候选文字、SHA256、模型 / 输出上限和可展开的完整 JSON。网页不读取密钥、不调用 AI，也不保存请求。切换群、关键词、主题、归组或视图会使旧请求失效并清空。

网页默认 Flash / 1024，当前群全部命中段构造一个请求，不按上方小时 / 日分桶。后续实际 CLI 调用必须使用同一数据范围和关键词规则；自定义网页关键词不会保存为 CLI 规则文件。候选阻断或无命中不生成请求。当前只是合成数据复核能力，不保证未知身份已经移除。
