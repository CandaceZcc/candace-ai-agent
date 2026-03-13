# System Design

这份文档只描述当前仓库的大致设计，不把它写成一个已经完全稳定的大平台。

## 当前系统核心

项目目前最核心的链路是：

```text
QQ / NapCat
    ↓ webhook
Python bot service
    ↓
message parsing / skill routing
    ↓
chat skill / reminder skill / other skills
    ↓
NapCat HTTP API / 本地模型工作流 / 本地 JSON
```

从工程上看，项目现在最重要的部分是：

- QQ webhook 接入
- Python bot 服务
- skill routing
- scheduler / reminder
- 本地 JSON 持久化

## 私聊与群聊

当前系统已经区分：

- 私聊消息处理
- 群聊消息处理

这意味着后续可以继续分别扩展：

- 私聊里的个人助手行为
- 群聊里的规则化回复和触发策略

## Skill Routing

这个项目的一个核心思路，是不要把所有消息都直接丢给大模型。

而是先做本地路由：

- reminder / schedule 查询，优先程序直答
- 普通自由对话，再走聊天链路
- 文件 / 图片 / 自动化等消息，可交给独立 skill

这样能减少：

- 不必要的 token 消耗
- 错误回答
- reminder / schedule 这类结构化信息被模型“瞎猜”

## Reminder / Scheduler

项目当前已经有主动提醒能力，链路大致是：

```text
QQ 私聊添加提醒
    ↓
本地 reminder store(JSON)
    ↓
scheduler 后台线程
    ↓
NapCat API 主动发私聊
```

这部分能力很重要，因为它说明项目已经不只是“被动聊天机器人”。

## 本地持久化

当前主要使用本地 JSON 文件来保存：

- reminders
- scheduler state
- schedule
- 其他轻量配置 / 状态

这对个人项目足够简单直接，也便于调试。  
如果后续复杂度继续上升，再考虑数据库并不迟。

## 后续演进方向

当前设计已经为后面几条路线预留了空间：

### 1. Playwright 浏览器自动化

用于更稳定的网页登录、流程执行、内容抓取和状态保留。

### 2. 桌面自动化

用于和实体机上的本地环境联动，承接更强的自动化能力。

### 3. ESP32 桌宠 / 硬件端

把提醒、状态、消息和陪伴能力延伸到桌面设备侧。

## 当前阶段的重点

现阶段并不是把功能堆得越多越好，而是先把以下部分做稳：

- 消息链路
- skill 路由
- reminder / scheduler
- 主动消息发送
- 本地调试与日志

这些基础稳定之后，后续扩展 Playwright 和硬件能力会顺很多。
