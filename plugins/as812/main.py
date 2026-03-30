"""as812插件主入口（重构版）"""
import sdk_compat  # noqa: F401

import asyncio
import re
import os
import base64
import sys
import subprocess
import random
from typing import Any
from types import SimpleNamespace
from pathlib import Path
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.utils.logger import get_log

from .core.config_manager import ConfigManager, PromptManager
from .core.log_manager import LogManager
from .handlers.message_handler import MessageHandler
from .handlers.response_handler import ResponseHandler
from .handlers.mood_handler import MoodHandler
from .handlers.command_handler import CommandHandler
from .handlers.bilibili_handler import BilibiliHandler
from .models.message_models import BotResponse

import bot_state
from uapi import UapiClient
from uapi.errors import UapiError

_log = get_log()


class _NoopRegistrar:
    """当未提供 bilibili 注册器时，保证装饰器不报错。"""

    def __getattr__(self, _name):
        def _decorator_factory(*_args, **_kwargs):
            def _decorator(func):
                return func
            return _decorator
        return _decorator_factory


bili_registrar = getattr(registrar, "bilibili", _NoopRegistrar())


class as812(NcatBotPlugin):
    """as812插件主类"""
    
    name = "as812"  # 插件名称
    version = "1.1.0"  # 插件版本（重构版）
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_manager = None
        self.prompt_manager = None
        self.log_manager = None
        self.message_handler = None
        self.response_handler = None
        self.mood_handler = None
        self.command_handler = None
        self.bilibili_handler = None
        self._assets_dir = Path(__file__).parent / "assests"
    
    async def on_load(self):
        """插件加载时执行"""
        _log.info("as812插件加载中……")
        
        # 初始化各个管理器
        self.config_manager = ConfigManager()
        self.prompt_manager = PromptManager()
        self.log_manager = LogManager()
        self.message_handler = MessageHandler(self.config_manager, self.log_manager)
        self.response_handler = ResponseHandler(
            self.config_manager, 
            self.log_manager, 
            self.message_handler
        )
        self.mood_handler = MoodHandler(self.config_manager)
        self.command_handler = CommandHandler(
            self.config_manager,
            self.prompt_manager,
            self.log_manager
        )
        self.bilibili_handler = BilibiliHandler(self.config_manager)
        await self.bilibili_handler.on_load(self.api)
        
        _log.info(f"{self.name} 插件已加载 (v{self.version})")
        # 以子进程方式启动可视化面板，避免在主进程导入 tkinter/PIL
        try:
            script_path = Path(__file__).parent / "visual_panel.py"
            args = [sys.executable, str(script_path), str(self._assets_dir), str(Path(__file__).parent / "logs"), str(os.getpid())]
            try:
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _log.info("as812 可视化面板已以子进程启动")
            except Exception as e:
                _log.warning(f"启动 as812 可视化面板失败: {e}")
        except Exception as e:
            _log.warning(f"准备启动 visual_panel 失败: {e}")

    async def on_unload(self):
        """插件卸载时清理资源。"""
        if self.bilibili_handler is not None:
            await self.bilibili_handler.on_unload(self.api)
    
    def _adapt_group_event(self, event: GroupMessageEvent):
        """将 v5 事件适配为旧逻辑可用的数据结构。"""
        sender = getattr(event, "sender", None)
        if sender is None:
            sender = SimpleNamespace(
                nickname=getattr(event, "nickname", ""),
                user_id=getattr(event, "user_id", None),
                card=getattr(event, "card", ""),
                role=getattr(event, "role", ""),
                title=getattr(event, "title", ""),
            )
        return SimpleNamespace(
            raw_message=getattr(event, "raw_message", "") or "",
            user_id=getattr(event, "user_id", None),
            group_id=getattr(event, "group_id", None),
            message=getattr(event, "message", []) or [],
            message_id=getattr(event, "message_id", None),
            sender=sender,
            timestamp=getattr(event, "timestamp", None),
            time=getattr(event, "time", None),
        )

    async def _qq_get_msg(self, message_id):
        """兼容不同 SDK 版本的取消息接口。"""
        qq_api = getattr(self.api, "qq", None)
        if qq_api is not None:
            query_api = getattr(qq_api, "query", None)
            if query_api is not None and hasattr(query_api, "get_msg"):
                return await query_api.get_msg(message_id)
            if hasattr(qq_api, "get_msg"):
                return await qq_api.get_msg(message_id)
        if hasattr(self.api, "get_msg"):
            return await self.api.get_msg(message_id)
        raise AttributeError("当前 SDK 未提供 get_msg 接口")

    async def _qq_post_group_msg(self, group_id, **kwargs):
        """兼容不同 SDK 版本的群消息发送接口。"""
        qq_api = getattr(self.api, "qq", None)
        if qq_api is not None and hasattr(qq_api, "post_group_msg"):
            return await qq_api.post_group_msg(group_id, **kwargs)
        if hasattr(self.api, "post_group_msg"):
            return await self.api.post_group_msg(group_id, **kwargs)
        raise AttributeError("当前 SDK 未提供 post_group_msg 接口")

    async def _qq_delete_msg(self, message_id):
        """兼容不同 SDK 版本的撤回消息接口。"""
        qq_api = getattr(self.api, "qq", None)
        if qq_api is not None and hasattr(qq_api, "delete_msg"):
            return await qq_api.delete_msg(message_id)
        if hasattr(self.api, "delete_msg"):
            return await self.api.delete_msg(message_id)
        raise AttributeError("当前 SDK 未提供 delete_msg 接口")

    @registrar.qq.on_group_command("测试as812")
    @bot_state.ignore_if_sleeping()
    async def on_group_event(self, event: GroupMessageEvent):
        """群事件处理"""
        msg = self._adapt_group_event(event)
        if msg.raw_message == "测试as812" and msg.user_id == bot_state.MASTER_UIN:
            try:
                await self._qq_post_group_msg(msg.group_id, text="NCatBot插件as812测试成功喵")
            except Exception as e:
                _log.error(f"发送测试消息失败: {e}")
    
    @registrar.qq.on_group_message()
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, event: GroupMessageEvent):
        """群消息处理"""
        msg = self._adapt_group_event(event)
        _log.info(f"{msg.sender.nickname}({msg.sender.user_id}): {msg.raw_message[:10]}")
        
        # 检查机器人是否被禁言
        if await self.mood_handler.is_bot_muted(self.api, msg.group_id):
            return
        text = msg.raw_message
        if text.startswith("/"):
            return  # 以 / 开头的消息视为命令，交由命令处理器处理，不进入后续流程
        # 处理心情计数
        try:
            await self.mood_handler.process_mood_on_message(self.api, msg.group_id)
        except Exception as e:
            _log.warning(f"处理心情计数失败: {e}")
        
        # 获取提示词
        cat_prompt = self.prompt_manager.load_prompt()
        
        # 获取API密钥
        api_key = self.config_manager.get_api_key()
        if not api_key:
            _log.error("API密钥未配置")
            return
        
        # 解析消息
        chat_message = self.message_handler.parse_group_message(msg)

        # 若消息引用了其他消息，尝试通过 API 展开引用内容后再保存
        try:
            if getattr(chat_message, "reply_id", None):
                try:
                    orig_event = await self._qq_get_msg(chat_message.reply_id)
                    # 优先使用 raw_message（若存在），否则尝试展平 message 段数组
                    orig_text = None
                    if hasattr(orig_event, "raw_message") and orig_event.raw_message:
                        orig_text = orig_event.raw_message
                    else:
                        # 尝试 message 属性（可能为列表）
                        if hasattr(orig_event, "message") and orig_event.message:
                            parts = []
                            for seg in orig_event.message:
                                try:
                                    if isinstance(seg, dict):
                                        if seg.get("type") == "text":
                                            parts.append(seg.get("data", {}).get("text", ""))
                                    else:
                                        if getattr(seg, "msg_seg_type", None) == "text":
                                            parts.append(getattr(seg, "text", ""))
                                except Exception:
                                    continue
                            orig_text = "".join(parts).strip()

                    if orig_text:
                        # 尝试获取被引用消息的用户 card（优先）或昵称作为标识
                        try:
                            sender = getattr(orig_event, "sender", None)
                            card = None
                            if sender is not None:
                                card = getattr(sender, "card", None) or getattr(sender, "nickname", None) or getattr(sender, "user_id", None)
                            if not card:
                                # 兼容字典式 sender
                                try:
                                    card = orig_event.get("sender", {}).get("card") or orig_event.get("sender", {}).get("nickname")
                                except Exception:
                                    card = None
                        except Exception:
                            card = None

                        # 格式化引用为 [引用:card:内容]，若 card 为空则省略 card
                        if card:
                            expanded = f"[引用:{card}:{orig_text}]"
                        else:
                            expanded = f"[引用:{orig_text}]"

                        # 如果解析阶段意外已将简单引用文本加入（如 [引用:efrfr]），先移除简单占位，避免重复
                        import re
                        chat_msg = chat_message.message or ""
                        # 删除形如 [引用:... ] 的最前面一项（只删除第一个匹配），以便用 expanded 替换
                        chat_msg = re.sub(r'^\[引用:[^\]]+\]\s*', '', chat_msg, count=1)

                        chat_message.message = f"{expanded} " + chat_msg
                except Exception as e:
                    _log.debug(f"拉取引用消息失败: {e}")
        except Exception:
            pass

        # 保存用户消息到群历史
        self.log_manager.save_group_message(str(msg.group_id), chat_message)

        # 保存用户消息到个人日志（聊天记录部分）
        personal_log_file = self.log_manager.get_personal_log_path(str(msg.group_id), str(msg.sender.user_id))
        self.log_manager.append_to_personal_log(personal_log_file, f"用户: {chat_message.message}")
        
        # 处理被动回复
        response = await self.response_handler.process_passive_response(
            api_key, 
            chat_message, 
            str(msg.group_id), 
            cat_prompt
        )
        
        if response:
            # 根据配置的概率决定是否引用消息
            reply_id = None
            random_response_way = self.config_manager.get_random_response_way()
            if random.random() < random_response_way:
                reply_id = msg.message_id
            await self._send_response(msg.group_id, response, reply_id)
        else:
            # 尝试主动回复
            active_group_id = self.config_manager.get_active_group_id()
            if str(msg.group_id) == active_group_id:
                active_response = await self.response_handler.process_active_response(
                    api_key, 
                    cat_prompt, 
                    str(msg.group_id)
                )
                if active_response:
                    await self._send_response(msg.group_id, active_response)
    
    @registrar.qq.on_private_message()
    @bot_state.ignore_if_sleeping()
    async def on_private_message(self, event: PrivateMessageEvent):
        """私聊消息处理"""
        msg = event
        super_user = self.config_manager.get_super_user()
        if str(msg.user_id) != super_user:
            return
        
        await self.command_handler.handle_private_command(
            self.api.qq,
            msg.user_id, 
            msg.raw_message.strip()
        )

    @bili_registrar.on_danmu()
    async def on_bilibili_danmu(self, event: Any):
        """Bilibili 弹幕事件入口（骨架）。"""
        if self.bilibili_handler is None:
            return
        await self.bilibili_handler.handle_danmu(event)

    @bili_registrar.on_private_message()
    async def on_bilibili_private_message(self, event: Any):
        """Bilibili 私信事件入口（骨架）。"""
        if self.bilibili_handler is None:
            return
        await self.bilibili_handler.handle_private_message(event)

    @bili_registrar.on_live_start()
    async def on_bilibili_live_start(self, event: Any):
        """Bilibili 开播事件入口（骨架）。"""
        if self.bilibili_handler is None:
            return
        await self.bilibili_handler.handle_live_start(event)

    @bili_registrar.on_live_end()
    async def on_bilibili_live_end(self, event: Any):
        """Bilibili 下播事件入口（骨架）。"""
        if self.bilibili_handler is None:
            return
        await self.bilibili_handler.handle_live_end(event)

    @bili_registrar.on_dynamic_new()
    async def on_bilibili_dynamic_new(self, event: Any):
        """Bilibili 新动态事件入口（骨架）。"""
        if self.bilibili_handler is None:
            return
        await self.bilibili_handler.handle_dynamic_new(event)
    
    async def _send_response(self, group_id: int, response: str, reply_id: str = None):
        """发送回复消息"""
        try:
            pause_multiplier, line_pause_multiplier = self.config_manager.get_pause_multipliers()
            
            # 将回复按空行分段
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", response) if p.strip()]
            last_sent_id = None
            is_first_message = True  # 标记是否为第一条消息
            
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
                            for ext in (".png", ".jpg", ".jpeg"):
                                img_path = self._assets_dir / f"{emoji_name}{ext}"
                                if img_path.exists() and img_path.is_file():
                                    try:
                                        data = img_path.read_bytes()
                                        b64 = base64.b64encode(data).decode()
                                        res = await self._qq_post_group_msg(group_id, image=f"base64://{b64}", reply=reply_id if is_first_message else None)
                                    except Exception as e:
                                        _log.error(f"发送表情包失败: {e}")
                                        res = None

                                    if res:
                                        last_sent_id = str(res)
                                        try:
                                            import time as _time
                                            bot_qq = self.config_manager.get_bt_uin() or "812"
                                            bot_resp = BotResponse(timestamp=float(_time.time()), message=f"[EMOJI]{emoji_name}", qq=str(bot_qq))
                                            self.log_manager.save_bot_response(str(group_id), bot_resp)
                                        except Exception as e:
                                            _log.warning(f"保存机器人回复日志失败: {e}")
                                        is_first_message = False  # 发送成功后，标记不再是第一条消息

                                    sent = True
                                    break

                            if not sent:
                                # 未找到对应文件，发送提示文本
                                try:
                                    res = await self._qq_post_group_msg(group_id, text=f"表情包不存在: {emoji_name}", reply=reply_id if is_first_message else None)
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
                    if line == "##revoke":
                        if last_sent_id:
                            try:
                                await self._qq_delete_msg(last_sent_id)
                            except Exception as e:
                                _log.error(f"撤回消息失败: {e}")
                        continue
                    if line == "##should not say":
                        break
                    if line.startswith("##set_emotion "):
                        # 心情设置指令：提取心情并保存到日志文件（不发送到群）
                        try:
                            mood_val = line[len("##set_emotion "):].strip()
                            # 保存到 plugins/as812/logs/{group_id}_mood.json
                            try:
                                self.mood_handler.save_mood_state(str(group_id), {"mood": mood_val})
                            except Exception as e:
                                _log.warning(f"保存心情文件失败: {e}")
                            # 尝试通过 mood_handler 更新群名片（异步方法）
                            try:
                                await self.mood_handler._update_group_card(self.api, group_id, mood_val)
                            except Exception as e:
                                _log.warning(f"设置群名片失败: {e}")
                        except Exception as e:
                            _log.warning(f"处理 ##set_emotion 指令失败: {e}")
                        continue
                    try:
                        res = await self._qq_post_group_msg(group_id, text=line, reply=reply_id if is_first_message else None)
                    except Exception as e:
                        _log.error(f"发送消息失败: {e}")
                        res = None
                    
                    # 保存消息ID
                    if res:
                        last_sent_id = str(res)
                        # 记录机器人发送的回复到群历史
                        try:
                            import time as _time
                            bot_qq = self.config_manager.get_bt_uin() or "812"
                            bot_resp = BotResponse(timestamp=float(_time.time()), message=line, qq=str(bot_qq))
                            self.log_manager.save_bot_response(str(group_id), bot_resp)
                        except Exception as e:
                            _log.warning(f"保存机器人回复日志失败: {e}")
                        is_first_message = False  # 发送成功后，标记不再是第一条消息
                    
                    await asyncio.sleep(line_pause_multiplier * max(1, len(line)))
                
                # 段间短暂停顿
                await asyncio.sleep(pause_multiplier * len(para))
                
        except Exception as e:
            _log.error(f"发送回复消息失败: {e}")
    