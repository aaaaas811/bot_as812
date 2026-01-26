"""消息处理器"""
import jieba
import random
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
        
        chat_history = []
        
        # 添加用户信息
        user_info = (
            f"用户信息: 昵称={current_message.user.nickname}, "
            f"QQ={current_message.user.qq}, "
            f"群名片={current_message.user.card}, "
            f"角色={self.map_role(current_message.user.role)}, "
            f"头衔={current_message.user.title}"
        )
        
        if personality_summary:
            user_info += f"\n该用户的个性总结：{personality_summary}"
        
        
        # 添加群聊历史
        group_messages = self.log_manager.load_group_history(group_id, chat_config.context_history)
        group_history = []
        
        bot_qq = self.config_manager.get_bt_uin()
        for msg in reversed(group_messages):
            if len(group_history) >= chat_config.context_history:
                break
            
            msg_qq = msg.get("qq")
            msg_nickname = msg.get("nickname", "")
            msg_content = msg.get("message", "")
            
            if msg_qq == bot_qq:
                group_history.append({"role": "assistant", "content": msg_content})
            else:
                group_history.append({"role": "user", "content": f"{msg_nickname}({msg_qq}): {msg_content}"})
        
        # 反转回时间顺序
        group_history.reverse()
        chat_history.extend(group_history)
        
        # 添加说明
        if group_history:
            chat_history.append({"role": "system", "content": "以上是过往群聊记录（不一定是该用户所说）"})
        # 添加用户信息
        chat_history.append({"role": "system", "content": user_info})
        # 添加当前消息
        chat_history.append({"role": "user", "content": current_message.message})
        
        return chat_history, chat_config.summary_threshold
    
    def get_user_info_string(self, chat_message: ChatMessage) -> str:
        """获取用户信息字符串"""
        return (
            f"QQ昵称: {chat_message.user.nickname}, "
            f"QQ号: {chat_message.user.qq}, "
            f"群昵称: {chat_message.user.card}, "
            f"群权限: {self.map_role(chat_message.user.role)}, "
            f"群头衔: {chat_message.user.title}"
        )