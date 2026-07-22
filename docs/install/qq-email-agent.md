# 个性化校园邮件推送

本功能通过只读 IMAP 整理校园邮件，使用本地规则与无工具模型分类，并将精简结果发送到 owner QQ。它不提供 SMTP，也不会修改、删除或标记邮箱中的邮件。

## 数据与密钥边界

- IMAP 密码、API key 和 provider 地址只放在 `~/.candace/qq-ai-bridge.env`，文件权限应为 `0600`。
- 个性化画像和反馈位于 `~/.candace/email-agent/`，同样使用 `0600`，不进入 Git。
- 原始邮件归档只保存在本机 `BASE_DATA_DIR/email/archive`，默认保留 30 天。
- 自动推送调用 `send_private_msg(..., redact_content=True)`；普通日志只保留状态、计数和错误类型。
- 邮件正文会发送给配置的云模型进行分类。使用第三方网关时，其数据处理与计费规则由该网关决定。

## API 分工

- QuotaRouter Responses provider 的 `gpt-5.6-terra`、`AGENT_MODEL_REASONING_EFFORT=high` 用于邮件语义分类和压缩。
- `AGENT_DISABLE_RESPONSE_STORAGE=true` 请求 provider 不存储响应；最终是否执行仍取决于 provider 能力。
- DeepSeek V4 继续处理普通聊天，默认不接收邮件内容。
- Banana 只用于图片生成，邮件链路无法调用图片能力。
- 邮件模型请求固定 `tools=[]`，不允许网页、电脑、SMTP 或本地工具回退。

环境文件只填写真实值，不要把它们复制到仓库文档。相关非敏感开关如下：

```dotenv
AGENT_PROVIDER=responses_proxy
RESPONSES_PROXY_MODEL=gpt-5.6-terra
AGENT_MODEL_REASONING_EFFORT=high
AGENT_DISABLE_RESPONSE_STORAGE=true

EMAIL_MONITOR_ENABLED=false
EMAIL_IMMEDIATE_PUSH_ENABLED=false
EMAIL_DIGEST_PUSH_ENABLED=false
EMAIL_SHADOW_MODE=true
EMAIL_POLL_INTERVAL_SECONDS=300
EMAIL_DIGEST_TIMES=12:30,20:30
```

## 安全诊断

从仓库根目录运行：

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --config
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --imap
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --shadow-report
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --cleanup --dry-run
```

诊断只输出单行 JSON，不读取 stdin，不打印邮箱地址、主题、正文、归档路径或凭据。`--cleanup` 不带 `--dry-run` 会实际删除超过保留期的本机归档，执行前应先检查 dry-run 数量。

## 无新邮件时的端到端演练

先运行不发送 QQ 的演练。它使用真实规则和真实邮件分类模型，但把发送结果记录在内存中：

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python \
  qq-ai-bridge/scripts/email_agent_check.py --simulate-automation
```

演练会注入课程考试调整、机器人竞赛和无关招聘三封合成邮件，并重复执行 poll 和摘要槽位。返回 JSON 中三类 route 应依次为 `immediate`、`digest`、`ignore`，`idempotency.poll` 和 `idempotency.digest` 均应为 `true`。

确认 dry-run 通过后，才运行真实 QQ 演练：

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python \
  qq-ai-bridge/scripts/email_agent_check.py \
  --simulate-automation --deliver-to-owner --accept-qq-send
```

真实演练只发送模型精简后的即时提醒和摘要，共两次服务级发送。消息带有“邮件自动推送模拟”标记，并通过 `redact_content=True` 写入脱敏审计。两个发送确认参数缺一不可。

两种演练都使用临时 IMAP 适配器、临时画像、临时归档和临时处理状态。它们不连接真实 IMAP，不读取或推进真实邮箱 UID 游标，也不会把合成记录写入正式摘要。

## QQ 命令

按需摘要：

```text
邮件 今天
邮件 昨天
邮件 本周
邮件 上周
邮件 最近 7 天
邮件 状态
```

反馈学习：

```text
邮件 E-1042 有用
邮件 E-1042 忽略
邮件 E-1042 忽略此类
邮件 E-1042 关注发件人
邮件 E-1042 撤销反馈
邮件 偏好
```

这些命令仅接受 owner 私聊。`关注发件人` 只学习完整发件地址，不根据共享的学校 edu 域名推断老师或机构；`忽略此类` 只形成可撤销的类别权重，不创建永久黑名单。

## 分阶段启用

1. 保持三项 automation 开关为 `false`，先运行配置和 IMAP 诊断。
2. 设置 `EMAIL_MONITOR_ENABLED=true`，继续保持 `EMAIL_SHADOW_MODE=true`，观察至少 24 小时的本地计数。
3. 根据误判通过 QQ 反馈或本机画像文件调整规则。
4. 经人工确认后，单独启用 `EMAIL_IMMEDIATE_PUSH_ENABLED=true`。
5. 再确认摘要内容与增量去重后，启用 `EMAIL_DIGEST_PUSH_ENABLED=true`。
6. 最后关闭 shadow mode 才会实际发送。NapCat 失败不会写入送达终态，下一轮会重试。

## 回滚

将以下开关全部设回 `false` 并重启 bridge：

```dotenv
EMAIL_MONITOR_ENABLED=false
EMAIL_IMMEDIATE_PUSH_ENABLED=false
EMAIL_DIGEST_PUSH_ENABLED=false
```

这不会删除画像、反馈或归档。需要清理归档时先运行 `--cleanup --dry-run`。自动化回滚不影响普通 QQ 聊天、提醒和手动邮件摘要命令。
