# Debug Logs

这个项目当前日志比较偏开发态，优点是排错信息很直接。

如果你在调 webhook、skill 路由、NapCat 发送、reminder / scheduler，建议始终盯着终端日志看。

## 常见日志前缀

### webhook 相关

```text
[WEBHOOK] ...
```

说明 NapCat 已经把消息送到 Python 服务。

### skill 路由相关

```text
[SKILL] check ...
[SKILL] result ...
```

用来判断一条消息最终被哪个 skill 接管。

### 私聊聊天链路

```text
[PRIVATE_CHAT] queued
[OCAI] start
```

如果你本来希望它走的是 reminder / schedule 查询，但日志出现了这两类，说明消息被错误地落回 chat / OCAI 了。

### reminder / scheduler

```text
[SCHEDULER] tick now=...
[REMINDER] added id=...
[REMINDER] firing id=...
[REMINDER] sent id=...
```

这部分日志主要用来确认主动提醒链路是否打通。

### NapCat 发送

```text
[SEND_PRIVATE] ...
[SEND_GROUP] ...
```

如果消息接收正常，但最终发不回去，通常要重点看这里。

## 推荐的排查方式

遇到问题时，不要只盯着最后一句报错，建议按顺序看：

1. 有没有收到 webhook
2. skill 是否命中正确
3. 是否进入了错误的处理链路
4. NapCat 发送是否成功
5. scheduler / reminder / store 状态是否一致

## 复制日志给 AI

如果你自己一时看不出来问题在哪，最实用的方法是：

1. 把终端完整日志复制出来
2. 包括上下文，不要只截最后一行
3. 发给 AI 让它帮你定位

例如：

```text
[SCHEDULER] tick now=...
[WEBHOOK] message_type: private
[SKILL] check reminder reason=...
[PRIVATE_CHAT] queued
[OCAI] start
[SEND_PRIVATE] NapCat 返回: 200
```

日志越完整，越容易分清：

- 是 webhook 没收到
- 是 skill 路由没命中
- 是 reminder 没写回
- 还是 NapCat API / OCAI / 配置问题
