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

    # 使用异步文件读取历史以兼容原实现
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
    # 只有在有 msg 的情况下才解析消息并追加历史
    if msg is not None:
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
                    force_reply = True

        text_content = f"{msg.sender.nickname}({msg.sender.user_id}): {text_content}"

        # Append the new message to the appropriate chat history
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"{asyncio.get_event_loop().time()} {text_content}\n")

    # 读取 config 中的 message_delay（秒）
    try:
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            message_delay = int(yaml.safe_load(f).get("message_delay", 10))
    except Exception:
        message_delay = 10

    # 查找历史记录中最后一次由机器人（812）发送的时间戳，以实现定时触发策略
    last_reply_time = 0.0
    try:
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as hf:
                for ln in reversed(hf.readlines()):
                    parts = ln.strip().split(None, 1)
                    if len(parts) < 2:
                        continue
                    try:
                        ts = float(parts[0])
                    except Exception:
                        continue
                    if "812(" in parts[1]:
                        last_reply_time = ts
                        break
    except Exception:
        last_reply_time = 0.0

    current_time = asyncio.get_event_loop().time()
    # 如果距离上次机器人回复还未到间隔且没有被@，则不生成回复
    if not force_reply and (current_time - last_reply_time) < message_delay:
        return

    _log.info("开始生成回复……")
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        result = []
        try:
            with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
                max_history = int(yaml.safe_load(f).get("max_history", 5))
        except:
            max_history = 5
        for line in reversed(lines):
            try:
                if len(result) >= max_history:
                    break
                parts = line.strip().split(None, 1)
                if len(parts) < 2:
                    continue
                try:
                    _ = float(parts[0])
                except Exception:
                    continue
                rest = parts[1]
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
