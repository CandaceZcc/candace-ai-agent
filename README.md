# Candace AI Agent

QQ、NapCat、VoCat、PC Agent 和一台 Ubuntu 主机拼出来的个人助手项目。

它现在已经能收 QQ 消息、跑本地技能、主动提醒、看图读文件、控制 VoCat 播报和表情，也有一个本地 Web 控制台可以看状态和日志。整体还在边用边修，很多地方保留了开发期的直白日志，排查起来比较方便。

## 现在能做什么

### QQ AI Bridge

核心服务在 `qq-ai-bridge/`，入口是 Flask / Waitress：

```text
qq-ai-bridge/bridge.py
```

它负责接收 NapCat webhook，然后按消息内容分流：

- 私聊回复
- 群聊触发回复
- 图片理解
- 文件理解
- 天气查询
- 提醒和日程
- 桌面 / 浏览器 agent 指令
- VoCat 语音入口
- 表情回应和 reaction 跟随

群聊里可以按群配置决定是否启用、是否全局触发、是否只在艾特时触发，也可以单独开关 Vision、风格学习、消息采样和日志静音。

### Web 控制台

bridge 自带一个本地控制台，不需要额外端口：

```text
http://127.0.0.1:5000/admin
```

目前有这些页面：

- `/admin`：总览，显示 bridge、NapCat、VoCat、队列和消息计数
- `/admin/groups`：群聊配置
- `/admin/logs`：日志中心，支持 category / level 多选过滤
- `/admin/vocat`：VoCat 状态和手动测试
- `/admin/private`：私聊调试
- `/admin/system`：只读配置状态

日志中心读的是固定文件：

```text
/home/cancade/candace-ai-agent/.runtime/logs/bridge.log
```

前端不会直接读文件，走后端 API；返回前会把 token、api key、Authorization 这类内容打码。

### VoCat

VoCat 现在接进了 bridge，主要当语音和表情终端用。

设备侧负责唤醒、收音、播报和显示 EAF 表情；本机 bridge 负责理解请求、调用 QQ / 日程 / Markdown / 本地技能，再把结果回给设备。

当前接口：

```text
POST /vocat/webhook
GET  /vocat/poll
POST /vocat/ack
GET  /vocat/queue
POST /vocat/queue
GET  /vocat/status
```

已支持：

- 语音请求转到本机 bridge
- bridge 返回 `reply` 和 `expression`
- 设备轮询本机 TTS / 表情命令
- QQ 私聊 `#说 <文本>` 让设备播报
- QQ 私聊 `#表情 <happy|angry|blink|dizzy|sleep>` 切设备表情
- VoCat 语音请求同步文本回复到 QQ
- 读取仓库内 Markdown，例如 `读取 README.md`

当前表情名：

```text
happy
angry
blink
dizzy
sleep
```

VoCat 相关细节见：

```text
docs/vocat-function-report.md
```

### Scheduler / Reminder

本地 scheduler 会随 bridge 启动。

目前可以：

- QQ 私聊添加提醒
- 到点后主动发 QQ 私聊
- 查询提醒列表
- 查询今明日程
- 每日睡觉提醒
- 明日课程提醒
- 必要时把提醒播报到 VoCat

数据主要存在本地 JSON 里，方便直接看、直接改、直接备份。

### PC Agent

`pc-agent/` 是本机桌面自动化侧的服务，默认给 bridge 调用。

它主要承接：

- 截屏
- OCR
- 鼠标键盘动作
- 桌面任务执行
- 后续浏览器自动化

默认地址：

```text
http://127.0.0.1:5050
```

## 项目目录

```text
candace-ai-agent/
├── qq-ai-bridge/              # QQ bridge、NapCat、skills、VoCat、控制台
│   ├── apps/qq_ai_bridge/
│   │   ├── adapters/          # webhook、NapCat、admin UI、VoCat controller
│   │   ├── services/          # chat、vision、file、scheduler、VoCat queue 等
│   │   ├── skills/            # chat / weather / reminder / schedule / vision 等
│   │   ├── config/
│   │   └── templates/
│   ├── data/                  # bridge 运行数据
│   ├── tests/
│   └── bridge.py
├── pc-agent/                  # 本机桌面自动化服务
├── docs/                      # 安装、排错、架构、VoCat 报告
├── data/                      # 项目级数据目录
├── .runtime/logs/             # bridge / agent 日志
├── requirements.txt
└── README.md
```

## 启动

先进入仓库：

```bash
cd /home/cancade/candace-ai-agent
source .venv/bin/activate
```

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

启动 QQ bridge：

```bash
python3 -u qq-ai-bridge/bridge.py
```

启动后打开：

```text
http://127.0.0.1:5000/admin
```

如果需要 PC Agent：

```bash
cd /home/cancade/candace-ai-agent/pc-agent
source .venv/bin/activate
python3 agent.py
```

## 配置

配置模板在：

```text
qq-ai-bridge/.env.example
```

推荐把真实密钥放在：

```text
~/.candace/qq-ai-bridge.env
```

或者：

```text
qq-ai-bridge/.local.env
```

bridge 启动时会按顺序读取：

```text
qq-ai-bridge/.env
.env
qq-ai-bridge/.local.env
~/.candace/qq-ai-bridge.env
```

常用配置项：

- `NAPCAT_HTTP`
- `NAPCAT_TOKEN`
- `OWNER_QQ`
- `VISION_API_URL`
- `VISION_API_KEY`
- `KIMI_API_KEY`
- `VOCAT_WEBHOOK_TOKEN`
- `VOCAT_TRUSTED_DEVICE_IPS`
- `PC_BROWSER_AGENT_URL`

控制台里只显示 set / unset，不会把 key 直接铺出来。

## 常用接口

### 管理后台

```text
GET /admin
GET /admin/groups
GET /admin/logs
GET /admin/vocat
GET /admin/api/summary
GET /admin/api/logs
GET /admin/api/vocat/status
```

日志过滤示例：

```bash
curl -sS 'http://127.0.0.1:5000/admin/api/logs?category=group,vocat&level=info,warning&limit=100' | python3 -m json.tool
```

### VoCat

```text
GET  /vocat/webhook
POST /vocat/webhook
GET  /vocat/poll
POST /vocat/ack
GET  /vocat/queue
POST /vocat/queue
GET  /vocat/status
```

测试播报：

```bash
curl -sS -X POST http://127.0.0.1:5000/vocat/queue \
  -H 'Content-Type: application/json' \
  -d '{"type":"tts","text":"测试播报","expression":"happy"}' | python3 -m json.tool
```

测试表情：

```bash
curl -sS -X POST http://127.0.0.1:5000/vocat/queue \
  -H 'Content-Type: application/json' \
  -d '{"type":"expression","expression":"blink"}' | python3 -m json.tool
```

## 日志

常看这几个文件：

```text
.runtime/logs/bridge.log
.runtime/logs/agent.log
.runtime/logs/openmaic.log
```

常见前缀：

```text
[SYSTEM]
[WEBHOOK]
[GROUP_CHAT]
[PRIVATE_CHAT]
[SEND_GROUP]
[SEND_PRIVATE]
[SKILL]
[VISION]
[REACTION]
[SCHEDULER]
[VOCAT]
[VOCAT_EXPR]
[OCAI]
```

排查时从 webhook 开始看，再看 skill 命中、NapCat 返回、VoCat poll / ack。日志写得比较直，哪里没接上通常能顺着前缀找到。

## 测试

运行全部单测：

```bash
source .venv/bin/activate
python -m unittest discover -s qq-ai-bridge/tests -p 'test_*.py'
```

只看控制台和 VoCat 队列相关测试：

```bash
python -m unittest qq-ai-bridge/tests/test_admin_console.py qq-ai-bridge/tests/test_vocat_command_queue.py
```

## 当前开发重点

近期主要在这几块上继续推进：

- QQ AI Bridge 控制台
- VoCat 语音、表情和本机队列
- 群聊触发和 reaction 行为
- 图片 / 文件理解
- reminder / schedule
- pc-agent 和浏览器自动化

这个仓库更像一个每天都在长一点的本机工作台。能跑的东西先接起来，出问题就看日志，能拆出去的逻辑再慢慢拆。

完整文档站：

```text
https://candacezcc.github.io/candace-ai-agent/
```
