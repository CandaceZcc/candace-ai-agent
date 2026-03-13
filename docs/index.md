# Candace AI Agent 文档

这是 `Candace AI Agent` 的独立文档站。

这个项目运行在 Ubuntu 实体机上，核心结构是：

- QQ webhook / NapCat 消息接入
- Python bot 服务
- skill routing
- scheduler / reminder 主动消息
- 本地 JSON 持久化

这里的文档主要负责两件事：

1. 提供完整安装与运行说明
2. 记录常见问题、日志排查和当前架构

如果你只是想快速了解项目，可以先看仓库根目录的 `README.md`。  
如果你准备在本地部署、修改配置、排查 webhook 或 scheduler 问题，建议从安装文档开始看。

## 文档导航

- `Installation`
  - Ubuntu 环境准备
  - NapCat 配置
  - OpenClaw / OCAI 接入
  - 机器人启动
- `Troubleshooting`
  - 常见错误排查
  - 调试日志说明
- `Architecture`
  - 当前系统设计概览

## 当前项目状态

这个项目仍然处于持续开发阶段。

现阶段重点是把下面这些基础能力做稳：

- 消息链路
- reminder / scheduler
- skill 路由
- 主动发送消息
- 自动化骨架

后续再继续扩展 Playwright 浏览器自动化、更多本地 skill，以及基于 ESP32 的桌宠 / 桌面陪伴方向。
