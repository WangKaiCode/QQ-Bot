# TASK-004 离线使用说明

2026-10-10。已实现的 synthetic.v1 命令行工具，样本全部为合成数据。无需安装第三方包；本次实测 Python 3.14.7 / SQLite 3.50.4，建议复现使用同版本。Python 构建须带 sqlite3 模块。

在项目根目录 PowerShell 执行：

```powershell
python qq_bot.py --db data/demo.db import tests/fixtures/synthetic.jsonl --allow tests/fixtures/allowlist.json
python qq_bot.py --db data/demo.db query --account demo-account --group demo-group
python qq_bot.py --db data/demo.db query --account demo-account --group demo-group --keyword 网络
python qq_bot.py --db data/demo.db batches
```

导入输出包含批次 `id`，查询结果包含消息 `id`。将实际 ID 填入下列命令（不含尖括号）：

```powershell
python qq_bot.py --db data/demo.db report <批次ID>
python qq_bot.py --db data/demo.db show <消息ID>
python qq_bot.py --db data/demo.db context <消息ID> --radius 2
```

`show` 输出原始 JSON 的解析对象、来源、文本及按输入顺序排列的段；原始行文字另保存在数据库 raw_json（去除行末换行）。`context` 输出同账号同群的 before / message / after。转发节点属于父消息中的来源，不据此认定其原群或提供 QQ 跳转。

查询必须指定账号和群；关键词按字面子串匹配（区分大小写），支持转发文本及显式 link 段的 URL；不抓取链接。`--since` 包含下界、`--until` 不包含上界，均为带偏移的 ISO 时间，例如 `2026-10-10T10:00:00+08:00`。排序为 UTC 毫秒时间、消息上游 ID 的字典序；`--limit` 默认 50、范围 1–200，`--offset` 默认 0。上下文半径默认 10、范围 0–50。CLI JSON 输出为 UTF-8。

白名单是非空 JSON 数组，元素具有字符串 account_id、group_id。必须同时匹配这两个字段才允许正文入库。示例见 tests/fixtures/allowlist.json。禁止使用真实聊天或凭据作为本增量的测试输入。

## 如何读导入报告

- seen = inserted + matched + failed + excluded，仅统计已经提交的行。
- inserted 为新增消息；matched 为同合成身份且载荷相同的重导。不同 ID 即使同人、同秒、同文本也保留。
- 同身份内容变化为 IDENTITY_CONFLICT；旧消息保留，冲突的白名单内合法原始观测留在该批次，报告只显示行号、错误码和字段路径。
- failed 可包含 INVALID_JSON、INVALID_FIELD、INVALID_TIMESTAMP、UNSUPPORTED_SCHEMA、DEPTH_LIMIT、SEGMENT_LIMIT、LINE_LIMIT；不回显失败正文。非白名单 excluded 仅保存行号与状态，不保存其原文、哈希或来源字段。
- completed 表示本文件所有行处理结束且无错误；completed_with_errors 表示行错误可定位且其他行已处理。均不证明 QQ 采集完整。
- 默认每 200 行一次事务；消息、段、观测与 committed_line 同时提交。存储 / 读文件异常会回滚当前事务，批次尽可能记为 interrupted；硬退出或状态写入失败可能留下 running。通过 batches 查找批次，再用 report 查看已提交位置。重新导入完整文件即可恢复，创建新批次、匹配已提交消息；不会自动改写旧批次。

退出码：0 正常完成；1 导入完成但有行错误；2 参数 / 存储 / 文件异常或导入中断（stderr 返回安全错误码，中断含批次 ID）。非法命令参数由 argparse 返回 2。输入应保持不变；检测到导入期间字节变化则中断，之前已提交的块仍保留，需使用稳定输入重导并核对冲突。

## 验证与当前边界

```powershell
python -m unittest discover -s tests -v
python tests/benchmark_offline.py
```

验证记录见 [task004_validation.md](task004_validation.md)。数据库及演示数据位于被 Git 忽略的 data/；合成 fixture 才进入版本库。工具只有本机离线能力，不是 QCE / OneBot 适配器，不提供网页、QQ / AI 接入、媒体下载或客户端跳转。单行上限 1 MiB（含换行）、转发递归层级 16、规范化段 / 节点约 10,000；超限报错，不静默截断。未知段保留原文并标记 unsupported。

原文 expires_at 按消息时间加 3 天记录，但到期清理和查询过期状态尚未实现（TASK-008）；历史合成样本仍可查看。当前不得用于真实数据留存。用户导入文件只读，不由应用删除。摘要保留 10 天将在摘要与清理任务实现；收藏例外仍未决定。
