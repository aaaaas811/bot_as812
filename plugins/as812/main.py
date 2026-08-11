"""as812插件主入口（重构版）"""
import sdk_compat  # noqa: F401

import asyncio
import re
import os
import base64
import sys
import subprocess
import random
import time
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
from .handlers.sender import ResponseSender
from .handlers.command_handler import CommandHandler
from .handlers.bilibili_handler import BilibiliHandler
from .models.message_models import BotResponse
from .responses.CatCatRes import cat_cat_response
from .rag import RAGManager, RAGConfig

import bot_state
from uapi import UapiClient
from uapi.errors import UapiError

_log = get_log()

# 导入素描本插件的绘图工具
_SKETCHBOOK_UTILS = Path(__file__).parent.parent / "Anans_sketchbook_chatbox_ncatbot" / "utils"
_SKETCHBOOK_AVAILABLE = False
if _SKETCHBOOK_UTILS.exists():
    if str(_SKETCHBOOK_UTILS) not in sys.path:
        sys.path.insert(0, str(_SKETCHBOOK_UTILS))
    try:
        from text_fit_draw import draw_text_auto  # type: ignore[import-not-found]
        from config import Config as SketchConfig  # type: ignore[import-not-found]
        _SKETCHBOOK_AVAILABLE = True
    except ImportError:
        _log.warning("素描本绘图工具导入失败，帮我说将使用文本模式")


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
        self.rag_manager = None
        self._assets_dir = Path(__file__).parent / "assests"
        self._private_chat_enabled = False
    
    async def on_load(self):
        """插件加载时执行"""
        _log.info("as812插件加载中……")
        
        # 初始化各个管理器
        self.config_manager = ConfigManager()
        self.prompt_manager = PromptManager()
        self.log_manager = LogManager()

        # 初始化 RAG 管理器
        try:
            rag_enabled = self.config_manager.get("rag_enabled", False)
            rag_config = RAGConfig(
                enabled=rag_enabled,
                embedding_mode=self.config_manager.get("rag_embedding_mode", "api"),
                embedding_model=self.config_manager.get("rag_embedding_model", "text-embedding-3-small"),
                embedding_dim=int(self.config_manager.get("rag_embedding_dim", 1536)),
                top_k=int(self.config_manager.get("rag_top_k", 5)),
                similarity_threshold=float(self.config_manager.get("rag_similarity_threshold", 0.5)),
                chunk_size=int(self.config_manager.get("rag_chunk_size", 512)),
                chunk_overlap=int(self.config_manager.get("rag_chunk_overlap", 64)),
                chunk_strategy=self.config_manager.get("rag_chunk_strategy", "paragraph"),
                trigger_mode=self.config_manager.get("rag_trigger_mode", "keyword"),
                trigger_keywords=self.config_manager.get("rag_trigger_keywords", ["什么是", "怎么", "如何", "攻略", "帮助", "help"]),
                debug=self.config_manager.get("rag_debug", False),
            )
            self.rag_manager = RAGManager(config=rag_config)
            _log.info(f"RAG 管理器已初始化 (enabled={rag_enabled})")
        except ImportError as e:
            _log.warning(f"RAG 管理器初始化失败（缺少依赖）: {e}，RAG 功能已禁用")
            self.rag_manager = None
        except Exception as e:
            _log.warning(f"RAG 管理器初始化失败: {e}，RAG 功能已禁用")
            self.rag_manager = None

        self.message_handler = MessageHandler(self.config_manager, self.log_manager)
        self.mood_handler = MoodHandler(self.config_manager)
        self.response_handler = ResponseHandler(
            self.config_manager,
            self.log_manager,
            self.message_handler,
            self.rag_manager,
            self.mood_handler
        )
        # 展示层：发送/渲染回复（表情包、指令、节奏）
        self.sender = ResponseSender(
            self.config_manager,
            self.log_manager,
            self.mood_handler,
            self._assets_dir,
            self._qq_post_group_msg,
            self._qq_post_private_msg,
            self._qq_delete_msg,
            self._set_emotion,
        )
        self.command_handler = CommandHandler(
            self.config_manager,
            self.prompt_manager,
            self.log_manager,
            self.rag_manager
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

    async def _qq_post_private_msg(self, user_id, **kwargs):
        """兼容不同 SDK 版本的私聊消息发送接口。"""
        qq_api = getattr(self.api, "qq", None)
        if qq_api is not None and hasattr(qq_api, "post_private_msg"):
            return await qq_api.post_private_msg(user_id, **kwargs)
        if hasattr(self.api, "post_private_msg"):
            return await self.api.post_private_msg(user_id, **kwargs)
        raise AttributeError("当前 SDK 未提供 post_private_msg 接口")

    async def _handle_private_chat(self, msg):
        """处理 MASTER_UIN 的私聊 AI 聊天"""
        user_id = str(msg.user_id)
        private_group_id = f"private_{user_id}"

        # 获取提示词和 API 密钥
        cat_prompt = self.prompt_manager.load_prompt()
        api_key = self.config_manager.get_api_key()
        if not api_key:
            _log.error("API密钥未配置")
            await self._qq_post_private_msg(msg.user_id, text="API密钥未配置，无法聊天")
            return

        # 解析私聊消息
        chat_message = self.message_handler.parse_private_message(msg)
        _log.info(f"私聊 {chat_message.user.nickname}({user_id}): {chat_message.message[:20]}")

        # 保存用户消息到私聊历史
        self.log_manager.save_group_message(private_group_id, chat_message)

        # 构建聊天历史
        chat_history = self.message_handler.build_chat_history(
            private_group_id, chat_message
        )

        # 注入当前心情（若已设置），让回复带有情绪
        self.mood_handler.inject_mood(chat_history, private_group_id)

        # RAG 检索
        rag_context = ""
        if self.rag_manager and self.rag_manager.should_retrieve(chat_message.message):
            rag_context, _ = self.rag_manager.retrieve(chat_message.message)

        # 生成回复
        _log.info("开始生成私聊回复……")
        image_api_key = self.config_manager.get_image_api_key()
        response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, rag_context)

        if not response:
            _log.info("私聊回复为空")
            return

        _log.info(f"812私聊回复：{response[:50]}")

        # 保存机器人回复到私聊历史
        bot_qq = self.config_manager.get_bt_uin() or "812"
        bot_response = BotResponse(
            timestamp=time.time(),
            message=response,
            qq=str(bot_qq)
        )
        self.log_manager.save_bot_response(private_group_id, bot_response)

        # 发送回复
        await self.sender.send_private_response(msg.user_id, response)

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
        text = msg.raw_message or ""
        # 群内命令路由。
        # 注意：/贴表情 的消息带 QQ 表情段时 raw_message 顺序可能不固定（face CQ 码在前），
        # 因此"贴表情"按"文本含 /贴表情 字样"判定，而非仅匹配开头。
        if text.startswith("/") or "/贴表情" in text:
            # 群内命令路由
            if text.startswith("/记忆") or text.startswith("/rag_"):
                await self.command_handler.handle_group_rag_command(
                    self.api.qq, str(msg.group_id), str(msg.sender.user_id), text, msg.sender.role
                )
            elif "/贴表情" in text:
                # 需要引用消息 ID 与表情段：先解析消息
                try:
                    chat_message = self.message_handler.parse_group_message(msg)
                    await self.command_handler.handle_group_emoji_like(
                        self.api.qq, str(msg.group_id), str(msg.sender.user_id),
                        text, chat_message.reply_id, chat_message.message_array
                    )
                except Exception as e:
                    _log.error(f"处理 /贴表情 失败: {e}")
                    try:
                        await self.api.qq.post_group_msg(msg.group_id, text=f"贴表情出错了…（{e}）")
                    except Exception:
                        pass
            elif text == "/撤回记录":
                await self.command_handler.handle_group_revoked_history(
                    self.api.qq, str(msg.group_id)
                )
            return  # 其他 / 命令直接跳过

        # 兜底：raw_message 不含 /贴表情 时（纯表情+引用消息 raw_message 可能为空），
        # 若消息含 face 段则解析后判断文本是否包含命令字样。
        if "/贴表情" not in text:
            has_face = False
            for seg in getattr(event, "message", None) or []:
                try:
                    seg_type = seg.get("type") if isinstance(seg, dict) else (
                        getattr(seg, "msg_seg_type", None) or seg.__class__.__name__.lower()
                    )
                    if str(seg_type).lower() in ("face", "emoji"):
                        has_face = True
                        break
                except Exception:
                    continue
            if has_face:
                try:
                    chat_message = self.message_handler.parse_group_message(msg)
                    if "/贴表情" in (chat_message.message or ""):
                        await self.command_handler.handle_group_emoji_like(
                            self.api.qq, str(msg.group_id), str(msg.sender.user_id),
                            text, chat_message.reply_id, chat_message.message_array
                        )
                        return
                except Exception as e:
                    _log.error(f"处理 /贴表情（兜底）失败: {e}")

        # 812记忆 命令（群内自然语言添加知识）
        if text.startswith("812记忆") or text.startswith("812记一下") or text.startswith("812学习"):
            await self.command_handler.handle_group_rag_command(
                self.api.qq, str(msg.group_id), str(msg.sender.user_id), text, msg.sender.role
            )
            return

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
        await self._expand_reply_content(chat_message)

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
            await self.sender.send_group_response(msg.group_id, response, reply_id)
        else:
            # 尝试主动回复
            active_group_ids = self.config_manager.get_active_group_ids()
            if str(msg.group_id) in active_group_ids:
                active_response = await self.response_handler.process_active_response(
                    api_key,
                    cat_prompt,
                    str(msg.group_id)
                )
                if active_response:
                    await self.sender.send_group_response(msg.group_id, active_response)
                else:
                    _log.info("未发送主动回复：延迟条件未满足或无可用用户消息")
            else:
                _log.info(
                    f"未进入主动回复：当前群 {msg.group_id} 不在 active_group_ids({active_group_ids}) 中"
                )
    
    @registrar.qq.on_private_message()
    @bot_state.ignore_if_sleeping()
    async def on_private_message(self, event: PrivateMessageEvent):
        """私聊消息处理"""
        msg = event
        super_user = self.config_manager.get_super_user()
        if str(msg.user_id) != super_user:
            return

        raw_text = (msg.raw_message or "").strip()

        # 私聊模式开关（仅 MASTER_UIN）
        if str(msg.user_id) == bot_state.MASTER_UIN:
            if raw_text == "开启私聊":
                self._private_chat_enabled = True
                await self._qq_post_private_msg(msg.user_id, text="私聊模式已开启")
                return
            if raw_text == "关闭私聊":
                self._private_chat_enabled = False
                await self._qq_post_private_msg(msg.user_id, text="私聊模式已关闭")
                return

        # 安安帮我说：xxx（图片模式）| 帮我说：xxx（纯文本模式）
        img_match = re.match(r"^安安帮我说[：:]\s*(.+)$", raw_text)
        txt_match = re.match(r"^帮我说[：:]\s*(.+)$", raw_text)
        match = img_match or txt_match
        if match:
            use_image = bool(img_match)
            active_group_id = self.config_manager.get_active_group_id()
            qq_api = getattr(self.api, "qq", None)
            if not active_group_id:
                if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                    await qq_api.post_private_msg(msg.user_id, text="active_group_id 未配置，转述失败")
                return

            content = match.group(1).strip()
            if not content:
                if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                    await qq_api.post_private_msg(msg.user_id, text="格式错误，请使用：帮我说：内容 或 安安帮我说：内容")
                return

            # 纯文本模式（帮我说）
            if not use_image or not _SKETCHBOOK_AVAILABLE:
                say_text = f"811说\"{content}\""
                try:
                    await self._qq_post_group_msg(int(active_group_id), text=say_text)
                    if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                        await qq_api.post_private_msg(msg.user_id, text=f"已转述到群 {active_group_id}")
                except Exception as e:
                    _log.error(f"私聊转述到群失败: {e}")
                    if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                        await qq_api.post_private_msg(msg.user_id, text=f"转述失败: {e}")
                return

            # 图片模式（安安帮我说）
            emotion_list = ["base", "开心", "生气", "无语", "脸红", "病娇",
                            "哭泣", "害怕", "惊讶", "激动", "闭眼", "难受"]
            emotion = random.choice(emotion_list)

            emotion_mapping = {
                "base": "base.png", "开心": "开心.png", "生气": "生气.png",
                "无语": "无语.png", "脸红": "脸红.png", "病娇": "病娇.png",
                "哭泣": "哭泣.png", "害怕": "害怕.png", "惊讶": "惊讶.png",
                "激动": "激动.png", "闭眼": "闭眼.png", "难受": "难受.png",
            }

            base_images_dir = _SKETCHBOOK_UTILS / "BaseImages"
            base_image_path = str(base_images_dir / emotion_mapping[emotion])

            if not os.path.exists(base_image_path):
                _log.error(f"底图文件不存在: {base_image_path}")
                await self._qq_post_group_msg(int(active_group_id), text=f"811说\"{content}\"")
                if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                    await qq_api.post_private_msg(msg.user_id, text=f"已转述到群 {active_group_id}")
                return

            try:
                sketch_config = SketchConfig()
                font_path = str(_SKETCHBOOK_UTILS / sketch_config.font_file)
                overlay_path = (
                    str(_SKETCHBOOK_UTILS / sketch_config.base_overlay_file)
                    if sketch_config.use_base_overlay
                    else None
                )

                png_bytes = await asyncio.to_thread(
                    draw_text_auto,
                    image_source=base_image_path,
                    top_left=sketch_config.text_box_topleft,
                    bottom_right=sketch_config.image_box_bottomright,
                    text=f"811：{content}",
                    color=(0, 0, 0),
                    max_font_height=64,
                    font_path=font_path if os.path.exists(font_path) else None,
                    image_overlay=overlay_path if overlay_path and os.path.exists(overlay_path) else None,
                    wrap_algorithm=sketch_config.text_wrap_algorithm,
                )

                image_base64 = base64.b64encode(png_bytes).decode('utf-8')
                await self._qq_post_group_msg(int(active_group_id), image='base64://' + image_base64)
                if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                    await qq_api.post_private_msg(msg.user_id, text=f"已转述到群 {active_group_id}（表情：{emotion}）")
            except Exception as e:
                _log.error(f"私聊转述到群失败: {e}")
                if qq_api is not None and hasattr(qq_api, "post_private_msg"):
                    await qq_api.post_private_msg(msg.user_id, text=f"转述失败: {e}")
            return

        # MASTER_UIN 私聊 AI 聊天（需开启私聊模式）
        if str(msg.user_id) == bot_state.MASTER_UIN and self._private_chat_enabled:
            is_known_command = (
                raw_text in ("view_config", "prompt", "rag_stats", "rag_list",
                             "rag_clear", "rag_enable", "rag_disable")
                or raw_text.startswith("set_prompt")
                or raw_text.startswith("set_")
                or raw_text.startswith("rag_add ")
                or raw_text.startswith("rag_import ")
                or raw_text.startswith("rag_remove ")
            )
            if not is_known_command:
                await self._handle_private_chat(msg)
                return

        await self.command_handler.handle_private_command(
            self.api.qq,
            msg.user_id,
            raw_text
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

    @registrar.qq.on_group_recall()
    @bot_state.ignore_if_sleeping()
    async def on_group_recall(self, event):
        """群消息撤回：记录被撤回的消息内容（供 /撤回记录 查询）"""
        try:
            group_id = str(event.group_id)
            message_id = str(event.message_id)
            user_id = str(getattr(event, "user_id", "") or "")
            operator_id = str(getattr(event, "operator_id", "") or "")
            _log.info(f"收到撤回事件: group={group_id} msg={message_id} user={user_id} operator={operator_id}")

            # 机器人自己撤回（##revoke）不记录，避免噪音
            bot_uin = self.config_manager.get_bt_uin()
            if bot_uin and operator_id == bot_uin:
                _log.info(f"撤回者为机器人自身，跳过记录: {message_id}")
                return

            # 撤回事件本身不含消息内容，从本地历史按 message_id 找回
            record = self.log_manager.find_message_by_id(group_id, message_id)
            if not record:
                _log.info(f"撤回消息无本地记录（可能早于 bot 启动或 message_id 不匹配），跳过: {message_id}")
                return

            record.setdefault("revoked_at", time.time())
            self.log_manager.save_revoked_message(group_id, record)
            _log.info(f"已记录撤回消息 {message_id}（{group_id}）")
        except Exception as e:
            _log.warning(f"记录撤回消息失败: {e}")

    async def _set_emotion(self, group_id: int, mood: str) -> None:
        """##set_emotion 指令副作用：保存心情文件并更新群名片（不发送到群）"""
        try:
            try:
                self.mood_handler.save_mood_state(str(group_id), {"mood": mood})
            except Exception as e:
                _log.warning(f"保存心情文件失败: {e}")
            try:
                await self.mood_handler._update_group_card(self.api, group_id, mood)
            except Exception as e:
                _log.warning(f"设置群名片失败: {e}")
        except Exception as e:
            _log.warning(f"处理 ##set_emotion 指令失败: {e}")

    async def _expand_reply_content(self, chat_message) -> None:
        """尝试拉取被引用消息的原文，展开为 [引用:昵称:内容] 供模型理解上下文。"""
        try:
            reply_id = getattr(chat_message, "reply_id", None)
            if not reply_id:
                return
            try:
                orig_event = await self._qq_get_msg(reply_id)
                orig_text = self._extract_referenced_text(orig_event)
                if not orig_text:
                    return
                label = self._extract_referenced_sender(orig_event)
                expanded = f"[引用:{label}:{orig_text}]" if label else f"[引用:{orig_text}]"
                # 若解析阶段已将简单引用占位加入（如 [引用:efrfr]），先移除，避免重复
                chat_msg = chat_message.message or ""
                chat_msg = re.sub(r'^\[引用:[^\]]+\]\s*', '', chat_msg, count=1)
                chat_message.message = f"{expanded} " + chat_msg
            except Exception as e:
                _log.debug(f"拉取引用消息失败: {e}")
        except Exception:
            pass

    @staticmethod
    def _extract_referenced_text(event) -> str:
        """从被引用消息事件中提取文本（兼容 raw_message 与 message 段数组）。"""
        try:
            if getattr(event, "raw_message", None):
                return str(event.raw_message)
        except Exception:
            pass
        try:
            parts = []
            for seg in getattr(event, "message", None) or []:
                try:
                    if isinstance(seg, dict):
                        if seg.get("type") == "text":
                            parts.append(seg.get("data", {}).get("text", ""))
                    elif getattr(seg, "msg_seg_type", None) == "text":
                        parts.append(getattr(seg, "text", ""))
                except Exception:
                    continue
            return "".join(parts).strip()
        except Exception:
            return ""
        return ""

    @staticmethod
    def _extract_referenced_sender(event) -> str:
        """从被引用消息事件中提取发送者标识（card 优先，其次昵称、QQ）。"""
        try:
            sender = getattr(event, "sender", None)
            if sender is not None:
                card = getattr(sender, "card", None) or getattr(sender, "nickname", None) or getattr(sender, "user_id", None)
                if card:
                    return str(card)
            try:
                sender = event.get("sender", {}) if isinstance(event, dict) else {}
                card = sender.get("card") or sender.get("nickname")
                if card:
                    return str(card)
            except Exception:
                pass
        except Exception:
            pass
        return ""

