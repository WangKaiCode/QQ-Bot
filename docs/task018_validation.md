# TASK-018 离线验证

2026-10-11，REQ-001、002、003、015、018。仅离线子集已实现，未启动 HTTP / WebSocket、安装或登录 QQ / NapCat、获取历史或外发 AI。真实兼容性与第三方保留尚未验证，甲方尚未验收。

13 项 onebot 核心及 4 项回放 / CLI 测试通过：白名单先于正文解析、身份 / 时间 / 段限制、未获取媒体 / 未解决转发、CQ 字符串、鉴权、消息 / 字节预算、去重冲突、随机 epoch、计数快照、到期主动清空、异常静态响应、回放行码 / 文件限制 / 无数据库创建 / 不回显正文身份。

独立 Agent 实际复现 1 秒会话在解析耗时 1.1 秒后仍返回 accepted 的竞态；修复为规范化 / 哈希后再检查截止，确定性测试覆盖新消息与冲突分支。复审延迟解析返回 stopped / SESSION_CLOSED，内容已清空。测试 Probe 均注册 close 清理。序列化字节预算不是 Python 堆或进程内存上限，清空不是操作系统安全擦除。

实际命令 `python qq_bot.py onebot-replay tests/fixtures/onebot.synthetic.jsonl --account 100001 --group 200001` 返回 accepted=1、excluded=1、forward_unresolved，不打印 token / 身份 / 正文。只允许显式合成包装；声明不能替代真实数据脱敏。返回统计注明清空前快照及已清空状态。

完整套件 `python -m unittest discover -s tests -v`：85 项通过，7.702 秒；git diff --check 通过（仅行尾规范化提示）。本记录不把合成回放当作真实采集成功。
