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

## 使用项目虚拟环境（推荐）

系统自带的 `python3` 若未装依赖，会报 `No module named 'dotenv'`。请优先：

```bash
source .venv/bin/activate
# 或直接用： .venv/bin/python3 qq-ai-bridge/bridge.py
```

## 准备配置

在启动前，至少确认下面这些信息已经可用：

- NapCat HTTP 地址
- NapCat token
- owner / 允许的私聊用户
- reminder / scheduler 配置
- （可选）OpenClaw / OCAI 命令路径

如果仓库中有 `.env.example`，建议先复制成 `~/.candace/qq-ai-bridge.env`（推荐，不会进 Git）或 `qq-ai-bridge/.local.env`，再填入真实 Key。`qq-ai-bridge/.env` 仅可放非敏感默认项；模板见 `qq-ai-bridge/.env.example`。

## Agents SDK provider probes

Phase A 的私聊 canary 可以使用 official OpenAI、第三方 Responses proxy，或
OpenAI-compatible Chat Completions provider。底层模型名写着 GPT-5.5/5.6
不代表网关一定转发 hosted tools；必须先验证实际 API surface。

先保持：

```dotenv
AGENT_RUNTIME_ENABLED=false
OPENAI_HOSTED_WEB_SEARCH_ENABLED=false
OPENAI_COMPUTER_USE_ENABLED=false
```

然后从仓库根目录运行：

```bash
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --text
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --web-search --accept-billable-probe
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --computer --accept-billable-probe
```

退出码含义：

- `0`: 该探针通过。
- `2`: 配置有效，但该 capability 不支持或未接受 billable hosted-tool probe。
- `1`: 配置、鉴权、网络或上游错误。

只有 exact endpoint/model 的 `--web-search` 返回真实 `web_search_call` 和引用时，
才启用 `OPENAI_HOSTED_WEB_SEARCH_ENABLED=true`。只有 `--computer` 返回
`computer_call` 时，才考虑启用 built-in computer flag；Phase A 的实际动作仍通过本地
PC Agent 安全边界执行。第三方网关的账单和数据处理由该网关控制。ChatGPT Plus 不能作为
这些脚本的 API 凭据。

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
