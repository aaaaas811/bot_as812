# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, PrivateMessage,GroupMessage,NoticeEvent, MessageArray
from ncatbot.utils import config
import asyncio
import bot_state
# ========== 创建 BotClient ==========
bot = BotClient()

# 配置：设置轮询等待时间（秒）
cyc_wait_time = 0.2
# 配置：表情歼灭模式
emoji_kill_model = False
emoji_kill_times = 8
emoji_wait_time = 0.1
emoji_combo = {147,127827,127853,10068,76,424,12951,63,66,9992}#废

# ========= 注册回调函数 ==========
@bot.private_event()
@bot_state.ignore_if_sleeping(allow_uins=bot_state.MASTER_UIN)
async def master_message_control(msg: PrivateMessage):
    global emoji_kill_model, emoji_kill_times
    text = msg.raw_message
    if text == "测试":
        await bot.api.post_private_msg(msg.user_id, text="NcatBot 测试成功喵~")
    if text == "表情歼灭模式开启":
        emoji_kill_model = True
        await bot.api.post_private_msg(msg.user_id, text="表情歼灭模式已开启喵~")
    if text == "表情歼灭模式关闭":
        emoji_kill_model = False
        await bot.api.post_private_msg(msg.user_id, text="表情歼灭模式已关闭喵~")
    if text == "查询表情歼灭模式":
        status = "开启" if emoji_kill_model else "关闭"
        await bot.api.post_private_msg(msg.user_id, text=f"当前表情歼灭模式为：{status} ")
    if text.startswith("歼灭次数+"):
        number_plus = text[len("歼灭次数+"):].strip()
        if number_plus.isdigit():
            emoji_kill_times += int(number_plus)
        await bot.api.post_private_msg(msg.user_id, text=f"当前歼灭次数为：{emoji_kill_times} 次")
    if text.startswith("歼灭次数-"):
        number_minus = text[len("歼灭次数-"):].strip()
        if number_minus.isdigit():
            if emoji_kill_times > int(number_minus):
                emoji_kill_times -= int(number_minus)
            else:
                emoji_kill_times = 1
        await bot.api.post_private_msg(msg.user_id, text=f"当前歼灭次数为：{emoji_kill_times} 次")
@bot.private_event()
@bot_state.ignore_if_sleeping(allow_uins=bot_state.ADMIN_UINS)
async def admin_message_control(msg: PrivateMessage):
    text = msg.raw_message
    if text == "812睡觉":
        await bot.api.post_private_msg(msg.user_id, text="哦呀斯密....")
        bot_state.set_sleep(True)
    if text == "812起床":
        bot_state.set_sleep(False)
        await bot.api.post_private_msg(msg.user_id, text="嗯——早上好喵呜喵呜~")

@bot.group_event()
@bot_state.ignore_if_sleeping(allow_uins=bot_state.ADMIN_UINS)
async def on_group_message(msg: GroupMessage):
    text = msg.raw_message
    if text == "812睡觉":
        await bot.api.post_group_msg(msg.group_id, text="哦呀斯密....")
        bot_state.set_sleep(True)
    if text == "812起床":
        bot_state.set_sleep(False)
        await bot.api.post_group_msg(msg.group_id, text="嗯——早上好喵呜喵呜~")
@bot.on_notice() # type: ignore
@bot_state.ignore_if_sleeping()
async def on_notice1(event: NoticeEvent):
    # 监听戳一戳事件
    if event.sub_type == 'poke':
        if event.target_id == event.self_id:
            for _ in range(5):
                try:
                    await bot.api.send_poke(user_id=event.user_id, group_id=event.group_id)
                except Exception:
                    pass
                await asyncio.sleep(cyc_wait_time)
@bot.on_notice() # type: ignore
@bot_state.ignore_if_sleeping()
async def emoji_killer(event: NoticeEvent):
        # 监听贴表情事件
    if event.notice_type == 'group_msg_emoji_like':        
        if event.is_add :
            try:
                if event.user_id != bot_state.MASTER_UIN or event.target_id == bot_state.MASTER_UIN:
                    return
            except Exception:
                return
        else:
            return
         #！！！！之前的bug，找到原因了，是参数不匹配导致的！！！！
        global emoji_kill_model
        if emoji_kill_model == False:
            try:
                #await bot.api.send_poke(user_id=event.user_id, group_id=event.group_id)
                #await bot.api.post_group_msg(group_id=event.group_id, text="糖")
                await bot.api.set_msg_emoji_like(message_id=event.message_id, emoji_id=event.emoji_like_id, set=True)
            except Exception:
                pass
            return
        else:
            for i in range(emoji_kill_times):
                
                try:
                    await bot.api.set_msg_emoji_like(message_id=event.message_id, emoji_id=event.emoji_like_id, set=True)
                    await asyncio.sleep(emoji_wait_time)
                    await bot.api.set_msg_emoji_like(message_id=event.message_id, emoji_id=event.emoji_like_id, set=False)
                except Exception:
                    pass
   
    
    
# ========== 启动 BotClient==========
bot.run()

