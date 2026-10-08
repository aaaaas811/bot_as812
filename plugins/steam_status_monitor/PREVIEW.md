# Steam 状态监控（NcatBot 迁移版）功能预览

### 功能 1：群聊 Steam 状态监控

群管理员添加 Steam 玩家并启动监控后，插件定时轮询状态，在上线、离线、开始游戏、切换游戏和结束游戏时向对应 QQ 群推送通知。

**触发方式**：群聊管理命令与后台轮询

**对话流**：

用户（管理员）：`/steam addid 7656119xxxxxxxxx`

Bot：添加成功，并显示该玩家的 Steam 信息。

用户（管理员）：`/steam on`

Bot：已启动本群 Steam 状态监控。

[Steam 状态变化]

Bot：发送状态文字和对应的游戏卡片图片。

**边界情况**：Steam API Key 缺失或 Steam 请求失败时返回明确错误，不启动无效轮询。

### 功能 2：查询与排行榜

群成员可查询当前玩家状态、游戏价格、游戏详情和指定时间范围的游玩时长排行榜。

**触发方式**：`/steam list`、`/steam price <游戏名>`、`/steam game <AppID>`、`/steam rank [天数]`

**对话流**：

用户：`/steam help`

Bot：返回完整 Steam 命令列表。

用户：`/steam rank 7`

Bot：返回本群最近 7 天的游戏时长排行榜图片。

### 功能 3：分群配置与主动推送

每个群独立维护 SteamID、监控开关和成就开关，也可将同一玩家的通知联动到其他群。

**触发方式**：`/steam push_group <SteamID>`、`/steam achievement_on`、`/steam achievement_off`

**对话流**：

用户（管理员）：`/steam push_group 7656119xxxxxxxxx`

Bot：本群已加入该 SteamID 的联动推送组。

### 功能 4：NcatBot 生命周期与权限

插件由 `manifest.toml` 发现，加载时启动后台任务，卸载或热重载时取消并等待任务结束，同时保存数据。本群操作允许 NcatBot 全局 root、群主和群管理员；跨群、全局配置及清理操作仅允许全局 root。

**触发方式**：NcatBot 启动、卸载、热重载，以及管理命令

**边界情况**：原 AstrBot Plugin Pages 管理页和 QQ 官方指令面板在 NcatBot 中无对等接口，相关入口安全降级；AstrBot LLM 游戏名翻译也未迁移，价格搜索会直接使用原始查询词，其他聊天命令不受影响。
