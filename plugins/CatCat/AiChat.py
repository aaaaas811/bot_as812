from ncatbot.utils.logger import get_log
from ncatbot.core.message import GroupMessage
from ncatbot.utils import config

import asyncio
import os
import aiofiles
import yaml

from .responses.CatCatRes import cat_cat_response

_log = get_log()

global_chat_histories = []


async def gene_response(api_key, msg: GroupMessage = None, cat_prompt=None, group_id: str = None):
    # 支持两种调用方式：由群消息触发（传入 msg），或定时/主动触发（传入 group_id 或使用 config 中 manager_id）
    if msg is not None:
        gid = msg.group_id
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

    history_file = f"plugins/CatCat/logs/{gid}_history.log"
    # 使用上下文管理器处理文件操作
    try:
        async with aiofiles.open(history_file, "r", encoding="utf-8") as f:
            lines = await f.readlines()
            # 找到最后一条可解析为时间戳的行
            last_group_message_time = 0
            for ln in reversed(lines):
                try:
                    first_tok = ln.strip().split(None, 1)[0]
                    last_group_message_time = float(first_tok)
                    break
                except Exception:
                    continue
    except FileNotFoundError:
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        async with aiofiles.open(history_file, "w", encoding="utf-8") as f:
            current_time = asyncio.get_event_loop().time()
            await f.write(f"{current_time} manager(10101): init catcat\n")
        last_group_message_time = 0

    force_reply = False
    text_content = ""
    for message in msg.message:
        # 兼容两种 message 格式：旧的 dict 格式或新的 MessageSegment 对象
        try:
            mtype = message["type"]
        except Exception:
            mtype = getattr(message, "msg_seg_type", None)

        if mtype == "text":
            # 获取文本内容，优先使用对象属性，再使用 dict 结构
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
            # 获取 at 的 qq 标识
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
                force_reply = True

    # 如果文本中包含 '812' 字样，也视为被提及，除非明确是睡觉/起床命令
    if not force_reply and text_content:
        try:
            # 去掉空格以便匹配像 '812 睡觉' 的情况
            compact = text_content.replace(" ", "")
            if "812" in compact:
                if not ("812睡觉" in compact or "812起床" in compact):
                    force_reply = True
        except Exception:
            pass

    if msg is not None:
        # 提取群成员额外字段：群名片(card)、角色(role)、头衔(title)
        try:
            card = getattr(msg.sender, "card", "") or ""
        except Exception:
            card = ""
        try:
            role = getattr(msg.sender, "role", "") or ""
        except Exception:
            role = ""
        try:
            title = getattr(msg.sender, "title", "") or ""
        except Exception:
            title = ""

        sender_info = f"{msg.sender.nickname}({msg.sender.user_id})[{card}][{role}][{title}]"
        text_content = f"{sender_info}: {text_content}"

        # Append the new message to the appropriate chat history
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"{asyncio.get_event_loop().time()} {text_content}\n")

    current_time = asyncio.get_event_loop().time()
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            message_dalay = int(yaml.safe_load(f)["message_delay"])
    except:
        message_dalay = 10
    if current_time - last_group_message_time < message_dalay and not force_reply:
        return

    _log.info("开始生成回复……")
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        result = []
        try:
            with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
                max_history = int(yaml.safe_load(f)["max_history"])
        except:
            max_history = 5
        for line in reversed(lines):
            try:
                if len(result) >= max_history:
                    break
                # 解析格式: <timestamp> <rest...>
                parts = line.strip().split(None, 1)
                if len(parts) < 2:
                    continue
                # 确保首项为时间戳
                try:
                    _ = float(parts[0])
                except Exception:
                    continue
                rest = parts[1]
                # 尝试从 rest 中提取消息主体（冒号后部分）
                if ":" in rest:
                    this_content = rest.split(":", 1)[1].strip()
                else:
                    this_content = rest
                if not any(this_content in content for content in result):
                    result.append(line)
            except Exception as e:
                print(f"处理历史记录出错: {str(e)}")
                continue
        chat_history = reversed(result)
    if response := await cat_cat_response(api_key, chat_history, cat_prompt):
        _log.info(f"812：{response}")
    else:
        return
      
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"{asyncio.get_event_loop().time()} 812({config.bt_uin}): {'\\'.join(response.split('\n'))}\n")
    return response
