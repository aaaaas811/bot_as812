from ncatbot.utils.logger import get_log
from ncatbot.core.message import GroupMessage
from ncatbot.utils import config

import asyncio
import os
import aiofiles
import yaml
import json
import jieba
import time
from collections import Counter
import random
from .responses.CatCatRes import cat_cat_response
from .personality_summary import summarize_personality
_log = get_log()
def map_role(role):
    role_mapping = {
        "member": "群成员",
        "admin": "管理员",
        "owner": "群主"
    }
    return role_mapping.get(role, role)  # 如果不在映射中，返回原值

def parse_message(msg: GroupMessage) -> dict:
    """解析GroupMessage，返回current_message字典"""
    user_qq = str(msg.sender.user_id)
    # 提取当前消息
    text_content = ""
    force_reply = False
    
    for message in msg.message:
        try:
            mtype = message["type"]
        except Exception:
            mtype = getattr(message, "msg_seg_type", None)

        if mtype == "text":
            txt = None
            if hasattr(message, "text"):
                txt = getattr(message, "text")
            else:
                try:
                    txt = message.get("data", {}).get("text")
                except Exception:
                    txt = None
            if txt:
                text_content += (txt + ",")

        if mtype == "at":
            qq_val = None
            if hasattr(message, "qq"):
                qq_val = getattr(message, "qq")
            else:
                try:
                    qq_val = message.get("data", {}).get("qq")
                except Exception:
                    qq_val = None
            if qq_val is not None and str(qq_val) == str(config.bt_uin):
                text_content = f"@812({config.bt_uin}) " + text_content
                force_reply = True  # 明确@了bot

    # 如果文本中包含 '812' 字样，也视为被提及
    if text_content and not force_reply:  # 只有没有@的时候才检查
        compact = text_content.replace(" ", "")
        if "812" in compact and not ("812睡觉" in compact or "812起床" in compact):
            force_reply = True

    # 提取发送者信息
    card = getattr(msg.sender, "card", "") or ""
    role = getattr(msg.sender, "role", "") or ""
    title = getattr(msg.sender, "title", "") or ""

    current_message = {
        "timestamp": time.time(),
        "nickname": msg.sender.nickname,
        "qq": user_qq,
        "card": card,
        "role": role,
        "title": title,
        "message": text_content.rstrip(','),
        "force_reply": force_reply
    }
    return current_message

async def build_chat_history(gid, current_message, personality_summary):
    """构建chat_history：关键词 + 用户信息 + 群聊历史 + 当前消息"""
    # 读取配置
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            max_history = int(cfg.get("max_history", 100))
            context_history = int(cfg.get("context_history", 50))
            max_words = int(cfg.get("max_words", 5))
            summary_threshold = int(cfg.get("summary_threshold", 50))
    except:
        max_history = 100
        context_history = 50
        max_words = 5
        summary_threshold = 50

    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
    
    # 提取关键词
    keywords = []
    if os.path.exists(group_history_file):
        with open(group_history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            recent_messages = []
            for line in reversed(lines):
                if len(recent_messages) >= max_history:
                    break
                try:
                    obj = json.loads(line.strip())
                    if obj.get("qq") != str(config.bt_uin):
                        recent_messages.append(obj["message"])
                except:
                    continue
            # 提取词语
            all_words = []
            for msg in recent_messages:
                words = jieba.cut(msg)
                all_words.extend([w for w in words if w.strip() and len(w) > 1 and w != "812"])  # 过滤空、单字和"812"
            word_freq = Counter(all_words)
            # 按频率降序，同频率随机
            sorted_words = sorted(word_freq.items(), key=lambda x: (-x[1], random.random()))
            keywords = [w for w, _ in sorted_words[:max_words]]

    # 构建chat_history
    chat_history = []
    
    # 添加关键词
    if keywords:
        keywords_str = "关键高频词（按词频降序排列，来自当前群聊，反应了最近在聊什么话题）: " + ", ".join(keywords)
        chat_history.append({"role": "system", "content": keywords_str})
    
    # 添加用户信息
    user_info = f"用户信息: 昵称={current_message['nickname']}, QQ={current_message['qq']}, 群名片={current_message['card']}, 角色={map_role(current_message['role'])}, 头衔={current_message['title']}"
    if personality_summary:
        user_info += f"\n该用户的个性总结：{personality_summary}"
    chat_history.append({"role": "system", "content": user_info})
    
    # 添加群聊历史
    group_history = []
    if os.path.exists(group_history_file):
        with open(group_history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines):
                if len(group_history) >= context_history:
                    break
                try:
                    obj = json.loads(line.strip())
                    if obj.get("qq") == str(config.bt_uin):
                        group_history.append({"role": "assistant", "content": obj["message"]})
                    else:
                        group_history.append({"role": "user", "content": f"{obj['nickname']}: {obj['message']}"})
                except:
                    continue
        # 反转回时间顺序
        group_history.reverse()
        chat_history.extend(group_history)
    
    # 添加说明
    if group_history:
        chat_history.append({"role": "system", "content": "以上是过往群聊记录（不一定是该用户所说）"})
    
    # 添加当前消息
    chat_history.append({"role": "user", "content": current_message["message"]})
    
    return chat_history, summary_threshold


async def load_personal_data(gid: str, user_qq: str) -> tuple:
    """加载用户的个人数据"""
    personal_log_dir = f"plugins/CatCat/logs/{gid}"
    os.makedirs(personal_log_dir, exist_ok=True)
    personal_log_file = f"{personal_log_dir}/{user_qq}.log"
    
    personal_history = []
    user_info_str = ""
    personality_summary = ""
    
    if os.path.exists(personal_log_file):
        with open(personal_log_file, "r", encoding="utf-8") as f:
            content = f.read()
            # 解析基本信息
            if "该用户的基本信息：" in content:
                start = content.find("该用户的基本信息：") + len("该用户的基本信息：")
                end = content.find("\n\n该用户的个性总结：", start)
                if end == -1:
                    end = content.find("\n\n过往聊天记录：", start)
                user_info_str = content[start:end].strip()
            # 解析个性总结
            if "该用户的个性总结：" in content:
                start = content.find("该用户的个性总结：") + len("该用户的个性总结：")
                end = content.find("\n\n过往聊天记录：", start)
                if end == -1:
                    end = len(content)
                personality_summary = content[start:end].strip()
            # 解析聊天记录
            if "过往聊天记录：" in content:
                records_start = content.find("过往聊天记录：") + len("过往聊天记录：")
                records = content[records_start:].strip().split("\n")
                # 保留完整的消息格式
                personal_history = [line.strip() for line in records if line.strip()]
    else:
        # 首次创建，写入基本信息
        user_info_str = f"QQ昵称: 未知, QQ号: {user_qq}, 群昵称: , 群权限: , 群头衔: "
        initial_content = f"该用户的基本信息：{user_info_str}\n\n该用户的个性总结：\n\n过往聊天记录：\n"
        with open(personal_log_file, "w", encoding="utf-8") as f:
            f.write(initial_content)
    
    return personal_history, user_info_str, personality_summary, personal_log_file

def self_update_personal_log(personal_log_file, user_info_str, personality_summary, personal_history):
    """统一更新个人日志文件"""
    # 构建完整内容
    content = f"该用户的基本信息：{user_info_str}\n\n"
    content += f"该用户的个性总结：{personality_summary}\n\n"
    content += "过往聊天记录：\n"
    content += "\n".join(personal_history) + "\n"
    
    # 写入文件
    with open(personal_log_file, "w", encoding="utf-8") as f:
        f.write(content)

def should_reply(current_message: dict) -> bool:
    """
    判断是否应该回复用户消息
    
    返回 True 的情况：
    1. 消息中明确@了bot
    2. 消息中包含"812"且不是"812睡觉"或"812起床"
    3. 消息中有"force_reply"标记为True
    
    返回 False 的情况：
    1. 是命令消息（以"/"开头）
    2. 没有触发条件
    """
    message = current_message.get("message", "")
    force_reply = current_message.get("force_reply", False)
    
    # 检查是否是命令
    if message.strip().startswith("/"):
        return False
    
    # 检查是否@了bot（在parse_message中已经处理了）
    if force_reply:
        return True
    
    # 检查是否包含"812"且不是特定指令
    if "812" in message:
        # 排除睡觉/起床指令
        compact = message.replace(" ", "")
        if not ("812睡觉" in compact or "812起床" in compact):
            return True
    
    return False

async def active_response(api_key, cat_prompt, group_id):
    """主动回复：获取最新的用户消息并生成回复"""
    gid = group_id
    if gid is None:
        try:
            with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as _f:
                cfg = yaml.safe_load(_f) or {}
                gid = cfg.get("active_group_id")
        except Exception:
            gid = None
    if gid is None:
        _log.warning("未提供 group_id，无法主动回复")
        return
    
    # 读取配置文件获取基础设置
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            base_delay = int(config.get("active_reply_delay", 900))
            current_delay = int(config.get("current_active_delay", 0))
            random_range = float(config.get("random_range", 0.2))
            bt_uin = str(config.get("bt_uin", ""))
    except:
        base_delay = 900
        current_delay = 0
        random_range = 0.2
        bt_uin = ""
    
    # 如果当前延迟为0（第一次运行），使用基础延迟作为初始值
    if current_delay <= 0:
        current_delay = random.randint(
            int(base_delay * (1 - random_range)), 
            int(base_delay * (1 + random_range))
        )
        try:
            config["current_active_delay"] = current_delay
            with open("plugins/CatCat/config/config.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False)
        except:
            pass
    
    current_time = time.time()
    last_bot_message_time = 0
    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
    
    # 读取群历史文件，获取机器人最后一条消息的时间
    if os.path.exists(group_history_file):
        try:
            with open(group_history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    try:
                        obj = json.loads(line.strip())
                        if bt_uin and obj.get("qq") == bt_uin:
                            timestamp = obj.get("timestamp")
                            if timestamp:
                                last_bot_message_time = float(timestamp)
                                break
                    except:
                        continue
        except Exception as e:
            _log.warning(f"读取群历史文件失败: {e}")
            last_bot_message_time = current_time
    
    # 如果从未发送过消息，直接跳过
    if last_bot_message_time == 0:
        _log.info("主动回复：机器人从未发送过消息，跳过本次主动回复")
        return
    
    # 计算距离上次回复的时间
    time_since_last_reply = current_time - last_bot_message_time
    
    # 只有当距离机器人最后回复的时间超过延迟时才主动回复
    if time_since_last_reply < current_delay:
        _log.info(f"主动回复：距离机器人最后回复 {time_since_last_reply:.1f} 秒，随机延迟 {current_delay} 秒未到，跳过")
        return
    
    _log.info(f"主动回复：距离上次回复 {time_since_last_reply:.1f} 秒，已超过延迟 {current_delay} 秒，开始处理")
    
    # 获取群历史最新的用户消息
    try:
        current_message = None
        user_qq = None
        
        if os.path.exists(group_history_file):
            with open(group_history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    try:
                        obj = json.loads(line.strip())
                        if (bt_uin and obj.get("qq") != bt_uin and 
                            not obj.get("message", "").startswith("/")):
                            current_message = obj
                            user_qq = obj.get("qq")
                            break
                    except:
                        continue
        
        if not current_message:
            _log.warning("无合适的新消息，无法主动回复")
            return
            
    except FileNotFoundError:
        _log.warning("群历史文件不存在，无法主动回复")
        return
    
    # 加载个人数据
    personal_history, user_info_str, personality_summary, personal_log_file = await load_personal_data(gid, user_qq)
    
    # ========== 统一处理消息记录 ==========
    # 记录用户消息到个人日志
    user_message_line = f"用户：{current_message['message']}"
    personal_history.append(user_message_line)
    
    # 更新用户信息
    current_user_info = f"QQ昵称: {current_message['nickname']}, QQ号: {current_message['qq']}, 群昵称: {current_message['card']}, 群权限: {map_role(current_message['role'])}, 群头衔: {current_message['title']}"
    if user_info_str != current_user_info and personal_log_file:
        user_info_str = current_user_info
    
    # 更新个人日志文件（先记录用户消息）
    self_update_personal_log(personal_log_file, user_info_str, personality_summary, personal_history)
    
    # 构建chat_history
    chat_history, summary_threshold = await build_chat_history(gid, current_message, personality_summary)
    
    # 检查聊天记录数量，如果 >= summary_threshold，调用总结
    if len(personal_history) >= summary_threshold and personal_log_file:
        await summarize_personality(personal_log_file, api_key, user_info_str)
        # 重新加载，清空聊天记录
        personal_history = []
        # 重新添加当前消息
        personal_history.append(user_message_line)
    
    # 生成回复
    _log.info("开始主动生成回复……")
    if response := await cat_cat_response(api_key, chat_history, cat_prompt):
        _log.info(f"812：{response}")
        
        # 将812的回复添加到个人历史
        bot_message_line = f"812：{response}"
        personal_history.append(bot_message_line)
        
        # 更新个人日志文件（包含用户消息和bot回复）
        self_update_personal_log(personal_log_file, user_info_str, personality_summary, personal_history)
        
        # 写入群历史
        bot_record = {
            "timestamp": time.time(),
            "nickname": "812",
            "qq": bt_uin,
            "card": "",
            "role": "",
            "title": "",
            "message": response
        }
       
        with open(group_history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(bot_record, ensure_ascii=False) + "\n")
        
        # 生成新的随机延迟用于下次
        try:
            new_delay = random.randint(int(base_delay * 0.8), int(base_delay * 1.2))
            config["current_active_delay"] = new_delay
            with open("plugins/CatCat/config/config.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False)
            _log.info(f"主动回复成功，已生成新的随机延迟：{new_delay} 秒")
        except Exception as e:
            _log.warning(f"生成新的随机延迟失败：{e}")
        
        return response
    else:
        _log.warning("生成回复失败")
        return
    """主动回复：获取最新的用户消息并生成回复"""
    gid = group_id
    if gid is None:
        try:
            with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as _f:
                cfg = yaml.safe_load(_f) or {}
                gid = cfg.get("active_group_id")
        except Exception:
            gid = None
    if gid is None:
        _log.warning("未提供 group_id，无法主动回复")
        return
    
    # 先检查active_reply_delay，避免不必要的文件读取
    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
    
    # 读取配置文件获取基础设置
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            base_delay = int(config.get("active_reply_delay", 900))
            current_delay = int(config.get("current_active_delay", 0))
            random_range = float(config.get("random_range", 0.2))
            bt_uin = str(config.get("bt_uin", ""))  # 获取机器人QQ
    except:
        base_delay = 900
        current_delay = 0
        random_range = 0.2
        bt_uin = ""
    
    # 如果当前延迟为0（第一次运行），使用基础延迟作为初始值
    if current_delay <= 0:
        current_delay = random.randint(
            int(base_delay * (1 - random_range)), 
            int(base_delay * (1 + random_range))
        )
        # 保存新的延迟
        try:
            config["current_active_delay"] = current_delay
            with open("plugins/CatCat/config/config.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False)
        except:
            pass
    
    current_time = time.time()
    last_bot_message_time = 0
    
    # 读取群历史文件，获取机器人最后一条消息的时间
    if os.path.exists(group_history_file):
        try:
            with open(group_history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):  # 从后往前查找
                    try:
                        obj = json.loads(line.strip())
                        # 只检查机器人自己的消息时间
                        if bt_uin and obj.get("qq") == bt_uin:
                            timestamp = obj.get("timestamp")
                            if timestamp:
                                last_bot_message_time = float(timestamp)
                                break
                    except:
                        continue
        except Exception as e:
            _log.warning(f"读取群历史文件失败: {e}")
            last_bot_message_time = current_time  # 如果读取失败，设置为当前时间
    
    # 关键修复：如果从未发送过消息，直接跳过本次主动回复
    # 这样可以避免机器人一启动就立即主动回复
    if last_bot_message_time == 0:
        _log.info("主动回复：机器人从未发送过消息，跳过本次主动回复")
        return
    
    # 计算距离上次回复的时间
    time_since_last_reply = current_time - last_bot_message_time
    
    # 只有当距离机器人最后回复的时间超过延迟时才主动回复
    if time_since_last_reply < current_delay:
        _log.info(f"主动回复：距离机器人最后回复 {time_since_last_reply:.1f} 秒，随机延迟 {current_delay} 秒未到，跳过")
        return
    
    _log.info(f"主动回复：距离上次回复 {time_since_last_reply:.1f} 秒，已超过延迟 {current_delay} 秒，开始处理")
    
    # 获取群历史最新的用户消息
    try:
        current_message = None
        user_qq = None
        
        if os.path.exists(group_history_file):
            with open(group_history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    try:
                        obj = json.loads(line.strip())
                        # 排除机器人自己的消息和命令消息
                        if (bt_uin and obj.get("qq") != bt_uin and 
                            not obj.get("message", "").startswith("/")):
                            current_message = obj
                            user_qq = obj.get("qq")
                            break
                    except:
                        continue
        
        if not current_message:
            _log.warning("无合适的新消息，无法主动回复")
            return
            
    except FileNotFoundError:
        _log.warning("群历史文件不存在，无法主动回复")
        return
    
    # 加载个人数据
    personal_history, user_info_str, personality_summary, personal_log_file = await load_personal_data(gid, user_qq)
    
    # 记录用户消息到个人日志（主动回复时记录当前消息）
    if personal_log_file:
        with open(personal_log_file, "a", encoding="utf-8") as f:
            f.write(current_message["message"] + "\n")
    
    # 更新用户信息
    current_user_info = f"QQ昵称: {current_message['nickname']}, QQ号: {current_message['qq']}, 群昵称: {current_message['card']}, 群权限: {map_role(current_message['role'])}, 群头衔: {current_message['title']}"
    if user_info_str != current_user_info and personal_log_file:
        # 更新个人日志的header
        try:
            with open(personal_log_file, "r", encoding="utf-8") as f:
                content = f.read()
            if "该用户的基本信息：" in content:
                new_content = content.replace(f"该用户的基本信息：{user_info_str}", f"该用户的基本信息：{current_user_info}")
                with open(personal_log_file, "w", encoding="utf-8") as f:
                    f.write(new_content)
        except Exception as e:
            _log.warning(f"更新用户信息失败: {e}")
    
    # 构建chat_history
    chat_history, summary_threshold = await build_chat_history(gid, current_message, personality_summary)
    
    # 生成回复
    _log.info("开始主动生成回复……")
    response = await cat_cat_response(api_key, chat_history, cat_prompt)
    if response :
        
        # 更新个人日志的聊天记录
        if len(personal_history) >= summary_threshold and personal_log_file:
            await summarize_personality(personal_log_file, api_key, user_info_str)
            # 重新加载，清空聊天记录
            personal_history = []
        
        # 更新个人日志的聊天记录部分
        if personal_history and personal_log_file:
            # 读取现有内容
            with open(personal_log_file, "r", encoding="utf-8") as f:
                content = f.read()
            # 分割内容
            parts = content.split("\n\n过往聊天记录：\n")
            if len(parts) == 2:
                header = parts[0] + "\n\n过往聊天记录：\n"
                # 写入更新后的内容
                with open(personal_log_file, "w", encoding="utf-8") as f:
                    f.write(header + "\n".join(personal_history) + "\n")
        
        # 写入个人日志
        if personal_log_file:
            with open(personal_log_file, "a", encoding="utf-8") as f:
                f.write("812：" + response + "\n")
        
        # 写入群历史
        bot_record = {
            "timestamp": time.time(),
            "nickname": "812",
            "qq": bt_uin,
            "card": "",
            "role": "",
            "title": "",
            "message": response
        }
       
        with open(group_history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(bot_record, ensure_ascii=False) + "\n")
        
        # 主动回复成功后，生成新的随机延迟用于下次
        try:
            new_delay = random.randint(int(base_delay * 0.8), int(base_delay * 1.2))
            config["current_active_delay"] = new_delay
            with open("plugins/CatCat/config/config.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False)
            _log.info(f"主动回复成功，已生成新的随机延迟：{new_delay} 秒")
        except Exception as e:
            _log.warning(f"生成新的随机延迟失败：{e}")
        
        return response
    else:
        _log.warning("生成回复失败")
        return

async def gene_response(api_key, msg: GroupMessage = None, cat_prompt=None):
    # 只处理被动回复：由群消息触发（传入 msg）
    if msg is None:
        raise ValueError("gene_response 现在只支持被动回复，请使用 active_response 进行主动回复")
    
    current_message = parse_message(msg)
    gid = msg.group_id
    user_qq = current_message["qq"]
    
    # 加载个人数据
    personal_history, user_info_str, personality_summary, personal_log_file = await load_personal_data(gid, user_qq)
    
    # 更新用户信息
    current_user_info = f"QQ昵称: {current_message['nickname']}, QQ号: {current_message['qq']}, 群昵称: {current_message['card']}, 群权限: {map_role(current_message['role'])}, 群头衔: {current_message['title']}"
    if user_info_str != current_user_info:
        # 更新个人日志的header
        with open(personal_log_file, "r", encoding="utf-8") as f:
            content = f.read()
        if "该用户的基本信息：" in content:
            new_content = content.replace(f"该用户的基本信息：{user_info_str}", f"该用户的基本信息：{current_user_info}")
            with open(personal_log_file, "w", encoding="utf-8") as f:
                f.write(new_content)
        user_info_str = current_user_info
    
    # ========== 统一处理消息记录 ==========
    # 无论是否触发回复，都先记录用户消息
    user_message_line = f"用户：{current_message['message']}"
    
    # 将用户消息添加到个人历史
    personal_history.append(user_message_line)
    
    # 更新个人日志文件
    self_update_personal_log(personal_log_file, user_info_str, personality_summary, personal_history)
    
    # 记录用户消息到群历史
    user_record = {
        "timestamp": time.time(),
        "nickname": current_message["nickname"],
        "qq": current_message["qq"],
        "card": current_message["card"],
        "role": current_message["role"],
        "title": current_message["title"],
        "message": current_message["message"]
    }
    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
    with open(group_history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(user_record, ensure_ascii=False) + "\n")
    
    # ========== 判断是否应该回复 ==========
    def should_reply(current_message: dict) -> bool:
        """判断是否应该回复用户消息"""
        message = current_message.get("message", "")
        force_reply = current_message.get("force_reply", False)
        
        # 检查是否是命令
        if message.strip().startswith("/"):
            return False
        
        # 检查是否@了bot
        if force_reply:
            return True
        
        # 检查是否包含"812"且不是特定指令
        if "812" in message:
            compact = message.replace(" ", "")
            if not ("812睡觉" in compact or "812起床" in compact):
                return True
        
        # 随机回复（5%概率）
        if random.random() < 0.05:
            _log.info("随机触发回复")
            return True
        
        return False
    
    should_reply_flag = should_reply(current_message)
    
    # 如果不应该回复，直接返回
    if not should_reply_flag:
        _log.info(f"消息不触发回复，仅记录：{current_message['message'][:50]}...")
        return None
    
    # ========== 需要回复的处理逻辑 ==========
    # 构建chat_history
    chat_history, summary_threshold = await build_chat_history(gid, current_message, personality_summary)
    
    # 检查聊天记录数量，如果 >= summary_threshold，调用总结
    if len(personal_history) >= summary_threshold:
        await summarize_personality(personal_log_file, api_key, user_info_str)
        # 重新加载，清空聊天记录
        personal_history = []
        # 重新添加当前消息
        personal_history.append(user_message_line)
    
    # 生成回复
    _log.info("开始生成回复……")
    if response := await cat_cat_response(api_key, chat_history, cat_prompt):
        _log.info(f"812：{response}")
        
        # 将812的回复添加到个人历史
        bot_message_line = f"812：{response}"
        personal_history.append(bot_message_line)
        
        # 更新个人日志文件（包含用户消息和bot回复）
        self_update_personal_log(personal_log_file, user_info_str, personality_summary, personal_history)
        
        # 将机器人回复写入群历史
        bot_record = {
            "timestamp": time.time(),
            "nickname": "812",
            "qq": str(config.bt_uin),
            "card": "",
            "role": "",
            "title": "",
            "message": response
        }
        with open(group_history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(bot_record, ensure_ascii=False) + "\n")
        
        return response
    
    return None
    # 只处理被动回复：由群消息触发（传入 msg）
    if msg is None:
        raise ValueError("gene_response 现在只支持被动回复，请使用 active_response 进行主动回复")
    
    current_message = parse_message(msg)
    gid = msg.group_id
    user_qq = current_message["qq"]
    
    # 加载个人数据
    personal_history, user_info_str, personality_summary, personal_log_file = await load_personal_data(gid, user_qq)
    
    # 更新用户信息
    current_user_info = f"QQ昵称: {current_message['nickname']}, QQ号: {current_message['qq']}, 群昵称: {current_message['card']}, 群权限: {map_role(current_message['role'])}, 群头衔: {current_message['title']}"
    if user_info_str != current_user_info:
        # 更新个人日志的header
        with open(personal_log_file, "r", encoding="utf-8") as f:
            content = f.read()
        if "该用户的基本信息：" in content:
            new_content = content.replace(f"该用户的基本信息：{user_info_str}", f"该用户的基本信息：{current_user_info}")
            with open(personal_log_file, "w", encoding="utf-8") as f:
                f.write(new_content)
        user_info_str = current_user_info
    
    # 定义个人日志文件路径
    personal_log_dir = f"plugins/CatCat/logs/{gid}"
    os.makedirs(personal_log_dir, exist_ok=True)
    personal_log_file = f"{personal_log_dir}/{user_qq}.log"
    
    # 判断是否需要回复
    should_reply_flag = should_reply(current_message)
    
    # 总是记录用户消息到个人日志（格式：用户：+消息）
    with open(personal_log_file, "a", encoding="utf-8") as f:
        f.write(f"用户：{current_message['message']}\n")
    
    # 记录用户消息到群历史
    user_record = {
        "timestamp": time.time(),
        "nickname": current_message["nickname"],
        "qq": current_message["qq"],
        "card": current_message["card"],
        "role": current_message["role"],
        "title": current_message["title"],
        "message": current_message["message"]
    }
    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
    with open(group_history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(user_record, ensure_ascii=False) + "\n")
    
    # 如果不应该回复，直接返回
    if not should_reply_flag:
        _log.info(f"消息不触发回复，仅记录：{current_message['message'][:50]}...")
        return None
    
    # ============= 以下部分只有需要回复时才执行 =============
    
    # 构建chat_history
    chat_history, summary_threshold = await build_chat_history(gid, current_message, personality_summary)
    
    # 检查聊天记录数量，如果 >= summary_threshold，调用总结
    if len(personal_history) >= summary_threshold:
        await summarize_personality(personal_log_file, api_key, user_info_str)
        # 重新加载，清空聊天记录
        personal_history = []
    
    # 更新个人日志的聊天记录部分
    if personal_history:
        # 读取现有内容
        with open(personal_log_file, "r", encoding="utf-8") as f:
            content = f.read()
        # 分割内容
        parts = content.split("\n\n过往聊天记录：\n")
        if len(parts) == 2:
            header = parts[0] + "\n\n过往聊天记录：\n"
            # 写入更新后的内容
            with open(personal_log_file, "w", encoding="utf-8") as f:
                f.write(header + "\n".join(personal_history) + "\n")
    
    _log.info("开始生成回复……")
    if response := await cat_cat_response(api_key, chat_history, cat_prompt):
        _log.info(f"812：{response}")
        
        # 将812的回复写入个人日志
        with open(personal_log_file, "a", encoding="utf-8") as f:
            f.write(f"812：{response}\n")
        
        # 将机器人回复写入群历史
        bot_record = {
            "timestamp": time.time(),
            "nickname": "812",
            "qq": str(config.bt_uin),
            "card": "",
            "role": "",
            "title": "",
            "message": response
        }
        with open(group_history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(bot_record, ensure_ascii=False) + "\n")
        
        return response
    
    return None