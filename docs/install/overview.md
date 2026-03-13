# Installation Overview

本页给出一个完整安装流程的总览，适合先通读一遍，再按顺序执行。

## 你需要准备的内容

在开始之前，建议先确认：

- 一台 Ubuntu 实体机
- 已安装 Python 3
- 能正常运行 NapCat 并完成 QQ 登录
- 允许本地服务监听端口
- 具备基础的 Linux 命令行操作能力

如果你计划保留当前聊天链路，还需要准备：

- 本地可调用的 OpenClaw / OCAI 环境

注意：OpenClaw 只是项目的一部分，不是整个系统的核心。  
项目核心仍然是 **QQ webhook + Python bot + skill routing + scheduler/reminder**。

## 推荐安装顺序

1. 准备 Ubuntu 运行环境
2. 安装并配置 NapCat
3. 克隆本仓库并安装 Python 依赖
4. 配置 webhook、环境变量与本地数据目录
5. （可选）接入 OpenClaw / OCAI
6. 启动机器人服务
7. 用私聊和 reminder 场景做验证

## 最小验证目标

安装完成后，至少建议验证下面几件事：

- NapCat webhook 能把 QQ 私聊消息送到 Python 服务
- Python 服务能通过 NapCat API 发回私聊消息
- reminder 能成功添加并到点主动发消息
- 群聊 / 私聊路由都能正常工作

如果某一步不通，不要急着继续叠功能，优先把链路打通。

接下来建议按文档顺序继续看：

- `Ubuntu Setup`
- `NapCat Setup`
- `OpenClaw Setup`
- `Run the Bot`
