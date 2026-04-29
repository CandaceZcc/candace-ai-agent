# VoCat 功能现状报告

更新时间：2026-04-29

## 1. 当前定位

当前 VoCat 在本项目中的定位是“语音与表情终端”，不是独立完整操作系统入口。

设备侧负责：

- 唤醒、收音、播放语音
- 显示 EAF 表情
- 把部分语音请求转发给本机 `qq-ai-bridge`
- 从本机轮询待播报或待切换表情的命令

本机侧负责：

- 接收 VoCat webhook
- 决定回复文本和表情
- 调用 QQ / 日程 / Markdown / 本地 agent 等能力
- 把文本回复同步发送到 QQ
- 下发 TTS 和 expression 队列命令给 VoCat

整体路线是“设备做终端，本机做大脑”。

## 2. 已完成能力

### 2.1 设备启动与运行

当前固件基于火山引擎 Embedded Kit 的 `VolcRTCDemo` 改造。

已确认：

- SD 卡可被设备挂载到 `/sdcard`
- LCD 初始化成功
- EAF 资源分区挂载成功
- 麦克风采集链路启动
- Wi-Fi 可连接本地网络
- 火山引擎会话可建立，串口出现 `Volc Engine connected`
- USB Serial/JTAG 可用于刷机和抓日志

之前 `fs_sdcard` 曾是启动风险点，现在已按可选设备处理，不再把 SD 卡失败作为整个板级初始化的硬失败条件。

### 2.2 VoCat 到本机 bridge

设备端可以把语音或 function call 请求 POST 到：

```text
POST /vocat/webhook
```

bridge 返回统一 JSON：

```json
{
  "ok": true,
  "handled": true,
  "reply": "回复文本",
  "expression": "happy",
  "source": "local_expression"
}
```

固件会解析：

- `reply`：用于本机语音播报
- `expression`：用于切换 EAF 表情

### 2.3 本机 bridge 到 VoCat

bridge 提供命令队列，设备定时轮询：

```text
GET  /vocat/poll
POST /vocat/ack
GET  /vocat/queue
POST /vocat/queue
```

支持两类命令：

- `tts`：让设备播报文本，可附带 expression
- `expression`：只切换表情

队列命令被设备取走后会 ack，bridge 日志会记录 deliver 和 ack。

### 2.4 QQ 联动

当前已支持：

- QQ 私聊 `#说 <文本>`：下发 VoCat 播报
- QQ 私聊 `#表情 <id/name>`：下发 VoCat 表情
- VoCat 语音请求可由 bridge 处理后同步文本回复到 QQ
- QQ 私聊回复可以进入 VoCat TTS 队列，由设备播报

语音侧可识别 QQ 发送意图，例如：

```text
发 QQ：测试表情
给 QQ 发消息：我到了
```

### 2.5 表情控制

当前支持的逻辑表情：

| 表情 | 语义 | EAF 映射 |
| --- | --- | --- |
| `happy` | 开心 / 正常 | `MMAP_EAF_HAPPY_EAF` |
| `angry` | 生气 | `MMAP_EAF_EMOTION_ANGRY_284_126_EAF` |
| `blink` | 眨眼 / idle | `MMAP_EAF_EMOTION_BLINK1_284_126_EAF` |
| `dizzy` | 思考 / 处理中 | `MMAP_EAF_EMOTION_DIZZY_284_126_EAF` |
| `sleep` | 睡觉 / 晚安 | `MMAP_EAF_EMOTION_SLEEP_284_126_EAF` |

已实现的状态策略：

- local fallback POST 前：切到 `dizzy`
- bridge 返回成功：优先使用 JSON 里的 `expression`
- bridge 没有返回 expression：固件按文本做兜底选择
- bridge 请求失败：切到 `angry`，播报“本机服务没有连接”
- TTS 播放后：延迟 8 秒回到 `blink`

设备串口会输出：

```text
[VOCAT_EXPR] current=
[VOCAT_EXPR] target=
[VOCAT_EXPR] source=
[VOCAT_EXPR] apply ok/failed
```

### 2.6 语音表情命令

当前已支持自然语音：

```text
测试表情
切换开心
切换生气
切换生气表情
换成眨眼
调成睡觉
切到思考
```

修复过的问题：

- `切换生气` 原来不带“表情”二字，会落到 Kimi 普通对话，现在会直接走本地表情逻辑。
- `测试表情` 原来会被普通对话解释为“表情符号”，现在会作为本地表情测试命令处理。
- 普通回复里出现“生气”等枚举词时，不再优先用 reply 误选 angry，而是优先按 query 或显式 expression 决定。

### 2.7 Markdown 仓库语音入口

bridge 支持读取本地仓库 Markdown。

默认根目录来自 `VOCAT_MD_ROOT`，当前指向本仓库：

```text
/home/cancade/candace-ai-agent
```

可用语音或 webhook 请求：

```text
读取 README.md
查看 docs/install/vocat-no-sd.md
总结 xxx.md
```

实现上会限制读取范围必须在 `VOCAT_MD_ROOT` 内，避免越界读任意文件。

### 2.8 本地技能

VoCat 请求进入 bridge 后，当前处理顺序大致为：

1. 表情控制
2. Markdown 读取
3. 天气
4. 今明日程 / 课表
5. 本地 agent 后台任务
6. QQ 转发
7. Kimi 普通文本回复

这意味着 VoCat 已经不是单纯语音玩具，而是可以作为本地仓库和本机能力的语音入口。

## 3. 实现方式

### 3.1 bridge 侧入口

文件：

```text
qq-ai-bridge/apps/qq_ai_bridge/adapters/webhook.py
```

新增或使用的路由：

```text
GET  /vocat/webhook
POST /vocat/webhook
GET  /vocat/poll
POST /vocat/ack
GET  /vocat/queue
POST /vocat/queue
```

`/vocat/webhook` 负责接收设备请求，并调用 `process_vocat_query()`。

`/vocat/poll`、`/vocat/ack`、`/vocat/queue` 负责设备拉取本机下发命令。

### 3.2 bridge 侧请求分流

文件：

```text
qq-ai-bridge/apps/qq_ai_bridge/services/vocat_service.py
```

核心函数：

- `_extract_query()`：从 `query/text/asr_text/message/content` 中提取文本
- `_detect_expression_query()`：识别表情控制语音
- `_extract_md_path()`：识别 Markdown 路径
- `_read_markdown_file()`：读取并截断 Markdown 内容
- `_handle_local_skill_sync()`：优先处理本地技能
- `_with_expression()`：为所有回复补齐 expression
- `process_vocat_query()`：统一处理 VoCat 请求

实现策略：

- 本地可处理的请求优先本地处理
- 不能本地处理的请求再交给 Kimi
- 每个结果都补齐 `expression`
- 需要时把 VoCat 的 reply 同步发到 QQ

### 3.3 bridge 侧命令队列

文件：

```text
qq-ai-bridge/apps/qq_ai_bridge/services/vocat_command_queue.py
```

核心函数：

- `enqueue_vocat_tts()`
- `enqueue_vocat_expression()`
- `poll_vocat_command()`
- `ack_vocat_command()`
- `get_vocat_queue_status()`
- `normalize_vocat_expression()`
- `select_vocat_expression()`

队列是进程内内存队列，适合当前单机开发环境。

命令结构示例：

```json
{
  "id": "command-id",
  "type": "tts",
  "text": "测试播报",
  "expression": "happy",
  "source": "manual_queue",
  "device_name": "",
  "delivery_count": 0,
  "created_at": "2026-04-29T00:00:00+00:00"
}
```

### 3.4 固件侧本地语音兜底

文件：

```text
/home/cancade/ConversationalAI-Embedded-Kit-2.0/application/service/local_logic_service/src/local_logic_service.c
```

核心逻辑：

- 识别 QQ 发送类语音
- 识别表情控制类语音
- 识别 Markdown / 仓库 / 文件读取类语音
- 识别日程 / 课表类语音
- 过滤设备自己刚播报出来的助手回复，避免自触发循环

当识别到应由本机处理的字幕时，调用：

```c
function_call_service_send_qq_bridge_text(query)
```

这会进入 function call service 的本机 bridge POST 流程。

### 3.5 固件侧 bridge 通信与表情

文件：

```text
/home/cancade/ConversationalAI-Embedded-Kit-2.0/application/service/function_call_service/src/volc_function_call_service.c
```

核心能力：

- POST `/vocat/webhook`
- 解析 bridge 返回的 `reply`
- 解析 bridge 返回的 `expression`
- 调用 EAF 表情切换
- 把 reply 送入火山 TTS
- 定时轮询 `/vocat/poll`
- 对已处理命令 POST `/vocat/ack`

表情应用函数：

```c
__apply_bridge_expression(expression, source)
```

它会：

1. 把字符串 expression 映射为 EAF index
2. 调用 `volc_hal_display_set_content()`
3. 写入 `[VOCAT_EXPR]` 日志
4. 成功后记录当前表情 index

### 3.6 固件侧配置

文件：

```text
/home/cancade/ConversationalAI-Embedded-Kit-2.0/examples/high_quality_solution/espressif/main/Kconfig.projbuild
```

关键配置：

```text
VOCAT_BRIDGE_WEBHOOK_URL
VOCAT_BRIDGE_WEBHOOK_TOKEN
VOCAT_BRIDGE_POLL_URL
VOCAT_BRIDGE_ACK_URL
VOCAT_BRIDGE_POLL_INTERVAL_MS
```

当前默认指向本机局域网 bridge：

```text
http://192.168.110.31:5000/vocat/webhook
http://192.168.110.31:5000/vocat/poll
http://192.168.110.31:5000/vocat/ack
```

换网络或本机 IP 变化时，需要同步更新并重刷固件。

## 4. 关键链路

### 4.1 语音输入到本机回复

```text
用户说话
  -> VoCat 唤醒 / ASR / 字幕
  -> local_logic_service 判断是否本机处理
  -> function_call_service POST /vocat/webhook
  -> qq-ai-bridge 处理 query
  -> 返回 reply + expression
  -> 固件切 expression
  -> 固件播报 reply
  -> 播报后回 blink
```

### 4.2 QQ 输入到设备播报

```text
QQ 私聊 / webhook
  -> qq-ai-bridge 处理消息
  -> enqueue_vocat_tts 或 enqueue_vocat_expression
  -> VoCat GET /vocat/poll
  -> 固件执行 TTS / expression
  -> VoCat POST /vocat/ack
```

### 4.3 表情控制

```text
语音“切换生气”
  -> 固件识别为 expression command
  -> POST /vocat/webhook
  -> bridge 返回 expression=angry
  -> 固件映射 angry -> EAF index 2
  -> volc_hal_display_set_content()
```

## 5. 验证方法

### 5.1 bridge 状态

```bash
curl -sS http://127.0.0.1:5000/vocat/webhook | python3 -m json.tool
```

### 5.2 webhook 表情测试

```bash
curl -sS -X POST http://127.0.0.1:5000/vocat/webhook \
  -H 'Content-Type: application/json' \
  -d '{"query":"切换生气"}' | python3 -m json.tool
```

期望：

```json
{
  "expression": "angry",
  "source": "local_expression"
}
```

### 5.3 队列表情测试

```bash
curl -sS -X POST http://127.0.0.1:5000/vocat/queue \
  -H 'Content-Type: application/json' \
  -d '{"type":"expression","expression":"angry"}' | python3 -m json.tool
```

### 5.4 队列状态

```bash
curl -sS http://127.0.0.1:5000/vocat/queue | python3 -m json.tool
```

### 5.5 Markdown 测试

```bash
curl -sS -X POST http://127.0.0.1:5000/vocat/webhook \
  -H 'Content-Type: application/json' \
  -d '{"query":"读取 README.md"}' | python3 -m json.tool
```

### 5.6 串口日志

```bash
cd /home/cancade/esp/esp-idf-v5.5
source ./export.sh
cd /home/cancade/ConversationalAI-Embedded-Kit-2.0/examples/high_quality_solution/espressif
idf.py -p /dev/ttyACM0 monitor
```

重点看：

```text
Got IP
Volc Engine connected
Forwarding local subtitle to QQ bridge
[VOCAT_EXPR] target=
[VOCAT_EXPR] source=
[VOCAT_EXPR] apply ok
bridge command ack
```

## 6. 编译和刷机

```bash
cd /home/cancade/esp/esp-idf-v5.5
source ./export.sh

cd /home/cancade/ConversationalAI-Embedded-Kit-2.0/examples/high_quality_solution/espressif
idf.py -p /dev/ttyACM0 flash
```

如需同时看日志：

```bash
idf.py -p /dev/ttyACM0 monitor
```

## 7. 当前已验证结果

已验证：

- 固件可编译
- 固件可刷写
- 设备可启动
- SD 卡可挂载
- Wi-Fi 可连接
- 火山引擎可连接
- bridge 可启动并监听 `0.0.0.0:5000`
- `/vocat/webhook` 可返回 `reply + expression`
- `/vocat/queue` 可下发 TTS 和 expression
- 设备可 poll 队列并 ack
- `happy`、`blink`、`dizzy`、`angry` 均能进入 EAF apply 流程
- `切换生气` 已被修复为本地表情命令

串口验证过：

```text
[VOCAT_EXPR] target=2 expression=angry
[VOCAT_EXPR] source=manual_queue
[VOCAT_EXPR] apply ok
```

## 8. 已知限制

### 8.1 触屏不是操作系统入口

当前固件是表情 + 语音引擎应用，不是带桌面菜单的触屏操作系统。触屏无法“进入系统”不是点击方式问题，而是当前应用没有实现这类 UI 路由。

### 8.2 表情视觉效果依赖 EAF 资源

固件已经调用 EAF 并返回 `apply ok`，但最终肉眼看到的变化取决于 EAF 资源本身、显示尺寸和动画状态。

日志中偶尔出现：

```text
gfx_obj: Set size for animation or image is not allowed
eaf: Unknown encoding type: FF
```

目前这些日志没有阻断 `apply ok`，但如果后续仍出现“日志成功但肉眼变化不明显”，需要继续检查 EAF 资源内容和显示层刷新逻辑。

### 8.3 bridge 队列是内存队列

当前队列随 bridge 进程重启而丢失。对开发阶段足够，但长期应改为持久化队列或至少落盘状态。

### 8.4 本机 IP 仍是固件配置

设备端 bridge URL 写在 ESP-IDF 配置里。本机 IP 变化后，设备无法自动发现 bridge，需要改配置并重刷，或后续做 mDNS / 配网页面配置。

### 8.5 自触发仍需保守处理

设备播报时，麦克风可能听见自己的 TTS。当前已过滤部分助手回复和收紧“测试表情”规则，但后续新增语音命令时仍要避免过宽匹配。

## 9. 下一步建议

优先级建议：

1. 增加设备端 bridge URL 动态配置，避免本机 IP 变化就重刷。
2. 给 EAF 表情增加明确可见的测试资源或测试页面，排除“调用成功但视觉不明显”的问题。
3. 将 VoCat command queue 改为轻量持久化，避免 bridge 重启丢队列。
4. 增加 `/vocat/status`，记录最近一次设备 poll、ack、expression、TTS、webhook。
5. 将 Markdown 读取扩展为摘要模式，而不是直接读前 1200 字。
6. 明确触屏产品形态：如果要触屏 UI，需要单独实现 LVGL 菜单，而不是等待现有固件“进入系统”。
