# as812_xiaozhi_bridge

将 QQ 私聊消息桥接到 [xiaozhi-esp32-server](https://github.com/78/xiaozhi-esp32) 的 AI 对话管线。

## 原理

xiaozhi-server 本身为 ESP32 硬件设计，通过 WebSocket 传输 Opus 音频 + JSON 指令。但它有一个 `listen/detect` 文本通道可以绕过语音识别，直接将文本送入 LLM。

本插件作为 WebSocket 客户端连接 xiaozhi-server，将 QQ 私聊的文本通过 `detect` 通道发送，收集 TTS 响应中的 `sentence_start` 文本片段，拼接后返回 QQ。

## 配置

编辑 `config/config.yaml`：

```yaml
xiaozhi_server:
  url: "ws://10.203.135.87:8000/xiaozhi/v1/"
  device_id: "qq-bot-bridge"
  client_id: "qq-bot-client"
  authorization: ""          # 如 xiaozhi-server 开启 auth 则填入 Bearer token

messaging:
  super_user: "3196611630"   # 默认仅此用户可用私聊桥接
  allowed_users: []          # 额外允许的用户 QQ 号列表
  status_reply: "小智正在思考..."  # 收到消息时的状态提示，留空禁用
```

## 依赖

- `websockets` — WebSocket 客户端
- `PyYAML` — 配置文件解析

两者都是 bot_as812 环境已有的依赖，通常无需额外安装。
