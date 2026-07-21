# Candace AI Agent

一个跑在本地机器上的个人 QQ 助手。

功能： 基于openclaw和python的 个人助手 + 扮演群聊群友 + 轻量agent + 乐鑫VoCat喵伴终端

---

## What is this

- QQ 通-> NapCat -> 本地抓取日志
- 本地 Python 服务接 webhook  
- 根据内容做分流  
- 能本地处理的直接处理  
- 不确定的再交给模型  


QQ → NapCat → webhook → bridge → routing → QQ / 设备 / 任务


---

## What it can do

实践功能：

### QQ

- 私聊收发  
- 群聊按规则触发（白名单 / 艾特 / 全局）  
- 每个群可以单独配置行为  

### routing / skill

- 判断消息类型 -> 决定路径  
- 天气 / 提醒 / 课程这类直接本地处理  
- 其他交给模型（Kimi / OCAI）  

### reminder / scheduler

- 私聊里添加提醒  
- 到时间自动发 QQ  
- 每日固定任务（睡觉 / 明日课程）  

### 个性化校园邮件

- 只读 IMAP，每 5 分钟增量检查
- 本地规则与无工具模型共同筛选相关邮件
- 高价值邮件分级 QQ 推送，12:30 / 20:30 生成最近 24 小时增量摘要
- owner 私聊反馈可学习、可撤销；不通过 edu 域名猜测老师或机构
- 自动化开关默认关闭，支持 24 小时 shadow canary


### VoCat（ESP32）

设备侧作为终端：

- 语音输入 → 本机处理  
- 本机结果 → QQ + 设备播报  
- 表情（EAF）+ TTS  
- 本机命令队列（poll / ack）  

使用方式：

对设备说话 → 本机处理 → QQ收到 + 设备播报  
QQ发命令 → 设备直接执行  

### 日志 / 调试

- 所有行为写入 bridge.log  
- 群聊 / 私聊 / vocat / scheduler / skill 可区分  
- web控制台： 'http://127.0.0.1:5000/admin/groups'： 包含日志中心、群聊规则配置、VoCat调试、私聊调试

---

## Project layout

candace-ai-agent/
├── qq-ai-bridge/      核心逻辑：webhook / routing / scheduler  
├── pc-agent/          桌面自动化相关
├── docs/              文档（MkDocs）  
├── requirements.txt  
└── README.md  

---

## How it works

私聊：

QQ 私聊  
→ webhook  
→ routing  
→ 本地逻辑 / 模型  
→ 回复 QQ  

群聊：

群消息  
→ 判断是否触发  
→ routing  
→ 回复 / 表情 / 忽略  

VoCat：

语音  
→ ASR  
→ 本机 webhook  
→ bridge 处理  
→ 返回文本 + 表情  
→ 播报 + 切表情  

scheduler：

定时任务  
→ 本地触发  
→ 发 QQ  
→ 可同步设备播报  

---

## Quick start

最短启动路径：

git clone <repo>  
cd candace-ai-agent  
python3 -m pip install -r requirements.txt  

runai


前提：

- NapCat 已配置 webhook  
- QQ 已登录  
- 环境变量已设置  

---

## Docs

📖 完整安装指南： 

https://candacezcc.github.io/candace-ai-agent/

Phase A owner-private Agents SDK canary:

- `docs/install/openai-agents-sdk.md`
- `docs/install/qq-email-agent.md`

---
