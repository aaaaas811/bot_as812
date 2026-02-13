# Yuri 插件

一个基于 ncatbot 的插件，提供各种有趣的内容，包括 Yuri 图片、每日金句、百合台词和名言警句。

## 功能

### 指令

- `/yuri`：发送一张随机 Yuri 图片
- `/一言`：发送一条每日金句
- `/yuriwords`：发送一条百合台词
- `/名言警句 [次数]`：发送指定次数的名言警句（默认 1 次，最大 10 次）

所有指令支持私聊和群聊。

### 定时任务

每隔 3 小时（从 00:00 开始）随机选择一个指令执行，并发送到指定群组。

## 安装

1. 将插件文件夹 `yuri` 放入项目的 `plugins` 目录。
2. 安装依赖：
   ```
   pip install -r plugins/yuri/requirements.txt
   ```
3. 修改 `plugins/yuri/main.py` 中的 `ACTIVE_GROUP_ID` 为你想要发送定时内容的群 ID。

## 配置

- `ACTIVE_GROUP_ID`：定时任务发送的目标群 ID，请修改为实际群号。

## 依赖

- requests
- uapi

## API 来源

- Yuri 图片：https://v1.yurikoto.com/wallpaper
- 每日金句：https://uapis.cn
- 百合台词：https://v1.yurikoto.com/sentence
- 名言警句：本地文件 `data/rgl.txt`

## 注意事项

- 确保 `data/rgl.txt` 文件存在，否则 `/名言警句` 指令将无法工作。
- 图片会下载到 `plugins/yuri/image_cache/` 目录以提高性能。
- 定时任务依赖 ncatbot 的调度系统。