"""响应处理器"""
import asyncio
import time
import random
from typing import Optional, Tuple
from ncatbot.utils.logger import get_log
from ..models.message_models import ChatMessage
from ..core.config_manager import ConfigManager
from ..core.log_manager import LogManager
from .message_handler import MessageHandler
from ..responses.CatCatRes import cat_cat_response, get_reply_lock as _get_shared_reply_lock

_log = get_log()


class ResponseHandler:
    """响应处理器类"""

    def __init__(self, config_manager: ConfigManager, log_manager: LogManager, message_handler: MessageHandler, rag_manager=None, mood_handler=None, get_image_cb=None):
        self.config_manager = config_manager
        self.log_manager = log_manager
        self.message_handler = message_handler
        self.rag_manager = rag_manager
        self.mood_handler = mood_handler
        self.get_image_cb = get_image_cb  # async fn(file) -> 本地路径（NapCat get_image 兜底）
        # 缓存每个群组机器人最后一条消息的时间戳，避免每次从日志中遍历查找
        self._last_bot_message_time = {}
        # 按群组维护主动回复互斥锁，避免并发消息导致主动回复重复触发
        self._active_reply_locks = {}

    def _get_reply_lock(self, group_id: str) -> asyncio.Lock:
        """获取或创建群组对应的回复阻塞锁（跨插件共享）"""
        return _get_shared_reply_lock(group_id)

    def _inject_mood(self, chat_history: list, group_id: str) -> None:
        """将当前心情注入聊天上下文，让回复语气带有情绪（未设置时零 token 开销）。"""
        try:
            if self.mood_handler is not None:
                self.mood_handler.inject_mood(chat_history, group_id)
        except Exception:
            pass

    async def process_passive_response(self, 
                                      api_key: str, 
                                      msg: ChatMessage, 
                                      group_id: str, 
                                      cat_prompt: str,
                                      current_messages: list[ChatMessage] | None = None) -> Optional[str]:
        """处理被动回复（由用户消息触发）"""
        # 关键判断：只有被@或消息中包含812时才回复
        if not (msg.force_reply or any(item.force_reply for item in (current_messages or []))):
            return None

        # 与同群其他回复共享生成锁；新的批次等待旧请求取消并释放锁
        reply_lock = self._get_reply_lock(group_id)

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
            group_id, msg, current_messages
        )

        # 注入当前心情（若已设置），让回复带有情绪
        self._inject_mood(chat_history, group_id)

        # 生成回复；收拢器负责在新消息到来时取消本次生成
        _log.info("开始生成回复……")
        image_api_key = self.config_manager.get_image_api_key()
        async with reply_lock:
            response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, "", self.get_image_cb)

        if not response:
            return None

        _log.info(f"812：{response}")
        return response
    
    async def process_active_response(self,
                                     api_key: str,
                                     cat_prompt: str,
                                     group_id: str,
                                     current_messages: list[ChatMessage] | None = None) -> Optional[str]:
        """处理主动回复"""
        # 与同群其他回复共享生成锁
        reply_lock = self._get_reply_lock(group_id)

        group_lock = self._active_reply_locks.get(group_id)
        if group_lock is None:
            group_lock = asyncio.Lock()
            self._active_reply_locks[group_id] = group_lock

        # 等待前一个主动回复尝试退出，再检查延迟并生成当前批次
        async with group_lock:
            # 检查延迟
            if not await self._check_active_reply_delay(group_id):
                return None
        
            # 获取最新的用户消息
            if current_messages:
                chat_message = current_messages[-1]
                current_message = chat_message.to_dict()
                user_qq = chat_message.user.qq
            else:
                current_message, user_qq = self._get_latest_user_message(group_id)
            if not current_message:
                _log.warning("无合适的新消息，无法主动回复")
                return None
        
            # 加载个人数据
            personal_history, user_info_str, personal_log_file = \
                await self._load_personal_data(group_id, user_qq)
        
            # 构建聊天历史（复用统一格式化的用户信息，保持与被动回复一致）
            chat_message = ChatMessage.from_dict(current_message)
            current_user_info = self.message_handler.get_user_info_string(chat_message)

            if user_info_str != current_user_info:
                self.log_manager.update_personal_log_header(personal_log_file, current_user_info)

            chat_history = self.message_handler.build_chat_history(
                group_id, chat_message, current_messages
            )

            # 注入当前心情（若已设置），让回复带有情绪
            self._inject_mood(chat_history, group_id)

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
        
            # 生成回复；收拢器负责在新消息到来时取消本次生成
            _log.info("开始主动生成回复……")
            image_api_key = self.config_manager.get_image_api_key()
            async with reply_lock:
                response = await cat_cat_response(api_key, chat_history, cat_prompt, image_api_key, "", self.get_image_cb)
        
            if not response:
                return None
        
            _log.info(f"812：{response}")
            return response

    async def record_sent_response(self, group_id: str, msg: ChatMessage, response: str, active: bool = False) -> None:
        """在群消息开始发送后记录回复和主动回复计时。"""
        self._last_bot_message_time[group_id] = time.time()
        _, _, personal_log_file = await self._load_personal_data(group_id, msg.user.qq)
        self._append_to_personal_chat_history(personal_log_file, f"812：{response}")
        if active:
            self._update_active_reply_delay()
    
    async def _load_personal_data(self, group_id: str, user_qq: str) -> Tuple[list, str, str]:
        """加载个人数据（异步包装）"""
        return await asyncio.to_thread(
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

        # 如果从未发送过消息，以当前时间为基准开始计时：
        # 本次触发仅建立基准（未达到延迟，跳过），后续触发按"从现在起"的间隔判断
        if last_bot_message_time == 0:
            last_bot_message_time = time.time()
            self._last_bot_message_time[group_id] = last_bot_message_time
            _log.info("主动回复：未找到历史回复时间，从现在开始计时")

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