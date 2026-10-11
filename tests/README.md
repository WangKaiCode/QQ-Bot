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

TASK-014 增量（2026-10-11）：test_analysis.py 覆盖规则、时间、隔离、证据拒绝、只读及输入版本；test_web.py 新增预览 HTTP 回归。实际最终数量与结果见 [task014_validation.md](../docs/task014_validation.md)。

## GitHub Actions CI（TASK-022）

仓库在 `.github/workflows/tests.yml` 提供跨平台标准库回归，触发条件为 `push` 与 `pull_request`：

- 运行矩阵：`ubuntu-latest`、`windows-latest` + Python `3.14`
- 执行命令：
  - `python -m unittest discover -s tests -v`
  - `python qq_bot.py --help`
  - `git diff --check <显式提交范围>`

`git diff --check` 的范围按事件显式计算：`pull_request` 使用 `base...head`，`push` 使用 `before..sha`；首次推送（`before` 全零）或 `before` 不在当前历史时，回退为 `EMPTY_TREE..HEAD`，避免在干净 checkout 上误判。

Action 固定版本依据（均为官方 release commit SHA）：

- `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683`（tag `v4.2.2`，官方 release：<https://github.com/actions/checkout/releases/tag/v4.2.2>）
- `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97`（tag `v7.0.0`，官方 release：<https://github.com/actions/setup-python/releases/tag/v7.0.0>）

两者仓库 `LICENSE` 均为 MIT；固定完整 SHA 的目的是减少 tag 漂移风险并保留可审计性。该流程不安装额外依赖、不使用仓库 secrets、不使用 `pull_request_target`，且同分支新提交会取消进行中的同工作流运行。
