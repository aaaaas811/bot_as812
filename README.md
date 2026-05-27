<p align="center">
  <img src="as812.png" alt="as812" width="200">
</p>

# bot_as812

基于 [NcatBot](https://github.com/ncatbot/NcatBot) 框架的多功能 QQ 机器人，集成 AI 对话、游戏数据查询、内容推送与 xiaozhi-esp32-server 桥接。


<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<!-- PROJECT LOGO -->
<br />

<p align="center">
  <h3 align="center">bot_as812</h3>
  <p align="center">
    QQ 平台多功能机器人，插件化架构
    <br />
    <br />
    <a href="./plugins">插件列表</a>
    ·
    <a href="https://github.com/ncatbot/NcatBot/issues">报告 Bug</a>
    ·
    <a href="https://github.com/ncatbot/NcatBot/issues">提出新特性</a>
  </p>
</p>

## 目录

- [功能概览](#功能概览)
- [上手指南](#上手指南)
  - [环境要求](#环境要求)
  - [安装步骤](#安装步骤)
- [文件目录说明](#文件目录说明)
- [插件系统](#插件系统)
- [部署](#部署)
- [使用到的框架](#使用到的框架)
- [贡献者](#贡献者)
- [版本控制](#版本控制)
- [作者](#作者)
- [鸣谢](#鸣谢)

## 功能概览

| 插件 | 说明 |
|------|------|
| **as812** | 主插件：AI 聊天（DeepSeek / Ollama）、RAG 知识库、B 站动态监听、表情包、私聊转述、情绪管理 |
| **gameinfo** | B 站游戏资讯：监控指定 UP 主视频，支持定时推送、按天数查询、动态添加 UP 主 |
| **mh** | 怪物猎人插件：MHW/MHR 集会码管理、怪物数据查询（肉质/弱点/简介）、Wiki 爬虫 |
| **yuri** | 内容推送：Yuri 图片、每日金句、百合台词、名言警句，支持定时任务 |
| **_31966_plugin** | 工具箱：戳一戳自动回击、表情回应、群成员欢迎、睡眠模式控制 |
| **as812_xiaozhi_bridge** | 桥接 xiaozhi-esp32-server，将 QQ 私聊消息接入 ESP32 AI 对话管线 |

### 上手指南

#### 环境要求

- **Python** ≥ 3.10
- **NapCat** — QQ 协议适配端（自动安装，需手动配置 QQ 账号）
- **系统**：Windows / Linux

#### 安装步骤

1. Clone 仓库
   ```sh
   git clone <your-repo-url> bot_as812
   cd bot_as812
   ```

2. 创建虚拟环境并安装依赖
   ```sh
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate  # Linux/Mac
   pip install -r requirements.txt
   ```

3. 配置 NapCat（首次启动时自动引导安装）
   ```sh
   python main.py
   ```
   启动后根据提示登录 QQ 账号，NapCat 将自动完成协议适配端配置。

4. 配置插件
   - 编辑 `config.yaml` 中的 `root` 为你的 QQ 号
   - 修改 `plugins/as812/config/config.yaml` 中的 API Key 等配置
   - 各插件独立配置位于 `plugins/<name>/config/`

### 文件目录说明

```
bot_as812/
├── main.py                        # 项目启动入口
├── config.yaml                    # 框架级配置（NcatBot + 适配器）
├── requirements.txt               # 项目级依赖
├── bot_state.py                   # 全局状态管理（睡眠模式、管理员列表）
├── sdk_compat.py                  # NcatBot SDK 运行时补丁
├── check_n_update.py              # 启动时自动更新检查
├── plugins/                       # 插件目录
│   ├── as812/                     # 主 AI 插件
│   │   ├── main.py                # 插件入口，消息路由
│   │   ├── core/                  # 配置管理、日志管理
│   │   ├── handlers/              # 消息处理、命令处理、回复处理
│   │   ├── models/                # 数据模型
│   │   ├── responses/             # AI 聊天响应生成
│   │   ├── rag/                   # ChromaDB RAG 知识库引擎
│   │   ├── utils/                 # API 调用工具
│   │   └── config/                # API Key、Prompt 等配置
│   ├── mh/                        # 怪物猎人插件
│   │   ├── mh.py                  # 插件入口
│   │   ├── analyze.py             # 怪物数据分析
│   │   └── data/                  # 怪物 JSON 数据
│   ├── gameinfo/                  # B站游戏资讯插件
│   │   ├── main.py                # 插件入口
│   │   └── config/                # UP主列表、目标群等配置
│   ├── yuri/                      # 内容推送插件
│   │   ├── main.py                # 插件入口
│   │   └── data/                  # 语录文件
│   ├── _31966_plugin/             # 工具箱插件
│   │   └── plugin.py              # 插件入口
│   └── as812_xiaozhi_bridge/      # xiaozhi-server 桥接插件
│       ├── main.py                # 插件入口
│       ├── connection.py          # WebSocket 连接管理
│       └── config/                # 桥接配置
├── plugins_nouse/                 # 未启用的旧插件
├── napcat/                        # NapCat QQ 协议适配端
├── data/                          # 运行时数据
└── logs/                          # 运行日志
```

### 插件系统

本项目采用 NcatBot 的插件架构。每个插件是 `plugins/` 下的独立目录，由框架自动发现和加载。

#### 插件结构规范

```
plugins/<plugin_name>/
├── __init__.py          # 导出插件类到 __all__
├── manifest.toml        # 插件清单（名称、版本、入口类）
├── main.py              # 插件主类，继承 NcatBotPlugin
├── requirements.txt     # 插件级依赖（可选）
└── config/              # 插件级配置（可选）
```

#### 插件加载方式

1. 框架扫描 `plugins/` 目录下所有包含 `manifest.toml` 的子目录
2. 读取 `entry_class` 指定的类名，实例化插件
3. 通过 `@registrar.qq.on_xxx()` 装饰器注册事件处理函数
4. 支持热重载（`hot_reload: true`）

#### 支持的事件类型

| 事件 | 装饰器 | 说明 |
|------|--------|------|
| 群消息 | `@registrar.qq.on_group_message()` | 群聊文本消息 |
| 私聊消息 | `@registrar.qq.on_private_message()` | 私聊文本消息 |
| 群命令 | `@registrar.qq.on_group_command("cmd")` | 监听指定命令 |
| 戳一戳 | `@registrar.qq.on_poke()` | 头像双击/戳一戳 |
| 群成员增加 | `@registrar.qq.on_group_increase()` | 新人入群 |
| 表情回应 | `@registrar.on("notice.group_msg_emoji_like", platform="qq")` | 表情回复 |
| B 站弹幕/私信等 | `@bili_registrar.on_danmu()` | Bilibili 平台事件 |

#### gameinfo 插件指令

| 指令 | 说明 | 权限 |
|------|------|------|
| `/gameinfo` | 获取当日所有监控 UP 主的视频，合并转发到当前群 | 所有人 |
| `/gameinfo x` | 获取最近 x 天内所有监控 UP 主的视频 | 所有人 |
| `/gameinfo add <UID> <名称>` | 添加（或更新）一个 B 站 UP 主到监控列表 | 群主 / 管理员 / 特殊账号 |

配置文件位于 `plugins/gameinfo/config/config.yaml`，可手动编辑 UP 主列表、目标群号、定时检查间隔等。

### 部署

#### 普通运行

```sh
python main.py
```

#### 后台运行（Linux）

```sh
nohup python main.py > bot.log 2>&1 &
```

### 使用到的框架

- [NcatBot](https://github.com/ncatbot/NcatBot) — QQ 机器人框架
- [NapCat](https://github.com/NapNeko/NapCatQQ) — QQ 协议适配端
- [websockets](https://github.com/python-websockets/websockets) — WebSocket 客户端/服务端
- [Ollama](https://ollama.com) / [DeepSeek](https://deepseek.com) — LLM 后端
- [ChromaDB](https://www.trychroma.com) — 向量数据库（RAG）
- [aiohttp](https://docs.aiohttp.org) — 异步 HTTP 客户端

### 贡献者

本项目为个人项目，目前由 as811 维护。

#### 如何参与开源项目

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### 版本控制

该项目使用 Git 进行版本管理。

### 作者

**as811** (aaaaas811)

- QQ: 3196611630

### 版权说明

该项目签署了 MIT 授权许可。

### 鸣谢

- [NcatBot](https://github.com/ncatbot/NcatBot) — 优秀的 QQ 机器人框架
- [NapCat](https://github.com/NapNeko/NapCatQQ) — 无头 QQ 协议实现
- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — ESP32 AI 对话服务端
- [mhws_Wiki_Crawler](https://github.com/Azuxa616/mhws_Wiki_Crawler) — 怪物猎人 Wiki 爬虫
- [Best README Template](https://github.com/shaojintian/Best_README_template) — README 模板参考

<!-- links -->
[contributors-shield]: https://img.shields.io/github/contributors/aaaaas811/bot_as812.svg?style=flat-square
[contributors-url]: https://github.com/aaaaas811/bot_as812/graphs/contributors
[issues-shield]: https://img.shields.io/github/issues/aaaaas811/bot_as812.svg?style=flat-square
[issues-url]: https://github.com/aaaaas811/bot_as812/issues
[license-shield]: https://img.shields.io/github/license/aaaaas811/bot_as812.svg?style=flat-square
[license-url]: https://github.com/aaaaas811/bot_as812/blob/main/LICENSE


Todolist:
ESP结合
贴表情功能重构
灵活的定时任务