# NapCat Setup

本页只说明把 NapCat 接到本项目需要关注的部分，不展开完整的 QQ / NapCat 教程。

## 目标

你需要让 NapCat 提供两类能力：

1. 把 QQ 消息通过 webhook 发给本项目
2. 允许本项目通过 NapCat HTTP API 主动发 QQ 消息

## 准备 NapCat

先确保 NapCat 已经正常运行，并完成 QQ 登录。

你至少需要确认：

- NapCat 进程正常在线
- QQ 账号已登录
- HTTP API 可访问
- webhook 推送功能可配置

## 配置 webhook 地址

假设本项目运行在本机 `5000` 端口，那么 webhook 地址通常类似：

```text
http://127.0.0.1:5000/
```

如果 NapCat 和本项目不在同一台机器上，需要把地址改成对应机器的可访问地址。

## 配置 NapCat API 地址与 token

项目侧通常需要知道 NapCat 的：

- HTTP 地址
- access token

示例：

```env
NAPCAT_HTTP=http://127.0.0.1:3001
NAPCAT_TOKEN=your_token_here
```

请把它们写到项目使用的 `.env` 或配置文件中。

## 最小联调检查

建议先验证下面两件事：

### 1. webhook 是否能收到消息

启动项目后，给机器人发一条 QQ 私聊消息，观察终端是否出现类似日志：

```text
[WEBHOOK] 收到请求: ...
[WEBHOOK] message_type: private
```

### 2. 项目是否能通过 NapCat 发回消息

如果消息能收到，但机器人完全不回，继续检查：

- NapCat HTTP API 是否通
- token 是否正确
- 项目配置里的 NapCat 地址是否填对

如果主动 reminder 能成功发到 QQ，通常也说明 NapCat 发送链路是通的。

## 常见建议

- 先在本机把 NapCat 和 Python 服务都跑通
- 不要一开始就跨机器部署
- webhook 不通时优先看 NapCat 侧和 Python 服务侧的终端日志
