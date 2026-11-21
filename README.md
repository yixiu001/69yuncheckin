# 69云 自动签到

> 用 GitHub Actions 每天自动登录 [69云](https://69yun69.com) 完成签到，并把到期时间、剩余流量、订阅链接与签到结果推送到 Telegram。

## 功能

- 每天定时自动签到（UTC 00:01，即北京时间 08:01）
- 支持多账号，一个 Telegram Bot 群发所有账号的签到结果
- 推送内容包含：到期时间、剩余流量、Clash / v2ray 订阅链接
- 密码在消息中**脱敏显示**（只保留首尾各 1 位），不发送明文
- 支持手动触发，方便随时验证

## 快速开始

### 1. Star 和 Fork

点个 Star 支持一下，然后点右上角 **Fork** 把仓库复制到自己的账号下。

> 视频教程：https://youtu.be/HjECaEIH4_s

### 2. 配置 Secrets

Fork 后进入你的仓库 **Settings → Secrets and variables → Actions**，点 **New repository secret**，添加以下密钥：

| Secret | 说明 |
|---|---|
| `BOT_TOKEN` | 你的 Telegram Bot Token（找 [@BotFather](https://t.me/BotFather) 创建） |
| `CHAT_ID` | 接收消息的 Chat ID（可以是个人、群组或频道） |
| `USER1` | 第 1 个账号（登录邮箱） |
| `PASS1` | 第 1 个账号的密码 |
| `USER2` | 第 2 个账号（登录邮箱） |
| `PASS2` | 第 2 个账号的密码 |

`BOT_TOKEN` 和 `CHAT_ID` 只需配一份，所有账号共用。

### 3. 添加更多账号

脚本会自动读取 `USER1 / PASS1`、`USER2 / PASS2`……一直到 `USER20 / PASS20`。

要新增账号时，需要在 `.github/workflows/69yuncheckin.yaml` 的 `env:` 里再补两行，例如：

```yaml
USER3: ${{ secrets.USER3 }}
PASS3: ${{ secrets.PASS3 }}
```

然后在仓库 Secrets 里对应添加 `USER3`、`PASS3` 即可，**无需改动 Python 脚本**。

### 4. 手动运行一次验证

进入 **Actions** 页面，选择 `69云 签到` 工作流，点 **Run workflow** 手动触发一次，确认能正常签到并收到 Telegram 消息。之后每天会自动运行。

## 本地运行（可选）

```bash
pip install -r requirements.txt

# 设置环境变量后运行
export BOT_TOKEN="..."
export CHAT_ID="..."
export USER1="you@example.com"
export PASS1="your-password"
python 69yun.py
```

> 也可以在环境变量里加 `DOMAIN` 覆盖默认面板地址（默认 `https://69yun69.com`）。

## 常见问题

- **没有收到 Telegram 消息**：确认 `BOT_TOKEN` 和 `CHAT_ID` 都正确；给 Bot 发过消息后才能主动私聊你。
- **提示未配置任何账号**：检查 `USER1 / PASS1` 是否在 Secrets 里设置，且与 yaml 中的引用名称一致。
- **定时任务没有运行**：GitHub 对 60 天无提交的仓库会停用定时任务，偶尔手动跑一次即可激活。
- **签到失败**：检查 Actions 日志中的具体报错，常见原因是密码错误或面板改版导致解析失败。

## 注意事项

- 定时触发用的是 UTC 时间（`1 0 * * *` = 北京时间 08:01），不是北京时间 0 点。
- 密码只做脱敏展示，请勿在消息或日志里输出明文密码。
- 本工具仅供个人学习与自动化使用，请遵守目标站点的服务条款。
