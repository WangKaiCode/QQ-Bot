# 源代码目录

当前只建立目录，尚无可运行代码，语言与框架未锁定。

2026-10-10 更新：上述为第一阶段历史；TASK-004 已建立 qq_radar 包，domain / storage / ingestion / cli 提供离线闭环。入口为根目录 qq_bot.py，使用 Python 标准库与 SQLite。后续模块按实际增量建立，运行见 [offline_usage.md](../docs/offline_usage.md)。

TASK-013 增量：demo.py 合成阅读样本、server.py 本机只读服务、web/ 原生界面；运行见 [web_usage.md](../docs/web_usage.md)。生产 API、分析 worker 与真实 adapter 未实现。

后续建议按职责拆分：采集 / 导入、标准化、存储、完整性记录、筛选 / 分析、任务调度、来源查询、Web 展示和保留策略。先验证离线样本闭环，再接真实 QQ 与 AI。

具体模块目录和依赖在技术方案确认后创建，不在本阶段预装。

TASK-014 增量（2026-10-11）：analysis.py / topics.json 提供只读规则 / 窗口 / Mock 摘录与证据校验，CLI analyze 与网页摘要预览复用；没有持久 worker 或真实 provider。运行见 [analysis_usage.md](../docs/analysis_usage.md)。
