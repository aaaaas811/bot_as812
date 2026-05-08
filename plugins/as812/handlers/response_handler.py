"""响应处理器"""
import asyncio
import time
import random
from typing import Optional, Tuple
from ncatbot.utils.logger import get_log
from ..models.message_models import ChatMessage, BotResponse
from ..core.config_manager import ConfigManager
from ..core.log_manager import LogManager
from .message_handler import MessageHandler
from ..responses.CatCatRes import cat_cat_response

_log = get_log()


class ResponseHandler:
    """响应处理器类"""

    def __init__(self, config_manager: ConfigManager, log_manager: LogManager, message_handler: MessageHandler, rag_manager=None):
        self.config_manager = config_manager
        self.log_manager = log_manager
        self.message_handler = message_handler
        self.rag_manager = rag_manager
        # 缓存每个群组机器人最后一条消息的时间戳，避免每次从日志中遍历查找
        self._last_bot_message_time = {}
        # 按群组维护主动回复互斥锁，避免并发消息导致主动回复重复触发
        self._active_reply_locks = {}
    
    async def process_passive_response(self, 
                                      api_key: str, 
                                      msg: ChatMessage, 
                                      group_id: str, 
                                      cat_prompt: str) -> Optional[str]:
        """处理被动回复（由用户消息触发）"""
        # 关键判断：只有被@或消息中包含812时才回复
        if not msg.force_reply:
            return None
        
        user_qq = msg.user.qq
        
        # 加载个人数据
        _, user_info_str, personal_log_file = \
            await self._load_personal_data(group_id, user_qq)
        
        # 更新用户信息
        current_user_info = self.message_handler.get_user_info_string(msg)
        if user_info_str != current_user_info:
            self.log_manager.update_personal_log_header(personal_log_file, current_user_info)
            user_info_str = current_user_info
        
        # 构建聊天历史
        chat_history = self.message_handler.build_chat_history(
            group_id, msg
        )
        
        
        # RAG 检索
        rag_context = ""
        if self.rag_manager and self.rag_manager.should_retrieve(msg.message):
            rag_context, _ = self.rag_manager.retrieve(msg.message)

        # 生成回复
        _log.info("开始生成回复……")
        image_api_key = self.config_manager.get_image_api_key()
        response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, rag_context)
        
        if not response:
            return None
        
        _log.info(f"812：{response}")
        
        # 保存机器人回复
        bot_qq = self.config_manager.get_bt_uin()
        bot_response = BotResponse(
            timestamp=time.time(),
            message=response,
            qq=bot_qq
        )
        
        # 记录内存中的最后回复时间，优先使用此时间判断主动回复延迟
        try:
            self._last_bot_message_time[group_id] = bot_response.timestamp
        except Exception:
            pass
        
        # 保存到个人日志
        self._append_to_personal_chat_history(personal_log_file, f"812：{response}")
        
        return response
    
    async def process_active_response(self, 
                                     api_key: str, 
                                     cat_prompt: str, 
                                     group_id: str) -> Optional[str]:
        """处理主动回复"""
        group_lock = self._active_reply_locks.get(group_id)
        if group_lock is None:
            group_lock = asyncio.Lock()
            self._active_reply_locks[group_id] = group_lock

        # 避免并发消息同时进入主动回复链路
        if group_lock.locked():
            return None

        async with group_lock:
            # 检查延迟
            if not await self._check_active_reply_delay(group_id):
                return None
        
            # 获取最新的用户消息
            current_message, user_qq = self._get_latest_user_message(group_id)
            if not current_message:
                _log.warning("无合适的新消息，无法主动回复")
                return None
        
            # 加载个人数据
            personal_history, user_info_str, personal_log_file = \
                await self._load_personal_data(group_id, user_qq)
        
            # 记录用户消息到个人日志
            self._append_to_personal_chat_history(personal_log_file, current_message["message"])
        
            # 更新用户信息
            current_user_info = (
                f"QQ昵称: {current_message['nickname']}, "
                f"QQ号: {current_message['qq']}, "
                f"群昵称: {current_message['card']}, "
                f"群权限: {self.message_handler.map_role(current_message['role'])}, "
                f"群头衔: {current_message['title']}"
            )
        
            if user_info_str != current_user_info:
                self.log_manager.update_personal_log_header(personal_log_file, current_user_info)
        
            # 构建聊天历史
            chat_message = ChatMessage.from_dict(current_message)
            chat_history = self.message_handler.build_chat_history(
                group_id, chat_message
            )

            # 主动回复场景：若当前消息无文本但包含图片/表情段，提示模型优先考虑识图工具。
            try:
                raw_text = str(current_message.get("message", "") or "").strip()
                msg_arr = current_message.get("message_array") or []
                has_visual_segment = False
                for seg in msg_arr:
                    if not isinstance(seg, dict):
                        continue
                    seg_type = str(seg.get("type", "") or "").lower()
                    if (
                        "image" in seg_type
                        or seg_type in ("face", "sticker")
                        or seg.get("url")
                        or seg.get("file")
                        or seg.get("image_url")
                        or seg.get("file_url")
                    ):
                        has_visual_segment = True
                        break

                if not raw_text and has_visual_segment:
                    chat_history.append(
                        {
                            "role": "system",
                            "content": "当前触发消息没有文本，仅包含图片/表情。请优先考虑调用 vision_recognize 分析图片后再回复。",
                        }
                    )
            except Exception:
                pass
        
            # RAG 检索
            rag_context = ""
            if self.rag_manager and self.rag_manager.should_retrieve(current_message.get("message", "")):
                rag_context, _ = self.rag_manager.retrieve(current_message.get("message", ""))

            # 生成回复
            _log.info("开始主动生成回复……")
            image_api_key = self.config_manager.get_image_api_key()
            response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, rag_context)
        
            if not response:
                return None
        
            _log.info(f"812：{response}")
        
            # 检查是否需要总结
        
            # 保存机器人回复
            bot_qq = self.config_manager.get_bt_uin()
            bot_response = BotResponse(
                timestamp=time.time(),
                message=response,
                qq=bot_qq
            )
        
            # 保存到群历史
            self.log_manager.save_bot_response(group_id, bot_response)
        
            # 保存到个人日志
            self._append_to_personal_chat_history(personal_log_file, f"812：{response}")
            # 记录内存中的最后回复时间，优先使用此时间判断主动回复延迟
            try:
                self._last_bot_message_time[group_id] = bot_response.timestamp
            except Exception:
                pass
        
            # 更新延迟
            self._update_active_reply_delay()
        
            return response
    
    async def _load_personal_data(self, group_id: str, user_qq: str) -> Tuple[list, str, str]:
        """加载个人数据（异步包装）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self.log_manager.load_personal_log, 
            group_id, 
            user_qq
        )

    
    async def _check_active_reply_delay(self, group_id: str) -> bool:
        """检查主动回复延迟"""
        base_delay, current_delay, random_range = self.config_manager.get_active_reply_config()
        
        # 如果当前延迟为0，生成初始延迟
        if current_delay <= 0:
            current_delay = random.randint(
                int(base_delay * (1 - random_range)), 
                int(base_delay * (1 + random_range))
            )
            self.config_manager.update_active_delay(current_delay)
        
        # 获取机器人最后一条消息的时间，优先使用内存缓存，缓存缺失时回退到日志查找
        last_bot_message_time = self._last_bot_message_time.get(group_id, 0)

        if last_bot_message_time == 0:
            bot_qq = str(self.config_manager.get_bt_uin() or "")
            messages = self.log_manager.load_group_history(group_id, limit=100)
            for msg in reversed(messages):
                if str(msg.get("qq", "")) == bot_qq:
                    timestamp = msg.get("timestamp")
                    if timestamp:
                        last_bot_message_time = float(timestamp)
                        break

        # 如果从未发送过消息，跳过本次主动回复
        if last_bot_message_time == 0:
            _log.info("主动回复跳过：未找到机器人历史回复时间")
            return False
        
        # 检查延迟
        current_time = time.time()
        time_since_last_reply = current_time - last_bot_message_time
        
        if time_since_last_reply < current_delay:
            _log.info(
                f"主动回复跳过：距离上次回复 {time_since_last_reply:.1f} 秒，未达到延迟 {current_delay} 秒"
            )
            return False
        
        _log.info(f"主动回复：距离上次回复 {time_since_last_reply:.1f} 秒，已超过延迟 {current_delay} 秒，开始处理")
        return True
    
    def _get_latest_user_message(self, group_id: str) -> Tuple[Optional[dict], Optional[str]]:
        """获取最新的用户消息"""
        bot_qq = str(self.config_manager.get_bt_uin() or "")
        messages = self.log_manager.load_group_history(group_id, limit=100)
        
        for msg in messages:
            msg_qq = str(msg.get("qq", ""))
            msg_content = msg.get("message", "")
            
            # 排除机器人自己的消息和命令消息
            if (msg_qq != bot_qq and 
                not msg_content.startswith("/")):
                return msg, msg_qq
        
        return None, None
    
    def _update_active_reply_delay(self) -> None:
        """更新主动回复延迟"""
        base_delay, _, random_range = self.config_manager.get_active_reply_config()
        
        new_delay = random.randint(
            int(base_delay * (1 - random_range)), 
            int(base_delay * (1 + random_range))
        )
        
        if self.config_manager.update_active_delay(new_delay):
            _log.info(f"主动回复成功，已生成新的随机延迟：{new_delay} 秒")
    def _append_to_personal_chat_history(self, log_path: str, content: str) -> None:
        """向个人聊天记录追加内容"""
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                file_content = f.read()

            parts = file_content.split("\n\n过往聊天记录：\n")
            if len(parts) == 2:
                header = parts[0] + "\n\n过往聊天记录：\n"
                existing_records = parts[1].strip().split("\n") if parts[1].strip() else []
                existing_records.append(content)

                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(header + "\n".join(existing_records) + "\n")
        except Exception as e:
            _log.error(f"更新个人聊天记录失败: {e}")