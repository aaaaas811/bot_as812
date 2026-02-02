"""消息处理器"""
import jieba
import random
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any, Tuple
from ncatbot.core.message import GroupMessage
from ncatbot.utils import config as bot_config
from ..models.message_models import ChatMessage, UserInfo, ChatHistoryConfig
from ..core.log_manager import LogManager
from ..core.config_manager import ConfigManager
from ncatbot.utils.logger import get_log

_log = get_log()


class MessageHandler:
    """消息处理器类"""
    
    def __init__(self, config_manager: ConfigManager, log_manager: LogManager):
        self.config_manager = config_manager
        self.log_manager = log_manager
    
    @staticmethod
    def map_role(role: str) -> str:
        """映射角色名称"""
        role_mapping = {
            "member": "群成员",
            "admin": "管理员",
            "owner": "群主"
        }
        return role_mapping.get(role, role)
    
    def parse_group_message(self, msg: GroupMessage) -> ChatMessage:
        """解析GroupMessage为ChatMessage对象"""
        user_qq = str(msg.sender.user_id)
        text_content = ""
        force_reply = False
        
        # 提取消息内容
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
                if qq_val is not None and str(qq_val) == str(bot_config.bt_uin):
                    text_content = f"@812({bot_config.bt_uin}) " + text_content
                    force_reply = True
        
        # 如果文本中包含'812'字样，也视为被提及
        if text_content:
            compact = text_content.replace(" ", "")
            if "812" in compact and not ("812睡觉" in compact or "812起床" in compact):
                force_reply = True
        
        # 创建用户信息
        card = getattr(msg.sender, "card", "") or ""
        role = getattr(msg.sender, "role", "") or ""
        title = getattr(msg.sender, "title", "") or ""
        
        user_info = UserInfo(
            nickname=msg.sender.nickname,
            qq=user_qq,
            card=card,
            role=role,
            title=title
        )
        
        # 创建聊天消息，安全获取时间戳（向后兼容不同事件字段）
        ts = None
        for attr in ("timestamp", "time", "recv_time", "receive_time", "created_at"):
            ts = getattr(msg, attr, None)
            if ts is not None:
                break
        if ts is None:
            try:
                import time as _time
                ts = _time.time()
            except Exception:
                ts = 0.0

        chat_message = ChatMessage(
            timestamp=float(ts),
            user=user_info,
            message=text_content.rstrip(','),
            force_reply=force_reply
        )
        
        return chat_message
    
    def build_chat_history(self, 
                          group_id: str, 
                          current_message: ChatMessage,
                          personality_summary: str = "") -> Tuple[List[Dict[str, str]], int]:
        """构建聊天历史"""
        # 获取配置
        config_data = {
            "context_history": self.config_manager.get("context_history", 50),
            "summary_threshold": self.config_manager.get("summary_threshold", 50)
        }
        
        chat_config = ChatHistoryConfig.from_config(config_data)
        
        # 按照规则生成合并后的历史：
        # 1) 先添加系统角色，明确规则只回答最新一条消息、忽略其他用户间对话、不加用户名前缀
        # 2) 如果有历史，合并为一条用户消息（只保留机器人和当前用户相关的历史）
        # 3) 添加当前消息，明确标记为“请回答这条消息”

        messages: List[Dict[str, str]] = []

        current_user_name = current_message.user.nickname or current_message.user.qq
        current_user_qq = str(current_message.user.qq)

        rules = (
            f"你是群聊机器人。当前与你对话的用户是：{current_user_name}\n\n"
            "规则：\n"
            "1. 只回答最新的一条用户消息\n"
            "2. 忽略历史消息中其他用户之间的对话\n"
            "3. 回复时不要加用户名前缀"
        )

        messages.append({"role": "system", "content": rules})

        # 加载群历史并合并为一条（只保留机器人和当前用户的消息）
        group_messages = self.log_manager.load_group_history(group_id, chat_config.context_history)
        bot_qq = str(self.config_manager.get_bt_uin())

        history_lines: List[str] = []
        # 遍历历史（从近到远），但我们最后希望按时间顺序展示，因此先收集再反转
        for msg in reversed(group_messages):
            msg_qq = str(msg.get("qq", ""))
            if not msg_qq:
                continue
            # 只保留与机器人或当前用户相关的消息
            if msg_qq != bot_qq and msg_qq != current_user_qq:
                continue

            msg_content = msg.get("message", "")
            if msg_qq == bot_qq:
                history_lines.append(f"as812: {msg_content}")
            else:
                nickname = msg.get("nickname", current_user_name)
                history_lines.append(f"{nickname}: {msg_content}")

        # history_lines 已是时间顺序（旧->新），因为我们从 reversed(group_messages) 收集后未再反转
        if history_lines:
            merged = "\n".join(history_lines)
            messages.append({"role": "user", "content": "以下是最新几条对话历史：\n" + merged})

        # 添加当前时间显示
        try:
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            messages.append({"role": "user", "content": f"当前时间：{now_time}"})
        except Exception:
            pass

        # 添加用户个性总结（若有）
        try:
            if personality_summary:
                ps = personality_summary.strip()
                if ps:
                    messages.append({"role": "user", "content": f"用户个性总结：\n{ps}"})
        except Exception:
            pass

        # 添加当前消息，明确标记要回复的那条消息
        current_msg_text = current_message.message or ""
        messages.append({"role": "user", "content": f"【请回答这条消息】{current_user_name}: {current_msg_text}"})

        return messages, chat_config.summary_threshold
    
    def get_user_info_string(self, chat_message: ChatMessage) -> str:
        """获取用户信息字符串"""
        return (
            f"QQ昵称: {chat_message.user.nickname}, "
            f"QQ号: {chat_message.user.qq}, "
            f"群昵称: {chat_message.user.card}, "
            f"群权限: {self.map_role(chat_message.user.role)}, "
            f"群头衔: {chat_message.user.title}"
        )