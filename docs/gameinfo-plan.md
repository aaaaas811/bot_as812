# gameinfo 插件实现计划

## 目标
开发一个 NcatBot 插件，从 Bilibili 获取指定 UP 主当日发布的视频信息，合并为一条聊天记录转发到指定 QQ 群。

## 插件结构

```
plugins/gameinfo/
├── __init__.py          # 导出插件类
├── manifest.toml        # 插件元数据
├── main.py              # 插件主逻辑
└── config/
    └── config.yaml      # 插件配置（UID列表、群号列表、检查间隔等）
```

## 配置设计 (config/config.yaml)

```yaml
# 要监控的UP主UID列表
uids:
  - 42931610    # 示例UID
  # - 其他UID...

# 转发目标群号列表
target_groups:
  - 883744030   # 示例群号

# 检查间隔（分钟）
check_interval: 30

# 首次加载时是否发送今日已发布视频
send_on_load: true
```

## 核心功能模块

### 1. Bilibili API 调用
- 使用 Bilibili 公开 API: `https://api.bilibili.com/x/space/wbi/arc/search`
- 需要 WBI 签名（w_rid + wts 参数），实现签名算法
- 按 UID 逐个获取视频列表，过滤 `created` 时间为当天的视频
- 获取 UP 主基本信息（昵称、头像）用于构造转发消息

### 2. 定时检查
- 使用 `add_scheduled_task()` 注册定时任务
- 间隔可配置，默认 30 分钟
- 首次加载时根据 `send_on_load` 决定是否立即发送

### 3. 去重机制
- 在 `data/gameinfo/` 目录下维护 `sent_videos.json`
- 记录已发送视频的 bvid，避免重复推送
- 数据结构: `{"uid_xxx": ["BVxxxxxxxx", ...], ...}`

### 4. 合并转发消息构造
- 使用 `ForwardConstructor` 构造合并转发
- 每个视频作为一条独立节点
- 节点使用 UP 主的昵称和 UID、头像作为发送者信息
- 视频信息包含：标题、BV号、发布时间、封面图、链接

### 5. 多群发送
- 遍历 `target_groups` 列表，依次发送到每个群
- 发送失败时记录日志但不阻塞其他群的发送

## 实现步骤

1. 创建插件目录结构和 manifest.toml
2. 实现 Bilibili API 客户端（WBI 签名 + 视频获取）
3. 实现去重存储管理
4. 实现视频信息格式化与转发消息构造
5. 实现定时任务调度
6. 实现插件主类及生命周期方法
7. 测试验证

## 关键技术细节

### WBI 签名流程
1. GET `https://api.bilibili.com/x/web-interface/nav` 获取 `wbi_img.img_key` 和 `wbi_img.sub_key`
2. 拼接 `img_key + sub_key`，取前 32 位作为 `mix_key`
3. 将所有请求参数按 key 排序，拼接为 `key=value&key=value` 格式
4. 追加 `mix_key`，计算 MD5 → `w_rid`
5. 请求时附带 `w_rid` 和 `wts`（当前秒级时间戳）参数

### 视频过滤逻辑
- API 返回的 `pubdate` 为 Unix 时间戳
- 判断 `pubdate` 是否在当天 00:00:00 ~ 23:59:59 范围内
- 使用中国时区 (UTC+8)

### 依赖
- `aiohttp` — 已在项目 requirements.txt 中，用于异步 HTTP 请求
- `PyYAML` — 已在项目 requirements.txt 中，用于读取配置
