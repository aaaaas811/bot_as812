"""示例插件：承接 legacy main.py 的迁移逻辑（NcatBot 5.x）。"""

import sdk_compat  # noqa: F401
import asyncio
import base64
import json
import os
import random
import re
import time
from pathlib import Path

import yaml
from ncatbot.core import registrar
from ncatbot.event.qq import (
    GroupIncreaseEvent,
    GroupMessageEvent,
    NoticeEvent,
    PrivateMessageEvent,
)
from ncatbot.plugin import NcatBotPlugin
from uapi import UapiClient
from uapi.errors import UapiError

import bot_state
from plugins._31966_plugin.sleep_schedule import is_scheduled_sleep_time

try:
    from as812.core.config_manager import ConfigManager
    from as812.core.log_manager import LogManager
    from as812.models.message_models import BotResponse
except ModuleNotFoundError:
    from plugins.as812.core.config_manager import ConfigManager
    from plugins.as812.core.log_manager import LogManager
    from plugins.as812.models.message_models import BotResponse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AS812_DIR = Path(__file__).resolve().parents[1] / "as812"


class PluginPlugin(NcatBotPlugin):
    name = "_31966_plugin"
    version = "0.2.0"
    author = "31966"
    description = "legacy main.py 逻辑迁移示例插件"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.emoji_kill_mode = False
        self.emoji_kill_times = 8
        self.emoji_wait_time = 0.1
        self.famous_words_time = 3600
        self.config_manager = ConfigManager()
        self.log_manager = LogManager()

    async def on_load(self):
        # 热重载或重启时立即按当前时间校准，避免等到下一个整点。
        bot_state.set_sleep(is_scheduled_sleep_time())
        self.add_scheduled_task(
            name="enter_sleep_mode",
            interval="00:00",
            callback=self.enter_sleep_mode,
        )
        self.add_scheduled_task(
            name="exit_sleep_mode",
            interval="08:00",
            callback=self.exit_sleep_mode,
        )
        self.logger.info(f"{self.name} 已加载")

    async def enter_sleep_mode(self):
        bot_state.set_sleep(True)
        self.logger.info("已按计划进入睡眠模式")

    async def exit_sleep_mode(self):
        bot_state.set_sleep(False)
        self.logger.info("已按计划退出睡眠模式")

    async def on_close(self):
        self.logger.info(f"{self.name} 已卸载")

    async def send_famous_words(self):
        client = UapiClient("https://uapis.cn")
        while True:
            try:
                result = client.poem.get_saying()
                try:
                    with open("config.yaml", "r", encoding="utf-8") as f:
                        root_config = yaml.safe_load(f) or {}
                    active_group_id = root_config.get("active_group_id")
                    if active_group_id:
                        await self.api.qq.post_group_msg(int(active_group_id), text=str(result))
                except Exception as exc:
                    self.logger.warning(f"发送名言警句失败: {exc}")
            except UapiError as exc:
                self.logger.warning(f"名言警句 API 错误: {exc}")
            await asyncio.sleep(self.famous_words_time)

    async def on_group_event(self, msg: GroupMessageEvent):
        # Compatibility entry for legacy dispatcher paths.
        await self.on_group_message(msg)

    async def on_private_message(self, msg: PrivateMessageEvent):
        # Compatibility entry for legacy dispatcher paths.
        await self.master_message_control(msg)

    @registrar.qq.on_private_message()
    @bot_state.ignore_if_sleeping(allow_uins=[bot_state.MASTER_UIN])
    async def master_message_control(self, msg: PrivateMessageEvent):
        text = (msg.raw_message or "").strip()
        if str(msg.user_id) != str(bot_state.MASTER_UIN):
            return

        if text == "测试":
            await self.api.qq.post_private_msg(msg.user_id, text="NcatBot 测试成功喵~")
        if text == "表情歼灭模式开启":
            self.emoji_kill_mode = True
            await self.api.qq.post_private_msg(msg.user_id, text="表情歼灭模式已开启喵~")
        if text == "表情歼灭模式关闭":
            self.emoji_kill_mode = False
            await self.api.qq.post_private_msg(msg.user_id, text="表情歼灭模式已关闭喵~")
        if text == "查询表情歼灭模式":
            status = "开启" if self.emoji_kill_mode else "关闭"
            await self.api.qq.post_private_msg(msg.user_id, text=f"当前表情歼灭模式为：{status}")
        if text.startswith("歼灭次数+"):
            number_plus = text[len("歼灭次数+") :].strip()
            if number_plus.isdigit():
                self.emoji_kill_times += int(number_plus)
            await self.api.qq.post_private_msg(msg.user_id, text=f"当前歼灭次数为：{self.emoji_kill_times} 次")
        if text.startswith("歼灭次数-"):
            number_minus = text[len("歼灭次数-") :].strip()
            if number_minus.isdigit():
                self.emoji_kill_times = max(1, self.emoji_kill_times - int(number_minus))
            await self.api.qq.post_private_msg(msg.user_id, text=f"当前歼灭次数为：{self.emoji_kill_times} 次")
        if text == "812睡觉":
            await self.api.qq.post_private_msg(msg.user_id, text="哦呀斯密....")
            bot_state.set_sleep(True)
        if text == "812起床":
            bot_state.set_sleep(False)
            await self.api.qq.post_private_msg(msg.user_id, text="嗯——早上好喵呜喵呜~")
        if text == "测试1":
            await self.api.qq.post_private_msg(msg.user_id, text="[CQ:face,id=66] hi")

    @registrar.qq.on_group_message()
    @bot_state.ignore_if_sleeping(allow_uins=bot_state.ADMIN_UINS, allow_group_admins=True)
    async def on_group_message(self, msg: GroupMessageEvent):
        text = (msg.raw_message or "").strip()

        if text == "812睡觉":
            role = getattr(getattr(msg, "sender", None), "role", None)
            if str(msg.user_id) not in bot_state.ADMIN_UINS and role not in ["owner", "admin"]:
                await self.api.qq.post_group_msg(msg.group_id, text="我才不听你的")
                return
            await self.api.qq.post_group_msg(msg.group_id, text="哦呀斯密....")
            bot_state.set_sleep(True)

        if text == "812起床" and bot_state.is_sleeping():
            bot_state.set_sleep(False)
            await self.api.qq.post_group_msg(msg.group_id, text="嗯——早上好喵呜喵呜~")

    @registrar.on("notice.group_msg_emoji_like", platform="qq")
    @bot_state.ignore_if_sleeping()
    async def emoji_killer(self, event: NoticeEvent):
        is_add = getattr(event, "is_add", None)
        if is_add is None:
            is_add = getattr(getattr(event, "data", None), "is_add", False)
        if not is_add:
            return

        target_id = getattr(event, "target_id", None)
        if target_id is None:
            target_id = getattr(getattr(event, "data", None), "target_id", None)

        if str(event.user_id) != str(bot_state.MASTER_UIN) or str(target_id) == str(bot_state.MASTER_UIN):
            return

        message_id = getattr(event, "message_id", None)
        emoji_like_id = getattr(event, "emoji_like_id", None)
        if message_id is None:
            message_id = getattr(getattr(event, "data", None), "message_id", None)
        if emoji_like_id is None:
            emoji_like_id = getattr(getattr(event, "data", None), "emoji_like_id", None)

        if not message_id or emoji_like_id is None:
            return

        if not self.emoji_kill_mode:
            try:
                await self.api.qq.set_msg_emoji_like(message_id=message_id, emoji_id=emoji_like_id, set=True)
            except Exception:
                pass
            return

        for _ in range(self.emoji_kill_times):
            try:
                await self.api.qq.set_msg_emoji_like(message_id=message_id, emoji_id=emoji_like_id, set=True)
                await asyncio.sleep(self.emoji_wait_time)
                await self.api.qq.set_msg_emoji_like(message_id=message_id, emoji_id=emoji_like_id, set=False)
            except Exception:
                pass

    @registrar.qq.on_group_increase()
    @bot_state.ignore_if_sleeping()
    async def on_group_member_join(self, event: GroupIncreaseEvent):
        await self.api.qq.post_group_msg(group_id=event.group_id, text="新天尊玩什么太刀")

    async def _send_response_like_as812(self, group_id: int, response: str):
        """模仿 as812 的回复发送逻辑，处理特殊指令。"""
        try:
            pause_multiplier, line_pause_multiplier = self.config_manager.get_pause_multipliers()
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", response) if p.strip()]
            last_sent_id = None
            assets_dir = AS812_DIR / "assests"

            for para in paragraphs:
                lines = [l.strip() for l in para.splitlines() if l.strip()]
                for line in lines:
                    m = re.match(r"^##emoji\s*\[?([^\]\s]+)\]?$", line)
                    if m:
                        emoji_name = m.group(1)
                        sent = False
                        for ext in (".png", ".jpg", ".jpeg", ".gif"):
                            img_path = assets_dir / f"{emoji_name}{ext}"
                            if img_path.exists() and img_path.is_file():
                                try:
                                    data = img_path.read_bytes()
                                    b64 = base64.b64encode(data).decode()
                                    res = await self.api.qq.post_group_msg(group_id, image=f"base64://{b64}")
                                except Exception:
                                    res = None

                                if res:
                                    last_sent_id = str(res)
                                    try:
                                        bot_resp = BotResponse(
                                            timestamp=float(time.time()),
                                            message=f"[EMOJI]{emoji_name}",
                                            qq="812",
                                        )
                                        self.log_manager.save_bot_response(str(group_id), bot_resp)
                                    except Exception:
                                        pass

                                sent = True
                                break

                        if not sent:
                            try:
                                res = await self.api.qq.post_group_msg(group_id, text=f"表情包不存在: {emoji_name}")
                            except Exception:
                                res = None
                            if res:
                                last_sent_id = str(res)
                        continue

                    inline_matches = list(re.finditer(r"\[([^\[\]\s]+)\]", line))
                    if inline_matches:
                        cursor = 0
                        handled_inline_emoji = False

                        for inline_match in inline_matches:
                            emoji_name = inline_match.group(1)
                            emoji_path = None
                            for ext in (".png", ".jpg", ".jpeg", ".gif"):
                                candidate = assets_dir / f"{emoji_name}{ext}"
                                if candidate.exists() and candidate.is_file():
                                    emoji_path = candidate
                                    break

                            if emoji_path is None:
                                continue

                            text_chunk = line[cursor:inline_match.start()].strip()
                            if text_chunk:
                                try:
                                    res = await self.api.qq.post_group_msg(group_id, text=text_chunk)
                                except Exception:
                                    res = None
                                if res:
                                    last_sent_id = str(res)
                                    try:
                                        bot_resp = BotResponse(timestamp=float(time.time()), message=text_chunk, qq="812")
                                        self.log_manager.save_bot_response(str(group_id), bot_resp)
                                    except Exception:
                                        pass

                            try:
                                data = emoji_path.read_bytes()
                                b64 = base64.b64encode(data).decode()
                                res = await self.api.qq.post_group_msg(group_id, image=f"base64://{b64}")
                            except Exception:
                                res = None

                            if res:
                                last_sent_id = str(res)
                                try:
                                    bot_resp = BotResponse(
                                        timestamp=float(time.time()),
                                        message=f"[EMOJI]{emoji_name}",
                                        qq="812",
                                    )
                                    self.log_manager.save_bot_response(str(group_id), bot_resp)
                                except Exception:
                                    pass

                            handled_inline_emoji = True
                            cursor = inline_match.end()

                        if handled_inline_emoji:
                            tail_text = line[cursor:].strip()
                            if tail_text:
                                try:
                                    res = await self.api.qq.post_group_msg(group_id, text=tail_text)
                                except Exception:
                                    res = None
                                if res:
                                    last_sent_id = str(res)
                                    try:
                                        bot_resp = BotResponse(timestamp=float(time.time()), message=tail_text, qq="812")
                                        self.log_manager.save_bot_response(str(group_id), bot_resp)
                                    except Exception:
                                        pass

                            await asyncio.sleep(line_pause_multiplier * max(1, len(line)))
                            continue

                    if line == "##revoke":
                        if last_sent_id:
                            try:
                                await self.api.qq.delete_msg(last_sent_id)
                            except Exception:
                                pass
                        continue

                    if line == "##should not say":
                        return

                    if line.startswith("##set_emotion "):
                        try:
                            mood_val = line[len("##set_emotion ") :].strip()
                            mood_path = AS812_DIR / "logs" / f"{group_id}_mood.json"
                            os.makedirs(mood_path.parent, exist_ok=True)
                            with open(mood_path, "w", encoding="utf-8") as mf:
                                json.dump({"mood": mood_val}, mf, ensure_ascii=False)
                        except Exception:
                            pass
                        continue

                    try:
                        res = await self.api.qq.post_group_msg(group_id, text=line)
                    except Exception:
                        res = None

                    if res:
                        last_sent_id = str(res)
                        try:
                            bot_resp = BotResponse(timestamp=float(time.time()), message=line, qq="812")
                            self.log_manager.save_bot_response(str(group_id), bot_resp)
                        except Exception:
                            pass

                    await asyncio.sleep(line_pause_multiplier * max(1, len(line)))

                await asyncio.sleep(pause_multiplier * len(para))
        except Exception as exc:
            self.logger.warning(f"发送回复失败: {exc}")
