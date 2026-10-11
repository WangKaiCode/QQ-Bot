# TASK-019 本机接收层验证

2026-10-11，REQ-001、003、015、018。仅合成 HTTP 请求与合成配置，未安装 / 启动 NapCat、登录 QQ、真实采集、外发 AI 或部署。甲方尚未验收。

`python -m unittest discover -s tests -v`：100 项通过，8.054 秒。新增接收层 12 项与 CLI 配置 3 项：Bearer 与 Host / Origin / cross-site 门禁、重复头 / 长度 / Transfer-Encoding 拒绝、内容类型 / 格式 / 限额、范围排除 / 重复 / 冲突、响应无正文身份、无详情端点、关闭与固定期限、配置未知字段 / 恰好一个群 / 64 KiB 限制 / 极深 JSON / 不创建库；输出 BrokenPipe 异常仍执行关闭。

实际 slow-drip 测试每 0.015 秒继续发小块数据，0.08 秒固定总读体时限仍返回 400；8 个连接占满后第 9 个被关闭，释放后 status 恢复 200。早期测试在活动 serve_forever 前关闭监听产生 WinError 10038；修正为先 shutdown / join 再 close，最终运行无后台异常。停止时关闭跟踪的活动 socket。

独立审查实际核验 1 秒会话：服务线程结束、端口拒绝新连接、Probe.closed=true。主 Agent 实际运行 `probe-serve`，使用忽略目录 data/ 中仅合成的 1 秒配置和 8774 端口：仅打印本机 URL，退出码 0，无 token / 账号 / 配置路径输出。真实配置未创建或索取。

git diff --check 通过（行尾规范化提示不属于内容错误）。没有生产吞吐、公网认证、恶意本机隔离或第三方缓存期限实测。当前受限接收层可用不等于 NapCat 许可 / 兼容性或真实采集已完成；前置见 real_ingestion_proposal.md。
