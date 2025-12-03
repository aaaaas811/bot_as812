# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, PrivateMessage,GroupMessage,NoticeEvent, MessageArray
from ncatbot.utils import config
import asyncio
# ========== 创建 BotClient ==========
bot = BotClient()
# 配置：设置轮询等待时间（秒）
cyc_wait_time = 0.2
# 配置：表情歼灭模式
emoji_kill_model = False
emoji_kill_times = 8
emoji_wait_time = 0.1
emoji_combo={147,127827,127853,10068,76,424,12951,63,66,9992}#废
# 配置：将这里的账号 ID 替换为你要监控的“账号 MASTER”QQ 号（字符串或整数都可）
ACCOUNT_MASTER_ID = '3196611630'

# ========= 注册回调函数 ==========
@bot.private_event()
async def on_private_message(msg: PrivateMessage):
    global emoji_kill_model
    if msg.user_id == ACCOUNT_MASTER_ID:
        if msg.raw_message == "测试":
            await bot.api.post_private_msg(msg.user_id, text="NcatBot 测试成功喵~")
        if msg.raw_message == "表情歼灭模式开启":
            emoji_kill_model = True
            await bot.api.post_private_msg(msg.user_id, text="表情歼灭模式已开启喵~")
        if msg.raw_message == "表情歼灭模式关闭":
            emoji_kill_model = False
            await bot.api.post_private_msg(msg.user_id, text="表情歼灭模式已关闭喵~")
        if msg.raw_message == "查询表情歼灭模式":
            status = "开启" if emoji_kill_model else "关闭"
            await bot.api.post_private_msg(msg.user_id, text=f"当前表情歼灭模式为：{status} 喵~")
        
            await msg.reply(text="诶？我还没搞这个")
@bot.group_event()
async def on_group_message(msg: GroupMessage):
    if msg.raw_message == "/菜单":
        menu_text = "诶？我还没搞这个诶"
        await msg.reply(text=menu_text)
@bot.on_notice() # type: ignore
async def on_notice(event: NoticeEvent):
    # 兼容不同版本的字段名
    notice = getattr(event, 'sub_type', None) or getattr(event, 'notice_type', None)
    liker = getattr(event, 'user_id', None)

    # 监听贴表情事件
    if notice == 'group_msg_emoji_like':        
        is_add = getattr(event, 'is_add', None)
        emoji_like_id = getattr(event, 'emoji_like_id', None)
        # 只对账号MASTER的新增表情回应作出反应
        if is_add :
            try:
                if str(liker) != str(ACCOUNT_MASTER_ID):
                    return
            except Exception:
                return
        else:
            return
         #！！！！之前的bug，找到原因了，是参数不匹配导致的！！！！
        global emoji_kill_model
        if emoji_kill_model == False:
            try:
                #await bot.api.send_poke(user_id=getattr(event, 'user_id', None), group_id=getattr(event, 'group_id', None))
                #await bot.api.post_group_msg(group_id=getattr(event, 'group_id', None), text="糖")
                await bot.api.set_msg_emoji_like(message_id=getattr(event, 'message_id', None), emoji_id=emoji_like_id, set=is_add)
            except Exception:
                pass
            return
        else:
            for i in range(emoji_kill_times):
                
                try:
                    await bot.api.set_msg_emoji_like(message_id=getattr(event, 'message_id', None), emoji_id=emoji_like_id, set=True)
                    await asyncio.sleep(emoji_wait_time)
                    await bot.api.set_msg_emoji_like(message_id=getattr(event, 'message_id', None), emoji_id=emoji_like_id, set=False)
                except Exception:
                    pass
    # 监听戳一戳事件
    if notice == 'poke':
        if getattr(event, 'target_id', None) == getattr(event, 'self_id', None):
            for _ in range(5):
                try:
                    await bot.api.send_poke(user_id=getattr(event, 'user_id', None), group_id=getattr(event, 'group_id', None))
                except Exception:
                    pass
                await asyncio.sleep(cyc_wait_time)
    
# ========== 启动 BotClient==========
bot.run()

