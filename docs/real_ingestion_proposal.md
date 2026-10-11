# 真实接入试验提案（待甲方确认）

> 最新状态：2026-10-11 用户已批准本机受限试验，仍须通过许可与兼容前置检查；见文末“授权与本机前置检查更新”。标题及初始提案保留为历史记录。

2026-10-11（Asia/Shanghai）。关联 TASK-005、REQ-001、002、003、010、012、015 及 OPEN-002 / 006。本文件是可评审方案，不是安装、登录、真实数据读取或自动删除授权。此次仅读取项目文档与官方网页，没有安装或运行任何 QQ 组件。

建议下一真实接入试验采用本机 Windows、独立测试账号和一个指定测试群，先接收人为准备的测试消息，不发送消息、不启用外部 AI。授权后仍应先完成接入适配、真实数据存储隔离与三天保留执行的具体方案；现有 synthetic.v1 库和本机演示服务不能直接切换为真实数据服务。

## 方案与备选

| 路线 | 可验证的软件效果 | 代价与边界 |
| --- | --- | --- |
| 推荐：NapCat Shell + 自研 OneBot 11 接收适配 | 消息进入应用后阅读、去重、转发解析；随后测试短时断线和原文回查 | 需要安装组件、用户本机扫码登录、版本兼容核验；必须独立实现来源 namespace / epoch，不能套用 synthetic 身份规则 |
| 备选：用户用 QCE 手动导出指定测试群时间范围，再由应用离线适配 | 先确认真实文件格式、来源阅读和导入错误，可暂不建设常驻接收 | 手动操作、不保证实时或群历史完整；QCE 的完整模式依赖 QQ / NapCat，仍有组件、登录和许可边界；不直接读取现有主账号全部聊天 |

优先试验独立测试账号，避免首先把日常主账号及全部群暴露给协议端。若没有可用测试账号，可以选择先处理用户主动导出的脱敏文件；这需要明确该文件授权范围，不能把文件存在视为读取许可。QCE 同账号不与另一个独立 Shell 实例同时启动；若后续采用 NapCat 插件包，需核对该组合，不额外重复登录。

## 2026-10-11 官方证据核对

版本是当日页面观察值，尚未锁定安装组合；发布版本与当前在线文档可能不同。安装前重新核对并记录下载文件哈希、QQ build、架构和配置。

| 核对项 | 当日证据与限制 |
| --- | --- |
| NapCat 发布 | latest 跳转至 [v4.18.37](https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.37)。发布说明列 QQ build 40768–53644 的核验范围，但明确没有 QQ 登录测试；不能据此证明所有 Windows QQ 组合兼容。资产列表加载失败，未下载核验安装包 |
| Windows 条件 | [官方 Shell 指南](https://napneko.github.io/guide/boot/Shell)：手动方式先安装 QQ、解压 NapCat.Shell.zip，再使用 launcher.bat（Windows 10 对应 launcher-win10.bat）；一键包面向 Windows amd64、无需预装 QQ。实际系统与客户端架构尚未检查，不擅自安装升级 QQ |
| 本机服务配置 | [官方配置指南](https://napneko.github.io/config/basic) 的 WebUI 与正向 WS 示例监听 0.0.0.0，并提供 token / messagePostFormat 配置。试验拟改为 127.0.0.1、启用独立 Token、array 消息段、关闭 debug 原始日志；绑定及认证须实测，不使用默认示例直接上线 |
| 接收接口 | [兼容表](https://napneko.github.io/develop/api) 列 HTTP / 正反向 WS；[事件表](https://napneko.github.io/develop/event) 列群消息、心跳、连接与群撤回。事件表标示一年以上未编辑，是能力线索，不是当前发布完整保证 |
| 消息与转发结构 | [官方事件字段](https://napneko.github.io/onebot/event) 包含 message_id、user_id、message / raw_message 及群字段；[forward 段定义](https://napneko.github.io/onebot/segment) 的 data.id 为转发引用，content 仅在解析内容时提供。适配器必须区别父消息 ID 与转发资源 ID，缺少内容可显示待获取状态 |
| 获取详情 | [get_msg](https://napcat.apifox.cn/226656707e0) 示例以 message_id 查询；[get_forward_msg](https://napcat.apifox.cn/226656712e0) 示例以字符串 message_id 查询并返回 data.messages。两页标记 2026-07-08 更新，未实测嵌套响应。查询转发属于读取 QQ 数据，只能用于白名单父消息；不能任意查询群外资源 |
| 群历史 | 兼容表列 get_group_msg_history；本次 [具体参数页](https://napcat.apifox.cn/226657401e0) 读取超时，不能锁定游标、页大小或历史可达范围。断线补齐必须版本实测，不能按消息 ID 连续性补洞 |
| NapCat 许可 | [官方 LICENSE](https://raw.githubusercontent.com/NapNeko/NapCatQQ/main/LICENSE) 为 Limited Redistribution License，限制未经许可使用 / 修改 / 分发代码及商业用途；[官方 README](https://github.com/NapNeko/NapCatQQ) 提示混合许可及不得未经授权基于代码开发。协议隔离不等于许可已解决；不复制、修改或随本项目分发组件。采用前按所用版本核验运行许可适用性，有不明之处先澄清，用户选择不能代替作者授予权利 |
| QCE 发布与条件 | [v6.3.2](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2) 为当日 latest。页面包装表称安装器 Windows 7+，系统要求节写 Windows 10/11 x64，有表述差异；本项目按 Windows 10/11 x64 核验，不保证 Windows 7。其 QQ 推荐 build 不替代 NapCat 当前组合验证 |
| QCE 导出与许可 | [官方指南](https://raw.githubusercontent.com/shuakami/qq-chat-exporter/master/docs/guide.md) 说明普通导出限客户端已同步本机记录，实验漫游限私聊；支持指定会话、格式和时间范围。现有导出文件的独立浏览模式不用登录，导出新记录的完整模式需要登录。QCE 自身 [GPL-3.0 LICENSE](https://raw.githubusercontent.com/shuakami/qq-chat-exporter/master/LICENSE) 不取消包内其他组件许可；本项目暂不复制或分发其代码 |

以上只来自项目官方仓库、文档站及官方链接的 Apifox 页面。本轮合并转发 / 详情参数访问成功，补充了 component_review.md 先前的部分访问缺口；群历史参数、版本对应完整响应、ID 跨重启稳定性、嵌套转发与资源失效仍未验证。

## 授权后验证顺序

1. 乙方先完成离线 OneBot / QCE 合成适配契约与测试，保留未知段、错误原因、批次和来源身份；明确 schema 迁移 / 独立测试库方案，不把真实输入伪装为 synthetic.v1。
2. 在用户指定 Windows 主机记录架构与 QQ 状态，固定官方组件版本，核验许可与资产哈希。用户本人完成扫码和账号登录；账号、群白名单与 Token 仅本地填写到忽略目录中的配置，Git 与聊天都不存凭据。安装不会自动授权关闭或修改已有日常 QQ。
3. 验证 WebUI / WS 仅绑定本机、错误 Token 拒绝；先接空流，再由用户在已授权测试群手动发少量标记文本。应用不调用 send_*、群管理、凭据读取、自动好友 / 入群或快速操作 API。
4. 入库前检查 self_id 与白名单 group_id；私聊和其他群事件立即丢弃正文，只保留不含原文的排除计数。协议端可能看到该登录账号其他事件，所以账号本身也必须在授权内。只允许 get_status / get_version_info / get_login_info，以及为白名单消息定位的 get_msg / get_forward_msg；历史读取在限定窗口的下一验证阶段启用。
5. 对照人工标记序列，验证重复、同文不同 ID、重启后身份稳定性、嵌套转发、图片引用与未知段；首轮不下载媒体、不做 OCR。单次连接成功不写“完整采集”。
6. 测短断线与重连，记录缺口；群历史参数明确后再进行限定窗口补齐，不自动全量历史拉取。不可恢复则显示 partial / unknown 和具体失败原因。
7. 真实内容启用前必须另有可评审的三天保留执行与副本清单，覆盖消息正文、段、原始观测、日志及托管副本。保留天数无需重复决策，但实际不可逆清理执行仍按 AGENTS / DEC-017 的边界确认；未完成时不开展持续真实采集。

真实测试数据不得提交 Git，不在聊天发送原始日志、二维码、Token、昵称或正文。失败报告仅含静态错误分类与脱敏版本 / 范围统计；本机查看必要原文须在已授权范围。不得通过外部 AI 分析真实试验原文，供应商与预算尚未决定。

## 失败退出与回退

许可适用性不明、登录风险提示、客户端冲突、非本机监听、未知 self_id 或群范围、写入失败时，停止新数据接收，显示原因，不自动升级、换账号或扩大白名单。转发 / 历史失败只标缺失，不发送回复、不编造内容。关闭本项目接入连接与已明确归属的测试实例，不结束不相关 QQ 进程；恢复措施先记录原状态。试验资料按批准的留存策略处理，不自行递归删除用户目录或用户导出文件。

如果正向 WS 所需 Python 依赖需要新增，乙方在实施前核对官方接口、版本和许可证并写技术决定；此方案不偷偷引入新框架。资料或真实环境限制导致实时路线不可行时，回退到合成回放，或提交 QCE 指定范围手动导出选择，不把备选自动当成已授权。

## 达到边界时只需甲方决定两项

1. **组件路线**：是否批准在本机进行 NapCat Shell 的只收消息试验（推荐，许可与兼容前置核验通过后才安装登录）；或先采用 QCE 指定范围手动导出；也可继续纯合成体验。
2. **真实范围**：是否具备可授权的独立测试账号与指定测试群，以及由用户在本机填好白名单配置。首轮限该群人为准备的测试内容，不默认主账号、私聊、所有群或历史全量；实际 QQ 号与凭据无需发到聊天。

甲方选择后，乙方负责实现、测试、文档与本地提交；清理执行、真实外发费用、媒体下载范围、外部通知、云部署与 GitHub 上传不随上述两项自动获准。当前没有真实接入决定，本文件也不要求用户现在在聊天提供账号或凭据。

## 授权与本机前置检查更新（2026-10-11）

以上“待甲方确认”与“当前没有真实接入决定”保留为提案提交时状态。主 Agent 在同日转交的最新用户明确回复已批准本机受限试验：独立测试账号、一个白名单群、只收消息，许可 / 兼容 / 保留为前置条件。该回复是当前授权依据，替代上文方案尚未选择的状态；不授权聊天外发、自动发送、扩大范围、上传或部署。账号与群的本地配置尚未提供，用户批准不等于组件作者许可。

预检查仅访问 Windows 产品信息、QQ / NapCat 安装注册项、常见程序目录元数据、指定进程名称和 QQ.exe 文件版本 / PE 头。没有读聊天目录、登录状态、凭据、原始日志或二维码，没有安装、启动或真实通信。

| 项目 | 实际观察 |
| --- | --- |
| Windows | 系统 API 返回 `Microsoft Windows 10.0.22631`、OSArchitecture=X64；注册表 DisplayVersion=23H2、build=22631、UBR=6199、EditionID=ProfessionalWorkstation。注册表旧 ProductName 写 Windows 10 Pro for Workstations，与 build 命名可能不一致，因此以实际 build / 架构记录，不直接沿用旧产品名判断兼容 |
| 检查权限 | `Get-CimInstance Win32_OperatingSystem` 拒绝访问；使用只读系统 API 与注册表替代，没有提权。64 位 OS 与当前进程均确认 |
| QQ 安装 | 注册项 QQ 9.9.33.52230，Publisher=腾讯科技(深圳)有限公司；DisplayIcon 指向 `D:\NormalAPPs\QQ\QQ.exe`。该文件存在，FileVersion=9.9.33.52230、ProductVersion=9.9.33.52230-aff854e8，PE machine 0x8664（x64） |
| 运行实例 | 受限进程枚举未发现名称为 QQ / NapCat / NapCatQQ / NapCatQQ-Desktop 的进程；这是检查时可见结果，不证明系统没有其他包装启动器 |
| NapCat 安装 | 检查的卸载注册项与常见 Program Files 目录未发现安装记录；不能据此排除自定义目录中的绿色解压包，没有全盘搜索或遍历 QQ 数据目录 |
| 兼容性 | QQ build 52230 数值落在 v4.18.37 发布说明的范围内，但未登录或运行验证；该范围本身明确没有登录测试，仍不能记为兼容已通过 |

### 未经修改运行的许可门槛

本次额外读取了 [v4.18.37 固定标签 LICENSE](https://raw.githubusercontent.com/NapNeko/NapCatQQ/v4.18.37/LICENSE)，与同日 main 的相关条款一致。其第 1 条完整句为：

> Unauthorized use, reproduction, modification, or distribution of this code is prohibited without explicit permission from the main author of the NapCat repository.

该条将 use 与复制、修改、分发并列，正文没有明确写“未修改、个人非商业运行发布二进制”自动豁免。第 2 条另允许附完整许可及来源的再分发，第 4 条要求未明确权利向作者申请；[当前官方 README](https://raw.githubusercontent.com/NapNeko/NapCatQQ/main/README.md) 又提示仅消息推送用途及未经授权不得基于其代码开发。README 固定 v4.18.37 标签读取失败，本次只用 current main 辅助理解，不宣称标签全文已核验。

待澄清的具体问题是：官方发布包的下载与启动教程是否构成个人非商业、未经修改运行的明确许可，以及自研应用仅通过 OneBot 协议接收消息是否在允许范围内。协议边界与用户授权不能替代这些文本中的作者许可。此处记录的是文本适用不明，没有作法律裁定，也不自行联系作者或发送消息。

在取得作者已有公开说明或用户已有许可依据前，先完成无组件执行的离线适配、配置校验及合成事件 probe。下一真实启动门槛为许可适用性明确、版本资产核验完成、用户本机填好独立账号 / 白名单群配置与登录操作。初期若采用不保存正文的受限 probe，仍需限制内存生命周期与日志，不写真实 SQLite；这只减少持久留存前置依赖，不免除账号范围和真实读取授权。持续采集 / 保存真实原文仍需保留执行方案到位。
