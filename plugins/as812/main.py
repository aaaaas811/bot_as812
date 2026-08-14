"""as812插件主入口（重构版）"""
import sdk_compat  # noqa: F401

import asyncio
import json
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
from .models.message_models import BotResponse, ChatMessage, UserInfo
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
            self.mood_handler,
            self._get_image_by_file,
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

        # 写入连接状态文件供面板读取
        try:
            conn_file = Path(__file__).parent / "logs" / "_connection.json"
            conn_file.write_text(json.dumps({
                "qq": True, "bilibili": True, "updated_at": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        # 启动面板指令轮询（读取面板写入的 _panel_cmd.json）
        self._panel_cmd_path = Path(__file__).parent / "logs" / "_panel_cmd.json"
        self._panel_cmd_mtime = 0.0
        # 写入启动确认（面板可据此判断 bot 端轮询是否就绪）
        try:
            result_file = Path(__file__).parent / "logs" / "_panel_result.json"
            result_file.write_text(json.dumps({
                "cmd": "系统", "result": "面板指令轮询已启动，等待指令…",
                "time": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._poll_panel_commands())
            _log.info("[面板] 指令轮询任务已创建")
        except RuntimeError:
            _log.warning("[面板] 无法获取事件循环，面板交互功能不可用")

        # 以子进程方式启动可视化面板，避免在主进程导入 tkinter/PIL
        try:
            script_path = Path(__file__).parent / "visual_panel.py"
            args_str = f'"{script_path}" "{self._assets_dir}" "{Path(__file__).parent / "logs"}" "{Path(__file__).parent / "config"}" {os.getpid()}'
            try:
                if os.name == "nt":
                    # Windows: 用 cmd /c start 完全独立启动，与父进程无任何关联
                    subprocess.Popen(
                        f'start "" "{sys.executable}" {args_str}',
                        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        [sys.executable, str(script_path), str(self._assets_dir),
                         str(Path(__file__).parent / "logs"), str(Path(__file__).parent / "config"),
                         str(os.getpid())],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                _log.info("as812 可视化面板已以子进程启动")
            except Exception as e:
                _log.warning(f"启动 as812 可视化面板失败: {e}")
        except Exception as e:
            _log.warning(f"准备启动 visual_panel 失败: {e}")

    async def on_unload(self):
        """插件卸载时清理资源。"""
        if self.bilibili_handler is not None:
            await self.bilibili_handler.on_unload(self.api)

    async def _get_image_by_file(self, file_name: str):
        """通过 NapCat 的 get_image action 按文件标识下载图片，返回本地路径。

        用于 QQ 图片 URL（gchat.qpic.cn 的 rkey）过期时的兜底取图。
        ncatbot 5.x 的 api.qq 是 QQAPIClient 门面，底层 NapCatBotAPI 在 api.qq._api。
        """
        try:
            if not file_name:
                _log.info("[识图兜底] file_name 为空")
                return None
            qq_api = getattr(self.api, "qq", None)
            if qq_api is None:
                _log.info("[识图兜底] api.qq 不存在")
                return None
            # 底层原始 API（NapCatBotAPI）有 _call，可调用 OneBot 11 标准 action
            raw_api = getattr(qq_api, "_api", None)
            call_fn = getattr(raw_api, "_call", None) if raw_api is not None else None
            if call_fn is None:
                _log.info(f"[识图兜底] 底层 API 无 _call 方法（raw_api={type(raw_api).__name__ if raw_api else None}）")
                return None
            resp = await call_fn("get_image", {"file": file_name})
            _log.info(f"[识图兜底] get_image 响应: {str(resp)[:200]}")
            data = resp.get("data") if isinstance(resp, dict) else {}
            local_file = None
            if isinstance(data, dict):
                local_file = data.get("file") or data.get("path")
            elif isinstance(data, str):
                local_file = data
            if not local_file:
                _log.warning(f"get_image 未返回文件路径: {resp}")
                return None
            if os.path.exists(local_file):
                _log.info(f"[识图兜底] 本地文件可用: {local_file}")
                return local_file
            _log.warning(f"get_image 返回的文件不存在: {local_file}")
        except Exception as e:
            _log.warning(f"按文件标识取图失败: {e}")
        return None

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
        response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, rag_context, self._get_image_by_file)

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

    # ==================== 群命令注册（SDK 装饰器） ====================

    @registrar.qq.on_group_command("测试as812")
    @bot_state.ignore_if_sleeping()
    async def cmd_test(self, event: GroupMessageEvent):
        """测试命令"""
        msg = self._adapt_group_event(event)
        if msg.user_id == bot_state.MASTER_UIN:
            await self._qq_post_group_msg(msg.group_id, text="NCatBot插件as812测试成功喵")

    @registrar.qq.on_group_command("/记忆", "812记忆", "812记一下", "812学习")
    @bot_state.ignore_if_sleeping()
    async def cmd_memory(self, event: GroupMessageEvent):
        """添加知识到 RAG"""
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_rag_command(
            self.api.qq, str(msg.group_id), str(msg.sender.user_id), msg.raw_message, msg.sender.role
        )

    @registrar.qq.on_group_command("/rag_stats")
    @bot_state.ignore_if_sleeping()
    async def cmd_rag_stats(self, event: GroupMessageEvent):
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_rag_command(
            self.api.qq, str(msg.group_id), str(msg.sender.user_id), "/rag_stats", msg.sender.role
        )

    @registrar.qq.on_group_command("/rag_list")
    @bot_state.ignore_if_sleeping()
    async def cmd_rag_list(self, event: GroupMessageEvent):
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_rag_command(
            self.api.qq, str(msg.group_id), str(msg.sender.user_id), "/rag_list", msg.sender.role
        )

    @registrar.qq.on_group_command("/rag_help")
    @bot_state.ignore_if_sleeping()
    async def cmd_rag_help(self, event: GroupMessageEvent):
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_rag_command(
            self.api.qq, str(msg.group_id), str(msg.sender.user_id), "/rag_help", msg.sender.role
        )

    @registrar.qq.on_group_command("/rag_remove")
    @bot_state.ignore_if_sleeping()
    async def cmd_rag_remove(self, event: GroupMessageEvent):
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_rag_command(
            self.api.qq, str(msg.group_id), str(msg.sender.user_id), msg.raw_message, msg.sender.role
        )

    @registrar.qq.on_group_command("/rag_enable", "/rag_disable")
    @bot_state.ignore_if_sleeping()
    async def cmd_rag_toggle(self, event: GroupMessageEvent):
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_rag_command(
            self.api.qq, str(msg.group_id), str(msg.sender.user_id), msg.raw_message, msg.sender.role
        )

    @registrar.qq.on_group_command("/撤回记录")
    @bot_state.ignore_if_sleeping()
    async def cmd_revoked(self, event: GroupMessageEvent):
        msg = self._adapt_group_event(event)
        await self.command_handler.handle_group_revoked_history(
            self.api.qq, str(msg.group_id)
        )

    @registrar.qq.on_group_command("/贴表情")
    @bot_state.ignore_if_sleeping()
    async def cmd_emoji_like(self, event: GroupMessageEvent):
        """贴表情命令（需要引用消息和表情段）"""
        msg = self._adapt_group_event(event)
        try:
            chat_message = self.message_handler.parse_group_message(msg)
            await self.command_handler.handle_group_emoji_like(
                self.api.qq, str(msg.group_id), str(msg.sender.user_id),
                msg.raw_message, chat_message.reply_id, chat_message.message_array
            )
        except Exception as e:
            _log.error(f"处理 /贴表情 失败: {e}")
            try:
                await self.api.qq.post_group_msg(msg.group_id, text=f"贴表情出错了…（{e}）")
            except Exception:
                pass

    # ==================== 群消息处理（非命令） ====================

    @registrar.qq.on_group_message()
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, event: GroupMessageEvent):
        """群消息处理（仅处理非命令消息：被动/主动回复）"""
        msg = self._adapt_group_event(event)
        _log.info(f"{msg.sender.nickname}({msg.sender.user_id}): {msg.raw_message[:10]}")

        # 忽略机器人自己的消息，防止自回复循环
        bot_uin = self.config_manager.get_bt_uin()
        if bot_uin and str(msg.sender.user_id) == str(bot_uin):
            return

        # 检查机器人是否被禁言（结果写入文件供面板读取）
        muted = await self.mood_handler.is_bot_muted(self.api, msg.group_id)
        try:
            mute_file = self.log_manager.base_log_dir / f"{msg.group_id}_mute.json"
            mute_file.write_text(json.dumps({
                "muted": muted, "checked_at": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        if muted:
            return

        # /贴表情 兜底：raw_message 不含 /贴表情 但消息含 face 段时，解析后判断
        text = msg.raw_message or ""
        if "/贴表情" not in text:
            for seg in getattr(event, "message", None) or []:
                try:
                    seg_type = seg.get("type") if isinstance(seg, dict) else (
                        getattr(seg, "msg_seg_type", None) or seg.__class__.__name__.lower()
                    )
                    if str(seg_type).lower() in ("face", "emoji"):
                        chat_message = self.message_handler.parse_group_message(msg)
                        if "/贴表情" in (chat_message.message or ""):
                            await self.cmd_emoji_like(event)
                            return
                        break
                except Exception:
                    continue

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

    async def _panel_chat(self, text: str) -> str:
        """模拟 as811 发消息给 bot，返回 bot 的回复（不发送到群）。"""
        try:
            api_key = self.config_manager.get_api_key()
            if not api_key:
                return "API 密钥未配置"

            cat_prompt = self.prompt_manager.load_prompt()

            # 构造 as811 的消息
            chat_message = ChatMessage(
                timestamp=time.time(),
                user=UserInfo(nickname="811", qq=str(bot_state.MASTER_UIN), card="", role="群主", title=""),
                message=text,
                force_reply=True,
            )

            # 构建聊天历史
            active_gid = self.config_manager.get_active_group_id() or "883744030"
            chat_history = self.message_handler.build_chat_history(active_gid, chat_message)

            # 注入心情
            self.mood_handler.inject_mood(chat_history, active_gid)

            # 调用 LLM 生成回复
            image_api_key = self.config_manager.get_image_api_key()
            rag_context = ""
            if self.rag_manager and self.rag_manager.should_retrieve(text):
                rag_context, _ = self.rag_manager.retrieve(text)

            response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, rag_context, self._get_image_by_file)
            return response or ""
        except Exception as e:
            _log.error(f"[面板] 聊天处理异常: {e}")
            return f"处理异常: {e}"

    async def _execute_panel_command(self, text: str) -> str:
        """执行面板命令并返回结果文本（不发送到群）。

        复用 command_handler 的逻辑，用 FakeApi 收集输出。
        """
        active_gid = self.config_manager.get_active_group_id() or "883744030"

        # FakeApi：收集 post_group_msg 的文本输出，不真正发送
        collected = []
        class FakeApi:
            async def post_group_msg(self, gid, text=None, **kw):
                if text:
                    collected.append(text)
            async def post_private_msg(self, uid, text=None, **kw):
                if text:
                    collected.append(text)

        fake_api = FakeApi()

        if text == "/撤回记录":
            await self.command_handler.handle_group_revoked_history(fake_api, active_gid)
        elif text == "/rag_stats":
            await self.command_handler.handle_group_rag_command(fake_api, active_gid, "", "/rag_stats", "")
        elif text == "/rag_list":
            await self.command_handler.handle_group_rag_command(fake_api, active_gid, "", "/rag_list", "")
        elif text == "/rag_help":
            await self.command_handler.handle_group_rag_command(fake_api, active_gid, "", "/rag_help", "")
        elif text.startswith("/记忆 ") or text.startswith("812记忆 "):
            await self.command_handler.handle_group_rag_command(fake_api, active_gid, "", text, "")
        elif text == "/helpMH":
            return (
                "直接发送集会码即可记录喵~\n/查询 获取集会列表\n"
                "/删除mhw 删除最近一个 MHW 集会码\n/删除mhr 删除最近一个 MHR 集会码\n"
                "/清空 清空所有集会码\n/爬取ws(wi,rs) 更新最新数据\n"
                "/怪物列表 列出已收录的怪物名称\n"
                "/ws(wi,rs)简介/弱点/肉质 怪物名字 查询对应数据"
            )
        else:
            return f"未知命令：{text}"

        return "\n".join(collected) if collected else "（命令已执行，无输出）"

    async def _poll_panel_commands(self):
        """轮询面板写入的 _panel_cmd.json，执行其中的指令。"""
        _log.info("[面板] 指令轮询已启动，每 2 秒检查一次")
        while True:
            try:
                if self._panel_cmd_path.exists():
                    mtime = self._panel_cmd_path.stat().st_mtime
                    if mtime != self._panel_cmd_mtime:
                        self._panel_cmd_mtime = mtime
                        data = json.loads(self._panel_cmd_path.read_text(encoding="utf-8"))
                        cmd = data.get("cmd", "")
                        text = data.get("text", "")
                        _log.info(f"[面板] 收到指令: cmd={cmd} text={text}")

                        result_file = Path(__file__).parent / "logs" / "_panel_result.json"

                        if cmd == "send" and text:
                            # 模拟 as811 发消息，触发 bot 被动回复，结果只在面板显示
                            try:
                                result = await self._panel_chat(text)
                                result_file.write_text(json.dumps({
                                    "cmd": f"811: {text}", "result": result or "（bot 选择不回复）",
                                    "time": time.time(),
                                }, ensure_ascii=False), encoding="utf-8")
                                _log.info(f"[面板] 聊天: 811说'{text}' → {str(result)[:50]}")
                            except Exception as e:
                                _log.error(f"[面板] 聊天失败: {e}")
                                result_file.write_text(json.dumps({
                                    "cmd": text, "result": f"处理失败: {e}",
                                    "time": time.time(),
                                }, ensure_ascii=False), encoding="utf-8")

                        elif cmd == "group_cmd" and text:
                            try:
                                result = await self._execute_panel_command(text)
                                result_file.write_text(json.dumps({
                                    "cmd": text, "result": result, "time": time.time(),
                                }, ensure_ascii=False), encoding="utf-8")
                                _log.info(f"[面板] 命令已执行: {text}")
                            except Exception as e:
                                _log.error(f"[面板] 命令执行失败: {e}")
                                result_file.write_text(json.dumps({
                                    "cmd": text, "result": f"执行失败: {e}", "time": time.time(),
                                }, ensure_ascii=False), encoding="utf-8")

                        elif cmd == "set_mood" and text:
                            try:
                                self.mood_handler.save_mood_state("", {"mood": text})
                                _log.info(f"[面板] 心情已保存: {text}")
                                for gid in self.config_manager.get_active_group_ids():
                                    try:
                                        await self.mood_handler._update_group_card(self.api, int(gid), text)
                                        _log.info(f"[面板] 群 {gid} 名片已更新: 812(bot)({text})")
                                    except Exception as e:
                                        _log.warning(f"[面板] 群 {gid} 名片更新失败: {e}")
                                result_file.write_text(json.dumps({
                                    "cmd": "设置心情", "result": f"心情已改为 {text}，群名片已更新",
                                    "time": time.time(),
                                }, ensure_ascii=False), encoding="utf-8")
                            except Exception as e:
                                _log.error(f"[面板] 设置心情失败: {e}")

                        elif cmd == "set_sleep":
                            try:
                                sleeping = bool(data.get("value", True))
                                bot_state.set_sleep(sleeping)
                                status = "开启" if sleeping else "关闭"
                                result_file.write_text(json.dumps({
                                    "cmd": "睡眠模式", "result": f"睡眠模式已{status}",
                                    "time": time.time(),
                                }, ensure_ascii=False), encoding="utf-8")
                                _log.info(f"[面板] 睡眠模式: {status}")
                            except Exception as e:
                                _log.error(f"[面板] 设置睡眠失败: {e}")
            except Exception as e:
                _log.error(f"[面板] 轮询异常: {e}")
            await asyncio.sleep(2.0)

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

