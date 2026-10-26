# 个人 QQ 群任务与邮件提醒

在 Windows 日常使用的 QQ 中采集指定群的文字，由服务器上的 NcatBot
提取待办事项、生成每日邮件，并在截止时间前发送提醒。

```text
Windows QQ + LiteLoaderQQNT + NapCat Framework
  └─ desktop 转发插件：群白名单 → 本地暂存 → HTTP(S)
服务器现有 NcatBot
  └─ qq_task_reminder：鉴权及二次群过滤 → SQLite → AI 提取 → SMTP 邮件
```

桌面端直接运行在 NapCat 内，无 npm 依赖，不另启动 Python、Node 服务或第二套 QQ。
它每 30 秒发送心跳并转发最多 50 条暂存消息；非指定群、私聊和媒体内容不上传。
文字里的 @ 提及保留为 `[at:QQ号]`，用于判断任务是否属于你。
实际内存开销及 QQ 兼容性需在安装后测量，不能仅凭代码给出占用保证。

## 当前状态

代码已提供，默认不启用。需要先填写个人 QQ、群号、服务器入口、AI 和邮件配置。
尚未在个人 QQ 或服务器上安装、登录或发送真实邮件。

默认北京时间 21:00 发每日清单；每 5 分钟提取新消息；提前 24 小时、1 小时及到期提醒。
提醒检查间隔 60 秒，新任务提取及邮件服务会额外产生延迟，不能保证实时送达。
错过多个提醒点时只补最近一级。AI 失败保留消息待重试；邮件失败不写成功记录。
重启后保留任务、消息及已发送记录。

## 1. 服务器配置

将整个 `qq_task_reminder` 目录放进服务器项目的 `plugins/`。
依赖服务器现有的 NcatBot 5.x、Python 3.11+ 和 aiohttp，不安装另一套 Bot。

```bash
cp plugins/qq_task_reminder/config.example.toml plugins/qq_task_reminder/config.toml
```

编辑 `config.toml`：

- `account`：你的个人 QQ 号，不能填 Bot 的 QQ。
- `groups`：需要提取任务的群号；桌面端也要填写相同白名单。
- `user_context`：课程、班级、姓名/昵称等，帮助识别哪些任务与你相关。
- `daily_time`、`reminder_hours`：每天汇总时间及提前小时数；`0` 表示到期。
- `ai.base_url`、`ai.model`：兼容 OpenAI Chat Completions 的服务。
  可使用现有 as812 的服务地址和模型，但不会读取它的人设、聊天记忆或配置密钥。
  选中群的文本和已有任务会提交给这个 AI 服务。
- `smtp`：邮箱服务器、端口、发件人、用户名、收件人。支持 SSL 和 STARTTLS。

在服务器 Bot 进程环境中配置：

```text
QQ_TASK_ONEBOT_TOKEN=自定义随机长令牌，桌面端使用同一个值
QQ_TASK_AI_KEY=AI 服务密钥（本地免鉴权服务可不设置）
QQ_TASK_SMTP_PASSWORD=发件邮箱的 SMTP 授权码
```

可用 `python -c "import secrets; print(secrets.token_hex(32))"` 生成传输令牌。
如果 Bot 使用 systemd，变量须配置进该服务的环境文件；仅在 SSH shell 中设置
不会自动传给已启动的服务。授权码不要填 QQ 登录密码，也不要提交到仓库。
本插件的 `config.toml` 已排除版本控制。

确认配置后设 `enabled = true`，通过现有方式重启 Bot。
接收端默认监听服务器 `127.0.0.1:8098`，路径为 `POST /events`。
对 Windows 提供一个可访问的 HTTPS 反向代理入口，保留 Authorization 请求头和请求体。
例如在已有 HTTPS nginx 站点中增加：

```nginx
location = /qq-tasks/events {
    proxy_pass http://127.0.0.1:8098/events;
    proxy_set_header Authorization $http_authorization;
    client_max_body_size 256k;
}
```

桌面配置中的 URL 则为 `https://你的服务器域名/qq-tasks/events`。
也可使用已有 VPN 私网连接，按需调整 `listen_host`；不要为了连接而公开个人 QQ 的控制接口。
接口只接收事件，不提供发送 QQ 消息、执行 OneBot action 或远程控制功能。

## 2. Windows 随 QQ 启动

使用官方 [NapCat Framework 安装说明](https://napneko.github.io/guide/boot/Framework)：

1. 检查 [LiteLoaderQQNT](https://liteloaderqqnt.github.io/) 对当前桌面 QQ 版本的支持情况并安装。
2. 下载匹配的 `NapCat.Framework.zip`，在 LiteLoaderQQNT 中导入，重启 QQ。
3. 确认所装 NapCat 版本支持插件管理及 Node `fetch` API。
4. 把本目录 `desktop/` 中的 `package.json` 和 `index.mjs` 复制到 NapCat 的
   `plugins/napcat-plugin-personal-tasks/`，在 NapCat 插件管理中启用。
5. 首次加载会创建一个默认关闭的 JSON 配置，日志会显示 `ctx.configPath` 的实际位置。
   编辑该文件，再重新加载采集插件：

```json
{
  "enabled": true,
  "account": "你的个人QQ号",
  "groups": ["目标群号1", "目标群号2"],
  "url": "https://你的服务器域名/qq-tasks/events",
  "token": "与服务器QQ_TASK_ONEBOT_TOKEN一致"
}
```

**不要另外配置普通 HTTP 客户端或反向 WebSocket 直连任务服务器**：
本插件自己发送筛选后的消息，普通 OneBot 上报可能绕过桌面群筛选。
群筛选、消息暂存及上传均在 QQ/NapCat 进程内执行。

之后正常打开 QQ 即可运行采集，彻底退出 QQ 后停止。关闭窗口但仍在系统托盘运行
不算退出。QQ 关闭期间服务器继续提醒已登记任务；这段时间新发的群消息不保证能补齐。
如果当时 QQ 仍在运行、只是网络或服务器中断，已落盘消息保留在
采集插件的 `dataPath/outbox/`，下一次连接后重试。

## 3. 验证与使用

先用一个测试群和自己的收件邮箱完成联调：

1. 设置客户端和服务端相同的个人 QQ 号、测试群号和传输令牌。
2. 在测试群发一条明确的任务，例如“请在 2026 年 10 月 30 日 18:00 前提交报告”。
3. 等待转发和提取；检查服务器 `data/qq_task_reminder/tasks.sqlite3` 是否有消息和任务。
4. 将汇总时间临时设为稍后几分钟，重启插件，检查收到的清单及来源原文。
5. 用另一个即将到期的测试任务验证提醒。最后改回正式时间和群白名单。

邮件包含任务标题、截止时间、来源群、消息编号和原文依据。
无法确定截止时间或适用对象的事项标为待确认，不自动编造 23:59 等时间。
目前清单列出累计提取的任务，未提供完成/取消管理界面；语义去重和改期识别依赖模型，
应核对原文。图片、语音、文件内容、合并转发、撤回和历史补拉不在首版处理范围内。

服务器处理过的消息正文保留 30 天；待处理消息不会自动删除，任务中的引用原文仍保留。
桌面上传成功即删除相应暂存文件。长时间离线时应关注桌面磁盘空间。
SMTP 接受邮件后若进程在写发送记录之前崩溃，重启可能重复发送，不能保证恰好一次投递。

离线测试（不登录 QQ、不调用真实 AI、不发送邮件）：

```bash
python -m unittest discover -s tests -p test_qq_task_reminder.py
node --test tests/test_qq_task_forwarder.mjs
```

Node 只用于开发测试；实际使用桌面插件不需要另装 Node。
