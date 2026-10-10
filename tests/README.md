# 测试目录

当前没有可执行测试。第一阶段仅创建项目文档与基础目录。

2026-10-10 更新：上述为第一阶段历史；TASK-004 新增 test_offline.py（10 项自动化测试）、fixtures/ 合成输入与 benchmark_offline.py（种子 410 的 30,000 条回放）。执行 `python -m unittest discover -s tests -v` 和 `python tests/benchmark_offline.py`，证据见 [task004_validation.md](../docs/task004_validation.md)。测试不接入真实服务。

TASK-013 新增 test_web.py（5 项 HTTP 回归），总计 15 项测试；prepare_browser_qa.py 提供独立合成浏览器边界样本。运行与证据见 [task013_validation.md](../docs/task013_validation.md)。浏览器检查目前为实际手动操作，不宣称端到端自动化套件。

下一阶段重点验证：

- 重复导入、跨账号 ID 冲突与乱序处理。
- 转发层级、图片段保留、解析失败可见性。
- 写入失败不推进检查点、断线恢复与补录边界。
- 摘要证据关联、来源上下文与过期状态。
- AI 外发字段约束、分析重试与通知幂等。
- 保留策略及收藏例外。
- 约 30,000 条 / 天的回放和独立峰值负载。

优先使用合成或脱敏样本。真实聊天、QQ 凭据与 API 密钥不作为提交到仓库的测试材料。测试的目标是验证业务行为与故障恢复，而非复刻实现细节。
