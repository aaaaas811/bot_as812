from ncatbot.utils.logger import get_log
from ncatbot.core.message import GroupMessage
from ncatbot.utils import config

import asyncio
import os
import aiofiles
import yaml
import json
import jieba
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

global_chat_histories = []


async def gene_response(api_key, msg: GroupMessage = None, cat_prompt=None, group_id: str = None):
    # 支持两种调用方式：由群消息触发（传入 msg），或定时/主动触发（传入 group_id 或使用 config 中 manager_id）
    if msg is not None:
        gid = msg.group_id
        user_qq = str(msg.sender.user_id)
        # 提取当前消息
        text_content = ""
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

        # 如果文本中包含 '812' 字样，也视为被提及
        force_reply = False
        if text_content:
            compact = text_content.replace(" ", "")
            if "812" in compact and not ("812睡觉" in compact or "812起床" in compact):
                force_reply = True

        # 提取发送者信息
        card = getattr(msg.sender, "card", "") or ""
        role = getattr(msg.sender, "role", "") or ""
        title = getattr(msg.sender, "title", "") or ""

        current_message = {
            "timestamp": asyncio.get_event_loop().time(),
            "nickname": msg.sender.nickname,
            "qq": user_qq,
            "card": card,
            "role": role,
            "title": title,
            "message": text_content
        }
    else:
        gid = group_id
        if gid is None:
            try:
                with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as _f:
                    cfg = yaml.safe_load(_f) or {}
                    gid = cfg.get("manager_id")
            except Exception:
                gid = None
        if gid is None:
            _log.warning("未提供 group_id，无法定位历史文件")
            return
        user_qq = gid  # 主动时使用manager_id作为qq

        # 主动模式：获取群历史最后一条消息作为当前消息
        group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
        try:
            with open(group_history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    try:
                        obj = json.loads(line.strip())
                        if not obj["message"].startswith("/"):
                            current_message = obj
                            break
                    except:
                        continue
                else:
                    _log.warning("群历史为空或只有命令，无法主动回复")
                    return
        except FileNotFoundError:
            _log.warning("群历史文件不存在，无法主动回复")
            return

    # 计算群历史最后消息时间，用于message_delay检查
    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
    last_group_message_time = 0
    if os.path.exists(group_history_file):
        try:
            with open(group_history_file, "r", encoding="utf-8") as f:
                for line in reversed(list(f)):
                    try:
                        obj = json.loads(line.strip())
                        last_group_message_time = float(obj.get("timestamp", 0))
                        break
                    except:
                        continue
        except:
            pass

    current_time = asyncio.get_event_loop().time()
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            message_delay = int(yaml.safe_load(f)["message_delay"])
    except:
        message_delay = 10
    if current_time - last_group_message_time < message_delay and not (msg is not None and force_reply):
        return

    # 个人日志文件
    personal_log_dir = f"plugins/CatCat/logs/{gid}"
    os.makedirs(personal_log_dir, exist_ok=True)
    personal_log_file = f"{personal_log_dir}/{user_qq}.log"

    # 加载个人历史
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
                personal_history = [line.strip() for line in records if line.strip()]
    else:
        # 首次创建，写入基本信息
        user_info_str = f"QQ昵称: {current_message['nickname']}, QQ号: {current_message['qq']}, 群昵称: {current_message['card']}, 群权限: {map_role(current_message['role'])}, 群头衔: {current_message['title']}"
        initial_content = f"该用户的基本信息：{user_info_str}\n\n该用户的个性总结：\n\n过往聊天记录：\n"
        with open(personal_log_file, "w", encoding="utf-8") as f:
            f.write(initial_content)

    # 提取关键词
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            max_history = int(cfg.get("max_history", 100))
            max_words = int(cfg.get("max_words", 5))
            summary_threshold = int(cfg.get("summary_threshold", 10))
    except:
        max_history = 100
        max_words = 5
        summary_threshold = 10

    group_history_file = f"plugins/CatCat/logs/{gid}_history.log"
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

    # 构建chat_history: 个人历史 + 关键词 + 用户信息 + 当前消息
    chat_history = []
    chat_history.append("个人的过往聊天记录（不一定是最近发生的）：")
    for h in personal_history:
        chat_history.append(h)    
        if personality_summary:
            chat_history.append(f"该用户的个性总结：{personality_summary}")    
        if keywords:
            keywords_str = "关键高频词（按词频降序排列，来自当前群聊，反应了最近在聊什么话题）: " + ", ".join(keywords)
        chat_history.append(keywords_str)
    # 添加用户信息
    user_info = f"用户信息: 昵称={current_message['nickname']}, QQ={current_message['qq']}, 群名片={current_message['card']}, 角色={map_role(current_message['role'])}, 头衔={current_message['title']}"
    chat_history.append(user_info)
    # 当前消息标识为用户
    chat_history.append("用户: " + current_message["message"])

    _log.info("开始生成回复……")
    if response := await cat_cat_response(api_key, chat_history, cat_prompt):
        _log.info(f"812：{response}")
    else:
        return

    # 存储当前消息到个人日志（如果不是主动模式）
    if msg is not None:
        # 检查聊天记录数量，如果 >= summary_threshold，调用总结
        if len(personal_history) >= summary_threshold:
            await summarize_personality(personal_log_file, api_key, user_info_str)
            # 重新加载，清空聊天记录
            personal_history = []
        # 写入新消息
        with open(personal_log_file, "a", encoding="utf-8") as f:
            f.write("用户：" + current_message["message"] + "\n")
        # 也将当前消息写入群历史
        with open(group_history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(current_message, ensure_ascii=False) + "\n")

    # 将机器人回复也写入群历史
    bot_record = {
        "timestamp": asyncio.get_event_loop().time(),
        "nickname": "812",
        "qq": str(config.bt_uin),
        "card": "",
        "role": "",
        "title": "",
        "message": response
    }
    with open(group_history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(bot_record, ensure_ascii=False) + "\n")

    # 也将机器人回复写入个人日志
    with open(personal_log_file, "a", encoding="utf-8") as f:
        f.write("812：" + response + "\n")

    return response
