# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, PrivateMessage,NoticeEvent, MessageArray
from ncatbot.utils import config
import asyncio
# ========== 创建 BotClient ==========
bot = BotClient()

# 配置：将这里的账号 ID 替换为你要监控的“账号 A”QQ 号（字符串或整数都可）
ACCOUNT_A_ID = '3196611630'

# ========= 注册回调函数 ==========
@bot.private_event()
async def on_private_message(msg: PrivateMessage):
    if msg.raw_message == "测试":
        await bot.api.post_private_msg(msg.user_id, text="NcatBot 测试成功喵~")
@bot.on_notice() # type: ignore
async def on_notice(event: NoticeEvent):
    notice = event.sub_type
    if notice == 'poke': # 戳一戳消息            
        if event.target_id == event.self_id:
            # Bot 被戳时连续戳回去 5 次（带小间隔，避免触发速率限制）
            for _ in range(5):
                try:
                    await bot.api.send_poke(user_id=event.user_id, group_id=event.group_id)
                except Exception:
                    # 忽略单次发送失败，继续尝试余下的
                    pass
                await asyncio.sleep(0.2)
    # 监听消息的表情回应
    if notice == 'group_msg_emoji_like':
        # 只对账号A的新增表情回应作出反应
        if event.is_add:
            liker = event.user_id
            if liker != ACCOUNT_A_ID:
                return
            await bot.api.set_msg_emoji_like(message_id=event.message_id, emoji_id=event.emoji_like_id)
        else:
            return
# ========== 启动 BotClient==========
bot.run_frontend()

