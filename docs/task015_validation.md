# TASK-015 验证记录

日期：2026-10-11。关联 TASK-008 / REQ-012、018。范围为合成数据只读保留影响预览，包含核心、CLI、GET API 与网页；不执行任何删除，不宣称生产保留策略已生效。Windows 本机，沿用 Python 3.14.7 / SQLite 3.50.4。

## 自动化检查

核心负责 Agent 实际执行 `python -m unittest discover -s tests -p test_retention.py -v`：10 项通过，0.204 秒，退出 0。

| 验证范围 | 实际结果 |
| --- | --- |
| 到期边界与期限依据 | 截止前 1 毫秒不计入、边界时刻计入；修改 expires_at 后按该字段判断，原文仍 available |
| 账号 / 群隔离与重复观测 | 同 external_id 的其他账号 / 群不计入；重复导入不增加逻辑消息，观测与原始观测均按行计数 |
| 分页 | 稳定排序、最后页及越过末页的 next_offset / 空列表符合契约 |
| 已不可用状态 | expired / withdrawn 单独计入状态分布，不进入 available 到期候选 |
| 无 raw_json 观测 | due_observations 包含该行，due_raw_observations 仅计非 NULL |
| 空库与当前时点 | 全部计数为 0、无候选；默认时点显示 +08:00，策略与未执行标记明确 |
| 只读与隐私输出 | readonly 连接重复结果一致；数据库文件字节与 total_changes 未改变；候选无正文、发送者或资源路径 |
| 非合成与异常恢复 | 仅指定 scope 中非合成来源拒绝；异常后回滚且连接可继续查询；越界存储日期不遗留事务 |
| 非法输入与调用事务 | 缺失 scope、非整数 / 越界分页、非整数 / 越界时间拒绝；已有调用事务拒绝并保持调用事务 |

主 Agent 汇报已实际执行 HTTP 回归：7 项通过（3.874 秒，退出 0）。覆盖新增保留接口与既有接口 / 安全边界；具体运行证据由主 Agent 维护。本文不会把该结果解释为自动删除、实际磁盘回收或真实 QQ 数据保障。

## CLI 与实际浏览器证据

主 Agent 执行 retention-preview --account demo-account --group demo-tech --as-of 2099-01-01T00:00:00+08:00 --limit 1，退出 0；实际库 total=6、due=6、segments=15、observations=32、raw_observations=32，next_offset=1。该库多次重导，所以观测数高于逻辑消息数，不是去重失败。

实际浏览器 8769：默认当前时间无到期候选；未来时间显示 6 条候选；sample-03 可回看嵌套原文和上下文；非法时间只报错、不显示旧候选。390×844 下 clientWidth=scrollWidth=375，四个导航按钮可用；恢复默认视口，error/warn 日志为空。[实际截图](assets/retention-preview.jpg)。

本增量新增 10 核心 + 1 HTTP 测试；已有 31 项测试维持回归。未声称测试覆盖真实删除或磁盘回收。

所有样本为合成内容。测试通过表示此次只读查询契约和隔离边界可复现，不表示甲方已验收，不覆盖真实来源标记可信度、托管副本删除、备份期限、收藏例外或生产性能。
