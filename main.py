# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, PrivateMessage,GroupMessage,NoticeEvent, MessageArray
from ncatbot.utils import config
import asyncio
# ========== 创建 BotClient ==========
bot = BotClient()
cyc_wait_time = 0.2
# 配置：将这里的账号 ID 替换为你要监控的“账号 A”QQ 号（字符串或整数都可）
ACCOUNT_A_ID = '3196611630'

# ========= 注册回调函数 ==========
@bot.private_event()
async def on_private_message(msg: PrivateMessage):
    if msg.raw_message == "测试":
        await bot.api.post_private_msg(msg.user_id, text="NcatBot 测试成功喵~")
@bot.group_event()
async def on_group_message(msg: GroupMessage):
    # 与 on_private_message 类似：收到 @ 机器人的消息时，回复固定文本
    try:
        # event.message 是 MessageArray，可迭代
        for seg in getattr(event, 'message', []) or []:
            seg_type = getattr(seg, 'type', None) if not isinstance(seg, dict) else seg.get('type')
            if seg_type != 'at':
                continue
            data = getattr(seg, 'data', None) if not isinstance(seg, dict) else seg.get('data', {})
            qq = None
            if isinstance(data, dict):
                qq = data.get('qq') or data.get('user_id')
            else:
                qq = getattr(data, 'qq', None) if data else None

            # 使用事件中自己的 id 进行比较，避免依赖外部 config
            if qq is not None and str(qq) == str(getattr(event, 'self_id', None)):
                await bot.api.post_group_msg(getattr(event, 'group_id', None), text="你叫我吗？喵~")
                return
    except Exception:
        return
@bot.on_notice() # type: ignore
async def on_notice(event: NoticeEvent):
    # 兼容不同版本的字段名
    notice = getattr(event, 'sub_type', None) or getattr(event, 'notice_type', None)
    is_add = getattr(event, 'is_add', None)
    emoji_like_id = getattr(event, 'emoji_like_id', None)
    liker = getattr(event, 'user_id', None)

    # (已移除调试输出)

    # 监听消息的表情回应
    if notice == 'group_msg_emoji_like':
        # 只对账号A的新增表情回应作出反应
        if is_add :
            # 类型安全比较（避免 int/str 导致的不匹配）
            try:
                if str(liker) != str(ACCOUNT_A_ID):
                    return
            except Exception:
                return

            # 在这里执行你希望的动作（示例：发送戳一戳或发送群消息）
    #！！！！之前的bug，找到原因了，是因为参数不匹配导致的！！！！
            try:
                #await bot.api.send_poke(user_id=getattr(event, 'user_id', None), group_id=getattr(event, 'group_id', None))
                #await bot.api.post_group_msg(group_id=getattr(event, 'group_id', None), text="糖")
                await bot.api.set_msg_emoji_like(message_id=getattr(event, 'message_id', None), emoji_id=emoji_like_id, set=is_add)
            except Exception:
                pass
            return

    # 监听 poke（戳一戳）事件
    if notice == 'poke':
        if getattr(event, 'target_id', None) == getattr(event, 'self_id', None):
            for i in range(5):
                try:
                    await bot.api.send_poke(user_id=getattr(event, 'user_id', None), group_id=getattr(event, 'group_id', None))
                except Exception:
                    pass
                await asyncio.sleep(cyc_wait_time)
    
# ========== 启动 BotClient==========
bot.run()

