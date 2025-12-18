# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, PrivateMessage,GroupMessage,NoticeEvent, MessageArray
from ncatbot.utils import config
from ncatbot.plugin_system import root_filter, admin_filter, on_group_increase
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
#测试用
@bot.private_event()
@bot_state.ignore_if_sleeping(allow_uins=[bot_state.MASTER_UIN])
async def master_message_control(msg: PrivateMessage):
    global emoji_kill_model, emoji_kill_times
    text = msg.raw_message
    if msg.user_id == bot_state.MASTER_UIN:
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
        if text == "812睡觉":
            await bot.api.post_private_msg(msg.user_id, text="哦呀斯密....")
            bot_state.set_sleep(True)
        if text == "812起床":
            bot_state.set_sleep(False)
            await bot.api.post_private_msg(msg.user_id, text="嗯——早上好喵呜喵呜~")
#普通用户私聊回复
@bot.private_event()
@bot_state.ignore_if_sleeping()
async def on_private_message(msg: PrivateMessage):
    text = msg.raw_message
    if(msg.user_id != bot_state.MASTER_UIN):
        await bot.api.post_private_msg(msg.user_id, text="811现在不让我和别人说话")
@bot.group_event()
@bot_state.ignore_if_sleeping(allow_uins=bot_state.ADMIN_UINS, allow_group_admins=True)
async def on_group_message(msg: GroupMessage):
    text = msg.raw_message
    if text == "812睡觉":
        # 检查权限：只有管理员或指定用户能让bot睡觉
        if str(msg.user_id) not in bot_state.ADMIN_UINS and not (hasattr(msg, 'sender') and getattr(msg.sender, 'role', None) in ['owner', 'admin']):
            await bot.api.post_group_msg(msg.group_id, text="我才不听你的")
            return
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
@bot.on_notice() # type: ignore
@bot_state.ignore_if_sleeping()
async def on_group_member_join(event: NoticeEvent):
    # 监听群成员加入事件
    if event.notice_type == 'group_increase':
        welcome_msg = f"新天尊玩什么太刀"
        await bot.api.post_group_msg(group_id=event.group_id, text=welcome_msg)

    
# ========== 启动 BotClient==========
bot.run()

