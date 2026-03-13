# Run the Bot

本页说明如何启动当前仓库中的机器人服务，并做一轮最小验证。

## 进入项目目录

```bash
cd /path/to/candace-ai-agent
```

如果你使用虚拟环境，先激活：

```bash
source .venv/bin/activate
```

## 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

## 准备配置

在启动前，至少确认下面这些信息已经可用：

- NapCat HTTP 地址
- NapCat token
- owner / 允许的私聊用户
- reminder / scheduler 配置
- （可选）OpenClaw / OCAI 命令路径

如果仓库中有 `.env.example`，建议先复制成 `.env` 再修改。

## 启动 QQ bridge

```bash
cd qq-ai-bridge
python3 bridge.py
```

如果启动成功，通常会看到类似日志：

```text
[SYSTEM] bridge 启动中
[SCHEDULER] started
[SCHEDULER] tick now=...
```

## 最小验证步骤

建议按下面顺序测试：

### 1. 验证 webhook

给机器人发一条 QQ 私聊消息，确认终端出现：

```text
[WEBHOOK] 收到请求: ...
[WEBHOOK] message_type: private
```

### 2. 验证普通回复

发送一条普通私聊文本，确认机器人能正常回复。

### 3. 验证 reminder

发送：

```text
1分钟后提醒我测试
```

正常情况下应看到：

```text
[REMINDER] added id=...
[REMINDER] firing id=...
[REMINDER] sent id=...
```

并且 QQ 私聊会在到点后收到主动提醒。

### 4. 验证结构化查询

可以继续测试：

- `提醒列表`
- `下一个提醒是什么`
- `明天有什么课或者提醒`

这些查询应该由本地逻辑回答，而不是盲目走大模型。

## 建议的启动方式

当前阶段更推荐：

- 先直接在终端前台运行
- 观察日志
- 把消息链路和 reminder 跑通

后面如果需要长期运行，再考虑：

- `tmux`
- `screen`
- `systemd`

不要一开始就把问题复杂化。
