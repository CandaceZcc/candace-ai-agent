# Candace AI Agent

一个运行在 Ubuntu 实体机上的 QQ 个人助手 / 机器人项目。

这个仓库目前围绕 **QQ webhook + Python bot + skill routing + scheduler/reminder** 持续建设。它的目标不是只做一个“接大模型聊天”的机器人，而是逐步发展成一个可扩展的个人自动化助手：先把消息链路、主动提醒、技能路由和基础自动化骨架打稳，再继续向浏览器自动化、桌面陪伴设备、更多本地 skill 扩展。

---

## 项目简介

当前系统主要通过 NapCat webhook 接收 QQ 消息，由本地 Python 服务完成：

- 私聊 / 群聊消息解析
- skill 路由与分发
- 定时提醒与主动消息发送
- 本地 JSON 持久化
- 按需接入 OpenClaw / OCAI 等模型工作流

从定位上看，这更像一个**正在持续建设中的个人项目**，而不是已经完整成型的平台。后续很适合继续接入浏览器自动化、桌宠、ESP32 设备和更多自动化能力。

---

## 当前功能

目前已经实现或已有稳定雏形的能力包括：

- QQ 私聊消息接收与回复
- QQ 群聊按规则触发回复
- Skill 路由机制，不同类型消息走不同处理逻辑
- 定时提醒与主动私聊消息发送
- reminders / scheduler state 的本地 JSON 持久化
- 基础日志与调试输出
- 面向自动化扩展的项目结构骨架

当前阶段的重点仍然是先把消息链路、提醒系统、技能路由和自动化基础打稳。

---

## 项目结构概览

仓库目前可以大致理解为：

```text
candace-ai-agent/
├── qq-ai-bridge/      # QQ webhook bridge、技能路由、提醒与主动消息
├── pc-agent/          # 桌面自动化 / PC 侧能力的实验与扩展方向
├── docs/              # 独立文档网站内容（MkDocs）
├── mkdocs.yml         # MkDocs 配置
├── requirements.txt   # Python 依赖
└── README.md
```

其中：

- `qq-ai-bridge/` 是当前最核心的一部分
- `pc-agent/` 主要承接桌面自动化相关方向
- `docs/` 用来放完整安装与排错文档

---

## 未来计划

### 1. Playwright 浏览器自动化

后续希望把浏览器自动化能力更系统地建立在 Playwright 上，而不是长期依赖 OCR + 坐标点击。这样更适合：

- 保留登录态
- 执行稳定的网页流程
- 为学校系统、网页助手、内容抓取等能力打基础

### 2. 基于 ESP32 的桌宠 / 桌面陪伴设备

另一个重要方向，是把这个项目从“聊天机器人”延伸到硬件端，例如：

- 基于 ESP32 的小型桌宠设备
- 结合屏幕、网络、状态展示与消息推送
- 让这个项目逐步变成桌面陪伴式个人助手

---

## 简要安装步骤

这里只保留非常简短的说明，完整安装过程请看独立文档站。

1. 克隆仓库并进入目录
2. 安装 Python 依赖
3. 配置 NapCat webhook 与项目环境变量 / 配置文件
4. 按需接入 OpenClaw / OCAI
5. 启动 `qq-ai-bridge` 服务

一个最简启动过程通常类似：

```bash
git clone <your-repo-url>
cd candace-ai-agent
python3 -m pip install -r requirements.txt
cd qq-ai-bridge
python3 bridge.py
```

在此之前，请先确保 QQ / NapCat / webhook 已经准备好。

---

## 完整安装文档链接

📖 完整安装指南：  
https://example.com/docs

