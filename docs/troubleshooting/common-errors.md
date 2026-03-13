# Common Errors

本页记录当前项目里最常见的一些问题。  
排查时建议先看终端日志，再根据日志定位是哪一层出了问题。

## 1. NapCat webhook 收不到消息

常见现象：

- QQ 发消息后，Python 服务终端没有任何输出
- 看不到 `[WEBHOOK]` 相关日志

优先检查：

- NapCat webhook 地址是否配置正确
- Python 服务是否已经启动
- 端口是否真的在监听
- NapCat 和 Python 服务是否在同一台机器 / 是否网络可达

可以先本地确认服务监听：

```bash
ss -ltnp | grep 5000
```

## 2. 端口被占用

常见现象：

- Flask 启动时报端口占用
- NapCat 或其他本地服务无法启动

检查方式：

```bash
ss -ltnp
```

或者：

```bash
lsof -i :5000
```

确认是哪个进程占用了端口，再决定是否换端口或停止旧进程。

## 3. Python 依赖问题

常见现象：

- `ModuleNotFoundError`
- 启动后某个包导入失败

建议做法：

```bash
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

如果你没有使用虚拟环境，也要确认当前执行的 `python3` 和 `pip` 是同一套环境。

## 4. OpenClaw 插件 / OCAI 加载问题

常见现象：

- 聊天链路报错
- 日志里提示找不到命令
- OCAI 调用失败

优先检查：

- `AI_CMD` 路径是否正确
- 本地命令是否可以手动执行
- 当前用户是否有执行权限

可以直接在终端测试：

```bash
/path/to/ocai --help
```

## 5. 机器人不回复消息

要先分层判断：

### 情况 A：完全没收到 webhook

说明问题在：

- NapCat webhook
- 网络
- Python 服务监听

### 情况 B：收到 webhook，但没发出消息

说明问题可能在：

- skill 路由
- reminder / scheduler 逻辑
- NapCat HTTP API 发送
- 模型调用链路

### 情况 C：普通聊天能回，但主动提醒不发

优先看：

- `[SCHEDULER]`
- `[REMINDER]`
- reminders.json
- scheduler_state.json

## 如果你不知道问题在哪

可以直接这样做：

1. 把终端日志完整复制出来
2. 发给 AI（例如 ChatGPT / Claude）
3. 让 AI 帮你分析日志

例如，把这类日志原样贴出去：

```text
[SCHEDULER] tick now=...
[WEBHOOK] message_type=...
[SEND_PRIVATE] ...
[REMINDER] firing id=...
```

如果日志足够完整，AI 通常能很快帮你判断问题是在：

- webhook 层
- skill routing
- reminder / scheduler
- NapCat API
- 还是模型链路
