# 项目文档入口

更新日期：2026-10-11。当前阶段：TASK-004 离线闭环、TASK-013 本机来源阅读与 TASK-014 规则 / Mock 摘要预览已实现，待甲方验收；本地 Git 管理，未上传。

| 文档 | 用途 | 维护方式 |
| --- | --- | --- |
| [project_context.md](project_context.md) | 历史背景、证据来源和访问缺口 | 新证据到达时补充，不抹去历史缺口 |
| [requirements.md](requirements.md) | 带编号的产品需求及验收草案 | 需求变化时更新；保留来源与确认状态 |
| [workflow.md](workflow.md) | 甲乙方分工、开发流程、文档维护规则 | 协作方式变化时更新 |
| [decisions.md](decisions.md) | 已确认决定、技术提案和待决策事项 | 决策产生或改变时更新 |
| [development_plan.md](development_plan.md) | 第一阶段提出的开发顺序 | 作为初始计划保留；具体推进看任务表 |
| [backlog.md](backlog.md) | 工作分解、关联需求、交付与验收 | 执行任务时维护状态 |
| [status.md](status.md) | 当前事实、已完成工作、下一步及交接入口 | 每次开发任务结束更新 |
| [changelog.md](changelog.md) | 里程碑变更记录 | 有实际交付时记录 |
| [component_review.md](component_review.md) | 官方组件核对与未验证边界 | 采用前重新核对版本并补实测 |
| [mvp_proposal.md](mvp_proposal.md) | 分期范围与甲方审阅事项 | 确认后同步需求 / 决策 |
| [architecture.md](architecture.md) | 技术架构提案 | 选型或实现变化时维护 |
| [data_model.md](data_model.md) | 数据身份、实体与清理契约草案 | schema 变更同步维护 |
| [api.md](api.md) | 合成输入和应用接口草案 | 实现前核对，变更时更新 |
| [validation_plan.md](validation_plan.md) | 编号验收案例与实测计划 | 实施后添加结果引用 |
| [product_analysis.md](product_analysis.md) | 使用场景、产品流程与体验评审 | 乙方依据用户反馈维护 |
| [offline_usage.md](offline_usage.md) | TASK-004 实际命令、配置、报告与恢复步骤 | 随实现维护 |
| [task004_validation.md](task004_validation.md) | TASK-004 测试覆盖与合成回放基线 | 保留实测范围与结果 |
| [web_usage.md](web_usage.md) | 本机来源阅读界面启动与体验路径 | 随 TASK-013 实现及反馈维护 |
| [task013_validation.md](task013_validation.md) | 本机网页测试与实际浏览器验证 | 保留实测范围与结果 |
| [analysis_usage.md](analysis_usage.md) | 离线规则筛选、Mock 摘要预览与证据回看 | 随 TASK-014 实现维护 |
| [task014_validation.md](task014_validation.md) | 规则 / 摘录边界与浏览器检查证据 | 仅记录实际结果 |
| [retention_usage.md](retention_usage.md) | 到期范围只读检查与统计含义 | 随 TASK-015 维护 |
| [task015_validation.md](task015_validation.md) | 保留预览验证证据 | 仅实际结果 |
| [outbound_usage.md](outbound_usage.md) | 本地候选载荷检查与隐私边界 | 随 TASK-016 维护 |
| [task016_validation.md](task016_validation.md) | 载荷检查验证记录 | 仅实际结果 |

项目根目录的 [AGENTS.md](../AGENTS.md) 是后续 Codex 的开发入口规则。已有 [README.md](../README.md) 保留第一阶段说明；最新开发状态以本入口和 status.md 为准。

维护约定：背景证据、需求、决策、执行状态各有单独位置，其余文档引用它们，避免复制后产生多个不一致版本。数据库、接口、部署文档随实际设计产生，不预填不存在的实现。
