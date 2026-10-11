# GitHub 仓库保护与执行状态

2026-10-11，TASK-028 / REQ-018。用户明确要求尝试批准 PR #2 CI，并设置合理仓库保护（DEC-033）。此要求不授权自动合并 PR、增加外部账号权限或关闭 Copilot 工作流审批。

## 实际核验

GitHub connector 返回用户对 WangKaiCode/QQ-Bot 为 admin=true；但集成读取 main/protection 返回 403 Resource not accessible by integration，工具集中无 ruleset 创建 / 更新或工作流 approve 工具。main 分支查询返回 protected=false；仓库 rulesets=[]。本机没有 gh CLI，内置浏览器未登录。已打开登录页并请求用户本人登录，不接收聊天密码 / Token。Actions run 38142169913 仍 action_required。以上是执行权限阻塞，不是用户没有授权或仓库配置已完成。

## 已备好配置

`.github/rulesets/main-baseline.json`：active、仅 main、无 bypass。禁止删除和强推，要求 PR 并解决讨论；允许现有 merge / squash / rebase。审批人数暂为零，保持人工阅读后由仓库所有者决定合并：主要单人维护时硬性第二人审批会阻塞本人创建的 PR。没有关闭工作流运行审批或增加机器人绕过权限。

`.github/rulesets/main-ci.json`：当前 disabled，尚不可视为 CI 保护已开启。等 PR #2 已审查工作流被批准、实际两个 job 成功且确认精确检查名称后，选择 GitHub Actions 作为来源并改为 active；要求 ubuntu-latest / Python 3.14 与 windows-latest / Python 3.14 两项，且必须与 main 最新内容一起测试。先不强制不存在的检查，避免当前 main 没有 CI workflow 时形成无法合并的门槛。工作流合并仍需甲方明确指令。

`.github/rulesets/release-tags.json`：active、仅 v* 标签、无 bypass，禁止删除与覆盖；允许创建新标签。

三个 JSON 是待导入的配置，不是 GitHub 运行配置，尚未应用。登录后优先核验现有设置，若仍为空再创建，防止重复 ruleset；保存后通过 API / 界面读回核验。分支保护生效后，本地变更仍可提交，但远端采用 codex/* 分支与 PR，不再直接推 main。

## 仓库安全设置待核验

在仓库界面检查免费可用的 Secret Protection / push protection 和 Dependabot alerts，启用未开启项；遇到付费确认不提交。保留 Actions 默认 token 只读、现有工作流 contents:read、Copilot 运行人工批准。当前没有确认这些仓库级选项的状态，不把它们列为已启用；不安装新应用、发放管理 Token 或更改仓库公开范围。

官方依据：[Rulesets API](https://docs.github.com/en/rest/repos/rules)、[分支规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)、[Push protection](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/prevent-future-leaks/enable-push-protection)、[Copilot 工作流审批](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/configuring-agent-settings)。JSON 结构 / main 与 v* 范围 / 无绕过 / CI disabled 已本机检查，git diff --check 通过；没有修改应用代码，不重复运行 174 项测试，也未声称远端保护或 CI 已通过。
