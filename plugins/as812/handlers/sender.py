"""回复发送器：将模型输出渲染为群聊/私聊消息。

职责边界（展示层）：
- 按段/行拆分回复，逐条发送，模拟真人聊天节奏（思考延迟 + 停顿抖动）
- 渲染表情包指令（##emoji / [EMOJI] / 行内 [名称]）与特殊指令（##revoke / ##should not say / ##set_emotion）
- 不直接接触 SDK：发送/撤回/心情副作用均通过插件主类注入的回调完成
"""
import re
import time
import random
import base64
import asyncio
from pathlib import Path
from ncatbot.utils.logger import get_log
from ..models.message_models import BotResponse
from ..core.config_manager import ConfigManager
from ..core.log_manager import LogManager

_log = get_log()


class ResponseSender:
    """展示层：把 LLM 回复变成一条条有节奏的 QQ 消息。"""

    def __init__(self, config_manager: ConfigManager, log_manager: LogManager,
                 mood_handler, assets_dir: Path,
                 post_group_msg, post_private_msg, delete_msg, set_emotion):
        self.config_manager = config_manager
        self.log_manager = log_manager
        self.mood_handler = mood_handler
        self._assets_dir = assets_dir
        # SDK 兼容接口（由插件主类注入，保持本模块与 SDK 解耦）
        self._post_group_msg = post_group_msg          # async fn(group_id, **kwargs) -> id
        self._post_private_msg = post_private_msg      # async fn(user_id, **kwargs) -> id
        self._delete_msg = delete_msg                  # async fn(message_id)
        self._set_emotion = set_emotion                # async fn(group_id, mood)

    async def send_group_response(self, group_id: int, response: str, reply_id: str = None) -> None:
        """发送群聊回复（记录机器人回复日志）。"""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", response) if p.strip()]
        if not paragraphs:
            return
        bot_qq = self.config_manager.get_bt_uin() or "812"

        async def send_line(**kwargs):
            return await self._post_group_msg(group_id, **kwargs)

        def on_text_sent(text, msg_id):
            bot_resp = BotResponse(timestamp=time.time(), message=text, qq=str(bot_qq))
            self.log_manager.save_bot_response(str(group_id), bot_resp)

        def on_emoji_sent(emoji_name, msg_id):
            bot_resp = BotResponse(timestamp=time.time(), message=f"[EMOJI]{emoji_name}", qq=str(bot_qq))
            self.log_manager.save_bot_response(str(group_id), bot_resp)

        await self._stream_reply(
            paragraphs,
            send_line,
            on_text_sent,
            on_emoji_sent,
            reply_id=reply_id,
            revoke_func=self._delete_msg,
            set_emotion_func=lambda mood: self._set_emotion(group_id, mood),
        )

    async def send_private_response(self, user_id: int, response: str, reply_id: str = None) -> None:
        """发送私聊回复（不记录日志、不支持撤回/心情指令）。"""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", response) if p.strip()]
        if not paragraphs:
            return

        async def send_line(**kwargs):
            return await self._post_private_msg(user_id, **kwargs)

        await self._stream_reply(
            paragraphs,
            send_line,
            lambda *a, **k: None,
            lambda *a, **k: None,
            reply_id=reply_id,
        )

    async def _stream_reply(self, paragraphs: list[str], send_line, on_text_sent, on_emoji_sent,
                            reply_id: str = None, revoke_func=None, set_emotion_func=None) -> None:
        """流式发送回复，模拟真人聊天的节奏。

        - 开口前先"思考"：随机延迟随回复长度增加，避免秒回
        - 行间/段间停顿加入随机抖动，模拟打字节奏的自然起伏

        send_line:        async fn(**kwargs) -> 消息id(可空)，实际发送接口
        on_text_sent:     fn(text, msg_id) 文本发送成功后的钩子（群聊用于保存日志）
        on_emoji_sent:    fn(emoji_name, msg_id) 表情发送成功后的钩子
        revoke_func:      fn(msg_id) 撤回钩子（私聊传 None 表示不支持撤回）
        set_emotion_func: fn(mood) 心情设置钩子（私聊传 None 表示按普通文本发送）
        """
        pause_multiplier, line_pause_multiplier = self.config_manager.get_pause_multipliers()
        jitter = float(self.config_manager.get("reply_pause_jitter", 0.35))
        think_min = float(self.config_manager.get("reply_think_delay_min", 0.5))
        think_max = float(self.config_manager.get("reply_think_delay_max", 2.0))

        # 模拟"读了消息再开口"：回复越长，思考越久（带随机抖动，避免每次一样）
        total_len = sum(len(p) for p in paragraphs)
        think_delay = think_min + (think_max - think_min) * min(1.0, total_len / 60.0) * random.uniform(0.7, 1.3)
        await asyncio.sleep(max(0.0, think_delay))

        last_sent_id = None
        is_first_message = True  # 标记是否为第一条消息

        def _reply_kwargs():
            return {"reply": reply_id} if (is_first_message and reply_id) else {}

        for para in paragraphs:
            # 段内若有多行，则按行分别发送
            lines = [l.strip() for l in para.splitlines() if l.strip()]

            for line in lines:
                # 处理发表情包指令：支持两种格式：[EMOJI]名称 或 ##emoji 名称（支持可选中括号）
                m_em_bracket = re.match(r"^\[EMOJI\]\s*([^\s\]]+)$", line)
                m_em_hash = re.match(r"^##emoji\s*\[?([^\]\s]+)\]?$", line, flags=re.IGNORECASE)
                m = m_em_bracket or m_em_hash
                if m:
                    emoji_name = m.group(1)
                    try:
                        # 只在 assests 根目录查找（不递归子目录）
                        sent = False
                        for ext in (".png", ".jpg", ".jpeg", ".gif"):
                            img_path = self._assets_dir / f"{emoji_name}{ext}"
                            if img_path.exists() and img_path.is_file():
                                try:
                                    data = img_path.read_bytes()
                                    b64 = base64.b64encode(data).decode()
                                    res = await send_line(image=f"base64://{b64}", **_reply_kwargs())
                                except Exception as e:
                                    _log.error(f"发送表情包失败: {e}")
                                    res = None

                                if res:
                                    last_sent_id = str(res)
                                    try:
                                        on_emoji_sent(emoji_name, last_sent_id)
                                    except Exception as e:
                                        _log.warning(f"保存机器人回复日志失败: {e}")
                                    is_first_message = False  # 发送成功后，标记不再是第一条消息

                                sent = True
                                break

                        if not sent:
                            # 未找到对应文件，发送提示文本
                            try:
                                res = await send_line(text=f"表情包不存在: {emoji_name}", **_reply_kwargs())
                            except Exception as e:
                                _log.error(f"发送消息失败: {e}")
                                res = None

                            if res:
                                last_sent_id = str(res)
                                is_first_message = False  # 发送成功后，标记不再是第一条消息

                        # 表情包指令处理完毕，继续下一行
                    except Exception as e:
                        _log.warning(f"处理表情包指令失败: {e}")
                    continue

                # 处理行内表情：例如“唔...我不太懂呢[奶龙大笑]”
                # 仅当中括号内容能匹配到本地表情文件时，才拆分为文本+表情发送。
                inline_matches = list(re.finditer(r"\[([^\[\]\s]+)\]", line))
                if inline_matches:
                    cursor = 0
                    handled_inline_emoji = False

                    for inline_match in inline_matches:
                        emoji_name = inline_match.group(1)
                        emoji_path = None
                        for ext in (".png", ".jpg", ".jpeg", ".gif"):
                            candidate = self._assets_dir / f"{emoji_name}{ext}"
                            if candidate.exists() and candidate.is_file():
                                emoji_path = candidate
                                break

                        # 未命中本地表情文件时，保留原文本，不将 [] 视为表情指令。
                        if emoji_path is None:
                            continue

                        text_chunk = line[cursor:inline_match.start()].strip()
                        if text_chunk:
                            try:
                                res = await send_line(text=text_chunk, **_reply_kwargs())
                            except Exception as e:
                                _log.error(f"发送消息失败: {e}")
                                res = None

                            if res:
                                last_sent_id = str(res)
                                try:
                                    on_text_sent(text_chunk, last_sent_id)
                                except Exception as e:
                                    _log.warning(f"保存机器人回复日志失败: {e}")
                                is_first_message = False

                        try:
                            data = emoji_path.read_bytes()
                            b64 = base64.b64encode(data).decode()
                            res = await send_line(image=f"base64://{b64}", **_reply_kwargs())
                        except Exception as e:
                            _log.error(f"发送表情包失败: {e}")
                            res = None

                        if res:
                            last_sent_id = str(res)
                            try:
                                on_emoji_sent(emoji_name, last_sent_id)
                            except Exception as e:
                                _log.warning(f"保存机器人回复日志失败: {e}")
                            is_first_message = False

                        handled_inline_emoji = True
                        cursor = inline_match.end()

                    if handled_inline_emoji:
                        tail_text = line[cursor:].strip()
                        if tail_text:
                            try:
                                res = await send_line(text=tail_text, **_reply_kwargs())
                            except Exception as e:
                                _log.error(f"发送消息失败: {e}")
                                res = None

                            if res:
                                last_sent_id = str(res)
                                try:
                                    on_text_sent(tail_text, last_sent_id)
                                except Exception as e:
                                    _log.warning(f"保存机器人回复日志失败: {e}")
                                is_first_message = False

                        await asyncio.sleep(line_pause_multiplier * max(1, len(line)) * random.uniform(1 - jitter, 1 + jitter))
                        continue

                if line == "##revoke":
                    if revoke_func is not None and last_sent_id:
                        try:
                            await revoke_func(last_sent_id)
                        except Exception as e:
                            _log.error(f"撤回消息失败: {e}")
                    continue
                if line == "##should not say":
                    break
                if line.startswith("##set_emotion "):
                    if set_emotion_func is not None:
                        try:
                            await set_emotion_func(line[len("##set_emotion "):].strip())
                        except Exception as e:
                            _log.warning(f"处理 ##set_emotion 指令失败: {e}")
                        continue
                    # 私聊路径不支持心情指令，按普通文本发送（保持旧行为）
                try:
                    res = await send_line(text=line, **_reply_kwargs())
                except Exception as e:
                    _log.error(f"发送消息失败: {e}")
                    res = None

                # 保存消息ID
                if res:
                    last_sent_id = str(res)
                    # 记录机器人发送的回复到群历史
                    try:
                        on_text_sent(line, last_sent_id)
                    except Exception as e:
                        _log.warning(f"保存机器人回复日志失败: {e}")
                    is_first_message = False  # 发送成功后，标记不再是第一条消息

                await asyncio.sleep(line_pause_multiplier * max(1, len(line)) * random.uniform(1 - jitter, 1 + jitter))

            # 段间短暂停顿
            await asyncio.sleep(pause_multiplier * len(para) * random.uniform(1 - jitter, 1 + jitter))
