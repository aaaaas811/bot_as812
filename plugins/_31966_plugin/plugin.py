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

try:
    from as812.core.config_manager import ConfigManager
    from as812.core.log_manager import LogManager
    from as812.models.message_models import BotResponse
    from as812.responses.CatCatRes import cat_cat_response
except ModuleNotFoundError:
    from plugins.as812.core.config_manager import ConfigManager
    from plugins.as812.core.log_manager import LogManager
    from plugins.as812.models.message_models import BotResponse
    from plugins.as812.responses.CatCatRes import cat_cat_response


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AS812_DIR = Path(__file__).resolve().parents[1] / "as812"


class PluginPlugin(NcatBotPlugin):
    name = "_31966_plugin"
    version = "0.2.0"
    author = "31966"
    description = "legacy main.py 逻辑迁移示例插件"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cyc_wait_time = 0.2
        self.emoji_kill_mode = False
        self.emoji_kill_times = 8
        self.emoji_wait_time = 0.1
        self.poke_back_times = 1
        self.poke_back_enabled = True
        self.famous_words_time = 3600
        self.config_manager = ConfigManager()
        self.log_manager = LogManager()

    async def on_load(self):
        self.logger.info(f"{self.name} 已加载")

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

    def load_cat_prompt(self) -> str:
        """从 plugins/as812/config/cat_prompt.txt 读取人设 prompt。"""
        try:
            prompt_path = AS812_DIR / "config" / "cat_prompt.txt"
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as exc:
            self.logger.error(f"读取 cat_prompt.txt 失败: {exc}")
            return ""

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
        if text == "戳一戳回击开启":
            self.poke_back_enabled = True
            await self.api.qq.post_private_msg(msg.user_id, text="戳一戳回击已开启喵~")
        if text == "戳一戳回击关闭":
            self.poke_back_enabled = False
            await self.api.qq.post_private_msg(msg.user_id, text="戳一戳回击已关闭喵~")
        if text == "查询戳一戳回击":
            status = "开启" if self.poke_back_enabled else "关闭"
            await self.api.qq.post_private_msg(
                msg.user_id, text=f"当前戳一戳回击为：{status}，次数：{self.poke_back_times}"
            )
        if text.startswith("戳一戳回击次数+"):
            number_plus = text[len("戳一戳回击次数+") :].strip()
            if number_plus.isdigit():
                self.poke_back_times += int(number_plus)
            await self.api.qq.post_private_msg(msg.user_id, text=f"当前戳一戳回击次数为：{self.poke_back_times} 次")
        if text.startswith("戳一戳回击次数-"):
            number_minus = text[len("戳一戳回击次数-") :].strip()
            if number_minus.isdigit():
                self.poke_back_times = max(0, self.poke_back_times - int(number_minus))
            await self.api.qq.post_private_msg(msg.user_id, text=f"当前戳一戳回击次数为：{self.poke_back_times} 次")
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

        if text.startswith("/名言警句"):
            try:
                file_path = PROJECT_ROOT / "data" / "rgl.txt"
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                if not lines:
                    await self.api.qq.post_group_msg(msg.group_id, text="无话可说")
                    return

                parts = text.split()
                count = 1
                if len(parts) > 1 and parts[1].isdigit():
                    count = min(10, int(parts[1]))

                for _ in range(count):
                    quote = random.choice(lines)
                    await self.api.qq.post_group_msg(msg.group_id, text=quote)
                    if count > 1:
                        await asyncio.sleep(0.5)
            except FileNotFoundError:
                await self.api.qq.post_group_msg(msg.group_id, text="文件不存在")

    @registrar.qq.on_poke()
    @bot_state.ignore_if_sleeping()
    async def on_poke(self, event: NoticeEvent):
        target_id = getattr(event.data, "target_id", None)
        if str(target_id) != str(event.self_id) or not self.poke_back_enabled:
            return

        for _ in range(self.poke_back_times):
            if event.group_id and event.user_id:
                await self.api.qq.send_poke(event.group_id, event.user_id)
            await asyncio.sleep(self.cyc_wait_time)

        try:
            config_path = AS812_DIR / "config" / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                cat_config = yaml.safe_load(f) or {}
                api_key = cat_config.get("api_key")
            cat_prompt = self.load_cat_prompt()

            try:
                _, user_info_str, personality_summary, _ = self.log_manager.load_personal_log(
                    str(event.group_id), str(event.user_id)
                )
            except Exception:
                user_info_str = ""
                personality_summary = ""

            chat_history = []
            if user_info_str:
                chat_history.append({"role": "system", "content": f"该用户的基本信息：{user_info_str}"})
            if personality_summary:
                chat_history.append({"role": "system", "content": f"该用户的个性总结：{personality_summary}"})
            chat_history.append(
                {
                    "role": "system",
                    "content": f"有人戳了戳因此812对其进行了{self.poke_back_times}下回击，812对此有些戏谑性的恼怒",
                }
            )

            response = await cat_cat_response(api_key, chat_history, cat_prompt)
            if response:
                await self._send_response_like_as812(event.group_id, response)
        except Exception as exc:
            self.logger.warning(f"戳一戳 AI 回复失败: {exc}")

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
                        for ext in (".png", ".jpg", ".jpeg"):
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
