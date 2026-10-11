# 组件核对与能力边界

核对日期：2026-10-10（Asia/Shanghai）。关联 TASK-002、REQ-001、002、003、010、014、015。

本次只核对官方仓库、发布页与文档，没有安装、登录、调用接口或运行性能测试。“官方列出”不等于“本项目实测通过”。以下版本是本次发布页观察值，不是安装锁定版本；安装前还需核对与 QQ 客户端及插件的兼容组合。

## 候选对比

| 候选 | 观察到的版本 | 官方资料支持的定位 | 本项目建议 |
| --- | --- | --- | --- |
| NapCatQQ | [v4.18.37](https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.37) | NTQQ 接入；接口表列出群消息历史、单消息及合并转发获取，HTTP 与正 / 反向 WS；Windows / Linux 安装说明 | 首选接入验证对象，运行许可与具体版本组合核对后采用 |
| qq-chat-exporter（QCE） | [v6.3.2](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2) | 本地群 / 私聊导出、结构化格式与媒体；Windows / Linux 包；可作为 NapCat 插件 | 历史导入候选，先读脱敏导出样本，避免同时启动重复 QQ 接入实例 |
| SnowLuma | [v1.14.22](https://github.com/SnowLuma/SnowLuma/releases/tag/v1.14.22) | 官方列出 OneBot v11、HTTP / WS、多账号与媒体；该发布页列出 Windows x64、Linux x64 / arm64 | 备选；不复制其代码，采用前核对运行条款 |
| napcat-msg-store | 未确认正式发行版本 | README 描述 WS → SQLite → HTTP 查询；README 声明 MIT，但本次文件列表没有独立 LICENSE | 仅参考职责划分，许可文件与实现未核实，不直接复用代码 |

证据：[NapCat 接口表](https://napneko.github.io/develop/api)、[NapCat 上报事件](https://napneko.github.io/develop/event)、[NapCat 安装说明](https://napneko.github.io/guide/boot/Shell)、[QCE 仓库](https://github.com/shuakami/qq-chat-exporter)、[SnowLuma 仓库](https://github.com/SnowLuma/SnowLuma)、[msg-store 仓库](https://github.com/keenlin/napcat-msg-store)。QCE 的许可证为 [GPL-3.0](https://github.com/shuakami/qq-chat-exporter/blob/master/LICENSE)。

## 不能承诺的能力

- **历史与完整性**：QCE 指南说明普通导出读取当前客户端已同步到本机的记录；实验性漫游仅支持私聊，不能套用于本项目指定群需求。任务成功也不能证明腾讯服务端保存完整。[QCE 指南](https://raw.githubusercontent.com/shuakami/qq-chat-exporter/master/docs/guide.md)、[漫游接口边界](https://shuakami.github.io/qq-chat-exporter/docs/roaming-api.html)
- **消息 ID**：NapCat 的较旧资源设计文档描述非连续 ID 与 LRU 时效。本次没有证实其约 5000 条缓存描述仍适用于最新版本，不能作为当前固定容量。消息 ID 不应按连续整数补洞，实时接收后要在本应用持久化；跨重启 / 导出 ID 对应关系必须实测。[ID 设计说明](https://napneko.github.io/onebot/napcat)
- **精确跳转**：本次已读取页面没有给出可靠的“跳到 QQ 某条消息”客户端契约。需求保留，先交付应用内原文与上下文，客户端跳转单独验证；该替代交付方式需要甲方确认。
- **转发与图片**：获取接口存在不证明全部嵌套可恢复；过期资源、访问权限、未知段和解析失败都要有状态。OCR 是否运行、准确率和费用尚未测定。
- **资源容量**：Windows / Linux 有发行包不意味着 2C2G40G 可承载 QQ、OCR、本地模型和分析；本阶段没有服务器实测。

## 许可核对对选型的影响

[NapCat LICENSE](https://github.com/NapNeko/NapCatQQ/blob/main/LICENSE) 为自定义 Limited Redistribution License，含使用、修改、分发和商业限制；README 也强调不得未经授权基于其代码开发。它不能视作 MIT 类代码素材。

[SnowLuma LICENSE](https://github.com/SnowLuma/SnowLuma/blob/main/LICENSE) 是源码可见非商业许可，含商业、衍生项目与公开修改版限制；发行包还有 EULA / 隐私条款。独立进程或协议边界是工程隔离方式，不能据此推定所有许可问题已解决。

建议自行编写应用的数据和分析层，通过明确接口或导出文件对接；安装、分发、收费或对外发布前核对所用版本的授权条件。本次不联系作者、不接受发行包协议、不复制或安装其代码。此处记录组件文本对选型的影响，未给出许可适用的法律裁定。

## 自研应用栈建议及依据

- Python：便于实现离线解析与分析适配；具体版本、依赖锁定在环境核对后记录。
- SQLite：单机、短期数据、低并发写入起步；官方指出同一时刻只有一个 writer，设计应使用短事务并控制写竞争。[适用范围](https://www.sqlite.org/whentouse.html)
- WAL：建议本地磁盘使用；不能把数据库放网络共享并让多机访问。[WAL 说明](https://www.sqlite.org/wal.html)
- FastAPI：作为后续 Web API 框架候选，官方提供请求验证与 OpenAPI 能力；离线原型不必先引入 Web 依赖。[官方文档](https://fastapi.tiangolo.com/)
- 搜索：第一版明确支持中文子串 / 关键词检索；不把默认 FTS5 当成中文分词方案。官方列出的 unicode61 默认按连续 token 处理，trigram 为三字符子串；短关键词另需回退与实测。[FTS5](https://www.sqlite.org/fts5.html)

以上仍是乙方提案，不是甲方已批准架构。SQLite 运行时版本、FTS5 编译支持和依赖兼容待本地环境检查。

## 实测清单与资料缺口

正式接入前记录 QQ / NapCat / QCE 版本、平台架构、配置和样本；验证重启前后 ID、断线历史窗口、转发深度、资源失效、撤回事件、查询超时与数据保留范围。结果进入验收记录，不能用 README 的宣传性完整性描述替代实测。

本次 NapCat Apifox 页面超时；SnowLuma 动作入口初次读取失败，后续官网 API 总览可读取，但未取得群历史与合并转发的逐项参数。QCE 通过仓库指南补充核对，但仍未取得版本对应的正式导出 JSON 样本。具体历史分页参数、跨工具 ID 映射与运行许可适用范围均未锁定。

2026-10-11 后续精确版本调查已补齐 NapCat v4.18.37 README / commit / LICENSE blob、release 资产 hash 及 Echo 专属授权回复，详见 [真实采集提案最新证据](real_ingestion_proposal.md)。本项目许可适用尚未明确，不以别的项目答复或无登录启动测试代替本项目授权 / 真实兼容；未安装或发消息。
