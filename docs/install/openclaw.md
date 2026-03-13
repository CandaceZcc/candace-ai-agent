# OpenClaw Setup

本页只说明如何把 OpenClaw / OCAI 接入到当前项目中。

注意：

- 这不是一个完整的 OpenClaw 教程
- OpenClaw 只是当前聊天链路中的一个组成部分
- 就算暂时不接入 OpenClaw，项目里 reminder / scheduler / webhook 的很多能力仍然可以单独工作

## 什么时候需要接入 OpenClaw

如果你希望下面这些能力正常工作，就需要准备本地可调用的 OpenClaw / OCAI：

- 私聊聊天回复
- 群聊聊天回复
- 某些需要模型参与的自动化规划

如果你当前只是在调 webhook、reminder、scheduler，可以先不把 OpenClaw 当成最优先步骤。

## 准备本地可调用命令

项目当前通常会通过一个本地命令来调用 OCAI / OpenClaw。

你需要保证：

- 对应命令已经安装
- 当前用户可以在终端里直接执行
- 项目配置里的命令路径正确

示例：

```env
AI_CMD=/path/to/ocai
```

## 最小验证方式

可以先在终端单独测试一下：

```bash
/path/to/ocai --help
```

或者执行你本地已有的最小验证命令，确认它不是“命令不存在”或“权限不足”。

## 与项目的关系

建议把 OpenClaw / OCAI 视为：

- 当前聊天与规划能力的后端
- 可替换 / 可调整的一部分

而不是把整个项目理解成“OpenClaw 的包装壳”。

这个仓库更核心的部分，仍然是：

- QQ webhook
- Python bot 服务
- skill routing
- reminder / scheduler
- 本地自动化骨架
