# Codex 与 Copilot 协作入口

2026-10-11，TASK-021 / REQ-018。用户要求判断协同方式并继续执行；首轮采用源码 / 合成样本范围的独立 CI 任务。仓库指引与连接核验已完成，TASK-022 已指派 Copilot；具体交接证据见下文。

Codex 负责需求、任务边界、核心集成、本机验证和最终审查；Copilot 承接独立分支任务。每次一个 Copilot 任务，交接记录起始提交、允许文件、验收条件、实际测试、返回 PR。Codex 不同时修改其专属文件；Copilot 不自行合并。仅对有必要的最终变更请求一次独立审查，不启用每次推送自动重复审查。学生内含额度与 GitHub Actions 用量需先核验，不开额外计费。

官方依据：[仓库指引](https://docs.github.com/en/copilot/tutorials/cloud-agent/get-the-best-results)、[任务入口](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github)、[学生方案](https://docs.github.com/en/copilot/get-started/plans)、[额度及计费](https://docs.github.com/en/copilot/concepts/billing-and-usage/individuals/billing)。2026-10-11 核对；当前计划按 AI Credits，不沿用旧固定 premium requests 假设。用户已确认仍有包含额度且额外计费关闭；工具不能直接读取实际余额或本次消耗。

## TASK-022 可直接交接的任务

标题：为 QQ-Bot 添加 Windows / Linux 的标准库测试 CI。

目标仓库 WangKaiCode/QQ-Bot，起点为包含本任务规格和 `.github/copilot-instructions.md` 的最新 main 提交；派发时记录实际 SHA，禁止自行猜测。允许修改 `.github/workflows/tests.yml`、`tests/README.md` 中 CI 运行说明；其他文件不修改。

要求：阅读 AGENTS.md 与仓库指引；新增 Windows / Ubuntu 的 Python 3.14 测试矩阵，运行 `python -m unittest discover -s tests -v`、CLI help 和 `git diff --check`。GitHub Actions checkout / setup-python 使用前核验官方当前版本与许可、固定官方完整 commit SHA，并在 PR 记录证据；不安装新的应用依赖。使用 push / pull_request，权限 contents:read、合理超时和同分支并发取消，不使用 pull_request_target、仓库 secrets、部署或外部 AI。不要启动长期演示服务。

验收：两个系统的完整测试必须真实通过；既有 100 项基线不代表 Linux 已验证。若跨平台失败，报告具体错误与来源，不跳过测试、不削弱断言、不越界修改业务逻辑。返回一个 PR，说明触发行为、允许文件变更、实际命令 / 结果及限制。Codex 复核 CI 与测试后再集成，未经核验不宣称完成。

## 初次连接检查（历史）

GitHub 插件本机版本 0.1.12-5f7cd798dc99，Plugin Management 确认 installed / enabled。当前会话没有 GitHub Issue / PR 工具，未找到 gh 或 copilot CLI；SSH 推送可用但不能据此取得 API / Copilot 授权。内置浏览器实际访问仓库显示 Public 和 Sign in，尚未登录。不要读取 Git 凭据存储、导出浏览器 Cookie 或要求在聊天提供 Token。

用户需自行完成浏览器登录或插件账号连接；之后复核可调用通道、学生余额 / 额外计费状态及仓库 Copilot 入口，再派发 TASK-022。若工具仍未加载，保留该规格供 GitHub Agents 界面使用，不能声称已经委派。当前没有安装 CLI、创建 OAuth / PAT 或改变账号权限。

## 已派发交接（2026-10-11）

用户检查连接后，本会话 GitHub 工具可用；实际返回账号 WangKaiCode、仓库 admin / push / triage 权限。建立 [Issue #1](https://github.com/WangKaiCode/QQ-Bot/issues/1)，起点 `28a575d8b0e336b7c7f57adf1b869b7616099baa`。用户随后明确确认“仍有包含额度，额外计费已关闭”。按 [官方 API 指南](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-via-the-api) 的 `copilot-swe-agent[bot]` 指派一次；返回 assignees 含 Copilot，复读确认，并发现 Copilot 创建的 [草稿 PR #2](https://github.com/WangKaiCode/QQ-Bot/pull/2)，分支 `copilot/task-022-add-windows-linux-ci`，创建时间 2026-10-11 08:33:36 UTC。

此证据只确认任务已启动，尚无最终代码审查或两系统 CI 通过证据。不要重复指派、启动第二任务或直接合并。下次从 PR #2 的最新提交、变更文件和 checks 开始；核对仅两个允许文件、完整 SHA 固定、最小权限与测试真实结果。若 GitHub 要求人工批准首次工作流运行，依据具体工作流审查后再处理。Codex 五小时额度读数已用 97%，当前先完成文档与 Git 收尾，应用代码未改，既有 100 项测试不重复执行。
