# ========= 导入必要模块 ==========
import sys
from pathlib import Path
# 将项目根和 plugins/as812 添加到 sys.path，保证老式相对导入能被解析
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
# 保留项目根路径，避免把插件目录直接加入 sys.path
# 这样包内的相对导入（例如 "..models"）才能正常工作

from ncatbot.core import BotClient, PrivateMessage,GroupMessage,NoticeEvent, MessageArray
from ncatbot.utils import config
from ncatbot.plugin_system import root_filter, admin_filter, on_group_increase
from ncatbot.utils import ncatbot_config
import asyncio
import bot_state
import random
import os
import yaml
import re
from plugins.as812.responses.CatCatRes import cat_cat_response
from plugins.as812.core.log_manager import LogManager
from plugins.as812.core.config_manager import ConfigManager
from plugins.as812.models.message_models import BotResponse
from ncatbot.core.event.message_segment import Face
import base64
import time
import json
from pathlib import Path
from uapi import UapiClient
from uapi.errors import UapiError
# ========== 创建 BotClient ==========
bot = BotClient()
ncatbot_config.debug = False  # 启用调试模式
# 配置：设置轮询等待时间（秒）
cyc_wait_time = 0.2
# 配置：表情歼灭模式
emoji_kill_model = False
emoji_kill_times = 8
emoji_wait_time = 0.1
emoji_combo = {147,127827,127853,10068,76,424,12951,63,66,9992}#废
# 配置：戳一戳回击次数
poke_back_times = 1
poke_back_enabled = True
# as812 配置与日志管理器实例（用于戳一戳回复的特殊指令处理）
config_manager = ConfigManager()
log_manager = LogManager()
# 配置：名言警句间隔时间（秒）
famous_words_time = 3600  # 默认1小时

# 名言警句定时任务##############未完成#############
async def send_famous_words():
    client = UapiClient("https://uapis.cn")
    while True:
        try:
            result = client.poem.get_saying()
            # 获取活跃群ID
            try:
                with open("config.yaml", "r", encoding="utf-8") as f:
                    root_config = yaml.safe_load(f)
                    active_group_id = root_config.get("active_group_id")
                if active_group_id:
                    await bot.api.post_group_msg(active_group_id, text=result)
            except Exception as e:
                print(f"发送名言警句失败: {e}")
        except UapiError as exc:
            print(f"API error: {exc}")
        await asyncio.sleep(famous_words_time)


def load_cat_prompt():
    """从 plugins/as812/config/cat_prompt.txt 文件中读取人设 prompt"""
    try:
        with open(os.path.join("plugins", "as812", "config", "cat_prompt.txt"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        try:
            from ncatbot.utils.logger import get_log
            _log = get_log()
            _log.error(f"读取cat_prompt.txt失败: {e}")
        except Exception:
            print(f"读取cat_prompt.txt失败: {e}")
        return ""
# ========= 注册回调函数 ==========
#测试用
@bot.private_event()
@bot_state.ignore_if_sleeping(allow_uins=[bot_state.MASTER_UIN])
async def master_message_control(msg: PrivateMessage):
    global emoji_kill_model, emoji_kill_times, poke_back_enabled, poke_back_times
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
        if text == "戳一戳回击开启":
            poke_back_enabled = True
            await bot.api.post_private_msg(msg.user_id, text="戳一戳回击已开启喵~")
        if text == "戳一戳回击关闭":
            poke_back_enabled = False
            await bot.api.post_private_msg(msg.user_id, text="戳一戳回击已关闭喵~")
        if text == "查询戳一戳回击":
            status = "开启" if poke_back_enabled else "关闭"
            await bot.api.post_private_msg(msg.user_id, text=f"当前戳一戳回击为：{status}，次数：{poke_back_times}")
        if text.startswith("戳一戳回击次数+"):
            number_plus = text[len("戳一戳回击次数+"):].strip()
            if number_plus.isdigit():
                poke_back_times += int(number_plus)
            await bot.api.post_private_msg(msg.user_id, text=f"当前戳一戳回击次数为：{poke_back_times} 次")
        if text.startswith("戳一戳回击次数-"):
            number_minus = text[len("戳一戳回击次数-"):].strip()
            if number_minus.isdigit():
                if poke_back_times > int(number_minus):
                    poke_back_times -= int(number_minus)
                else:
                    poke_back_times = 0
            await bot.api.post_private_msg(msg.user_id, text=f"当前戳一戳回击次数为：{poke_back_times} 次")
        if text == "812睡觉":
            await bot.api.post_private_msg(msg.user_id, text="哦呀斯密....")
            bot_state.set_sleep(True)
        if text == "812起床":
            bot_state.set_sleep(False)
            await bot.api.post_private_msg(msg.user_id, text="嗯——早上好喵呜喵呜~")
        if text == "测试1":
            await bot.api.post_private_msg(msg.user_id, text="[CQ:face,id=66] hi")
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

    if text == "812起床" and bot_state.is_sleeping():
        bot_state.set_sleep(False)
        await bot.api.post_group_msg(msg.group_id, text="嗯——早上好喵呜喵呜~")

    if text.startswith("/名言警句"):
        try:
            file_path = os.path.join(os.path.dirname(__file__), "data", "rgl.txt")
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            if not lines:
                await bot.api.post_group_msg(msg.group_id, text="无话可说")
                return
            
            # 解析次数
            parts = text.split()
            count = 1
            if len(parts) > 1 and parts[1].isdigit():
                count = int(parts[1])
                if count > 10:  # 限制最大次数，避免滥用
                    count = 10
            
            # 发送指定次数的名言警句
            for _ in range(count):
                quote = random.choice(lines)
                await bot.api.post_group_msg(msg.group_id, text=quote)
                if count > 1:
                    await asyncio.sleep(0.5)  # 避免发送太快
        except FileNotFoundError:
            await bot.api.post_group_msg(msg.group_id, text="文件不存在")
@bot.on_notice() # type: ignore
@bot_state.ignore_if_sleeping()
async def on_notice1(event: NoticeEvent):
    # 监听戳一戳事件
    if event.sub_type == 'poke':
        if event.target_id == event.self_id and poke_back_enabled:
            for _ in range(poke_back_times):
                try:
                    await bot.api.send_poke(user_id=event.user_id, group_id=event.group_id)
                except Exception:
                    pass
                await asyncio.sleep(cyc_wait_time)
            
            # 获取API key和prompt，并尝试加载被戳者的个人信息加入到 AI 输入中
            try:
                with open(os.path.join("plugins", "as812", "config", "config.yaml"), "r", encoding="utf-8") as f:
                    cat_config = yaml.safe_load(f)
                    api_key = cat_config.get("api_key")
                cat_prompt = load_cat_prompt()

                # 使用 plugins/as812 的 LogManager 加载个人数据（位置：plugins/as812/logs/{group_id}/{user}.log）
                try:
                    log_manager = LogManager()
                    personal_history, user_info_str, personality_summary, personal_log_path = \
                        log_manager.load_personal_log(str(event.group_id), str(event.user_id))
                except Exception:
                    user_info_str = ""
                    personality_summary = ""

                # 构建chat_history，优先包含被戳者的个人信息和个性总结（如果存在）
                chat_history = []
                if user_info_str:
                    chat_history.append({"role": "system", "content": f"该用户的基本信息：{user_info_str}"})
                if personality_summary:
                    chat_history.append({"role": "system", "content": f"该用户的个性总结：{personality_summary}"})
                chat_history.append({"role": "system", "content": f"有人戳了戳因此812对其进行了{poke_back_times}下回击，812对此有些戏谑性的恼怒"})

                # 生成AI回复
                response = await cat_cat_response(api_key, chat_history, cat_prompt)
                if response:
                    await _send_response_like_as812(event.group_id, response)
            except Exception as e:
                print(f"戳一戳AI回复失败: {e}")
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

    
async def _send_response_like_as812(group_id: int, response: str):
    """模仿 plugins/as812.main.py 的回复发送逻辑，处理 spacial_actions.txt 中的特殊指令。"""
    try:
        pause_multiplier, line_pause_multiplier = config_manager.get_pause_multipliers()
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", response) if p.strip()]
        last_sent_id = None
        assets_dir = Path("plugins") / "as812" / "assests"

        for para in paragraphs:
            lines = [l.strip() for l in para.splitlines() if l.strip()]
            for line in lines:
                m = re.match(r"^##emoji\s*\[?([^\]\s]+)\]?$", line)
                if m:
                    emoji_name = m.group(1)
                    sent = False
                    for ext in (".png", ".jpg", ".jpeg"):
                        img_path = assets_dir / f"{emoji_name}{ext}"
                        if img_path.exists() and img_path.is_file():
                            try:
                                data = img_path.read_bytes()
                                b64 = base64.b64encode(data).decode()
                                res = await bot.api.post_group_msg(group_id, image=f"base64://{b64}")
                            except Exception:
                                res = None

                            if res:
                                last_sent_id = str(res)
                                try:
                                    bot_qq = "812"
                                    bot_resp = BotResponse(timestamp=float(time.time()), message=f"[EMOJI]{emoji_name}", qq=str(bot_qq))
                                    log_manager.save_bot_response(str(group_id), bot_resp)
                                except Exception:
                                    pass

                            sent = True
                            break

                    if not sent:
                        try:
                            res = await bot.api.post_group_msg(group_id, text=f"表情包不存在: {emoji_name}")
                        except Exception:
                            res = None
                        if res:
                            last_sent_id = str(res)
                    continue

                if line == "##revoke":
                    if last_sent_id:
                        try:
                            await bot.api.delete_msg(last_sent_id)
                        except Exception:
                            pass
                    continue

                if line == "##should not say":
                    return

                if line.startswith("##set_emotion "):
                    try:
                        mood_val = line[len("##set_emotion "):].strip()
                        mood_path = os.path.join("plugins", "as812", "logs", f"{group_id}_mood.json")
                        try:
                            os.makedirs(os.path.dirname(mood_path), exist_ok=True)
                            with open(mood_path, "w", encoding="utf-8") as mf:
                                json.dump({"mood": mood_val}, mf, ensure_ascii=False)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    continue

                try:
                    res = await bot.api.post_group_msg(group_id, text=line)
                except Exception:
                    res = None

                if res:
                    last_sent_id = str(res)
                    try:
                        bot_qq = "812"
                        bot_resp = BotResponse(timestamp=float(time.time()), message=line, qq=str(bot_qq))
                        log_manager.save_bot_response(str(group_id), bot_resp)
                    except Exception:
                        pass

                await asyncio.sleep(line_pause_multiplier * max(1, len(line)))

            await asyncio.sleep(pause_multiplier * len(para))
    except Exception as e:
        print(f"发送回复失败: {e}")

# ========== 启动 BotClient==========
bot.run()

