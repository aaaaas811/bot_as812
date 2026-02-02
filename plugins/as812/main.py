"""as812插件主入口（重构版）"""
import asyncio
import re
import os
import base64
import sys
import subprocess
from pathlib import Path
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.plugin_system import filter_registry
from ncatbot.core.message import GroupMessage, PrivateMessage
from ncatbot.utils.logger import get_log

from .core.config_manager import ConfigManager, PromptManager
from .core.log_manager import LogManager
from .handlers.message_handler import MessageHandler
from .handlers.response_handler import ResponseHandler
from .handlers.mood_handler import MoodHandler
from .handlers.command_handler import CommandHandler
from .models.message_models import BotResponse

import bot_state

_log = get_log()

bot = CompatibleEnrollment()  # 兼容回调函数注册器


class as812(BasePlugin):
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
        
        _log.info(f"{self.name} 插件已加载 (v{self.version})")
        # 以子进程方式启动可视化面板，避免在主进程导入 tkinter/PIL
        try:
            script_path = Path(__file__).parent / "visual_panel.py"
            args = [sys.executable, str(script_path), str(self._assets_dir), str(Path(__file__).parent / "logs")]
            try:
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _log.info("as812 可视化面板已以子进程启动")
            except Exception as e:
                _log.warning(f"启动 as812 可视化面板失败: {e}")
        except Exception as e:
            _log.warning(f"准备启动 visual_panel 失败: {e}")
    
    @filter_registry.group_filter
    @bot_state.ignore_if_sleeping()
    async def on_group_event(self, msg: GroupMessage):
        """群事件处理"""
        if msg.raw_message == "测试as812" and msg.user_id == bot_state.MASTER_UIN:
            try:
                await self.api.post_group_msg(msg.group_id, text="NCatBot插件as812测试成功喵")
            except Exception as e:
                _log.error(f"发送测试消息失败: {e}")
    
    @filter_registry.group_filter
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, msg: GroupMessage):
        """群消息处理"""
        _log.info(f"{msg.sender.nickname}({msg.sender.user_id}): {msg.raw_message[:10]}")
        
        # 检查机器人是否被禁言
        if await self.mood_handler.is_bot_muted(self.api, msg.group_id):
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
            await self._send_response(msg.group_id, response)
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
    
    @filter_registry.private_filter
    @bot_state.ignore_if_sleeping()
    async def on_private_message(self, msg: PrivateMessage):
        """私聊消息处理"""
        super_user = self.config_manager.get_super_user()
        if str(msg.user_id) != super_user:
            return
        
        await self.command_handler.handle_private_command(
            self.api, 
            msg.user_id, 
            msg.raw_message.strip()
        )
    
    async def _send_response(self, group_id: int, response: str):
        """发送回复消息"""
        try:
            pause_multiplier, line_pause_multiplier = self.config_manager.get_pause_multipliers()
            
            # 将回复按空行分段
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", response) if p.strip()]
            last_sent_id = None
            
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
                                        res = await self.api.post_group_msg(group_id, image=f"base64://{b64}")
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

                                    sent = True
                                    break

                            if not sent:
                                # 未找到对应文件，发送提示文本
                                try:
                                    res = await self.api.post_group_msg(group_id, f"表情包不存在: {emoji_name}")
                                except Exception as e:
                                    _log.error(f"发送消息失败: {e}")
                                    res = None

                                if res:
                                    last_sent_id = str(res)

                            # 表情包指令处理完毕，继续下一行
                        except Exception as e:
                            _log.warning(f"处理表情包指令失败: {e}")
                        continue
                    if line == "##revoke":
                        if last_sent_id:
                            try:
                                await self.api.delete_msg(last_sent_id)
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
                        res = await self.api.post_group_msg(group_id, line)
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
                    
                    await asyncio.sleep(line_pause_multiplier * max(1, len(line)))
                
                # 段间短暂停顿
                await asyncio.sleep(pause_multiplier * len(para))
                
        except Exception as e:
            _log.error(f"发送回复消息失败: {e}")
    