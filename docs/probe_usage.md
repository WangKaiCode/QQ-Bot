# 受限本机接收层

2026-10-11，TASK-019，REQ-001、003、015、018。这是本项目的内存探针接收层，独立于只读合成信息流；不安装或启动 NapCat / QQ，不获取历史、发送消息或外发 AI。验证只使用合成 HTTP 事件。用户已批准的真实试验仍需组件许可依据及第三方日志 / 缓存期限核验；当前不能把这份说明当作真实试验已开始。

## 配置与生命周期

实际账号、一个白名单群、随机 token 只在本机 `data/probe-config.json` 填写，data/ 已被 Git 忽略；不要在聊天或 Git 提交配置。配置字段为 account、allowed_groups（必须恰好一个群）、token（32–256 UTF-8 字节），可选 duration_seconds / max_messages / max_bytes / max_retained_bytes；默认及上限见 onebot_usage.md。未知字段、超过 64 KiB 文件、空配置及无效期限拒绝启动。

本地配置准备好且实际试验前置满足后，可运行 `python qq_bot.py probe-serve --config data/probe-config.json --port 8766`。监听固定 127.0.0.1，命令仅打印本机地址；Ctrl+C 或期限结束会停止监听并清空内存。不创建来源库 / 作业库，不记录访问日志；操作系统交换文件、NapCat 自身缓存 / 日志和用户复制文件不在这项清空承诺内。

目前没有配置编辑界面、登录流程、转发拉取、历史补齐或消息详情 HTTP 接口。代码的低层列表上限不改变一个测试群的授权。

## 接口

所有请求必须使用 `Authorization: Bearer <本地token>`；不支持 URL token，不提供 CORS。Host 只接受 localhost / 127.0.0.1 和当前端口；提供 Origin 时必须是当前本机 origin，cross-site 请求拒绝。响应禁缓存，不包含 token、账号 / 群 / 来源 ID、昵称、正文或 local_id。

- POST /events：Content-Type 为 application/json，必须有唯一且合法 Content-Length；不支持 Transfer-Encoding，超限或超时拒绝。只处理 OneBot 群消息事件；范围外内容不进入规范段解析。
- GET /status：返回计数、缺口及关闭状态；不返回正文或身份。
- 接纳 / 重复 / 冲突 / 排除返回 200；鉴权失败 401、格式错误 400、超限 413、关闭 410。错误只有静态码；未知路径 404、未支持方法 405。

读取正文有固定总时限，持续小块发送不能续期；并发处理最多 8 个连接，额外连接直接关闭，不返回 HTTP 503。停止时关闭跟踪的活动连接。限额不保证低配机器性能，也不是恶意本机进程隔离；本机受限开发接收层未作生产部署、真实高负荷或公网认证验证。验证见 task019_validation.md。
