"""消息数据模型"""
from dataclasses import dataclass
from typing import Dict, Any, Optional
import time


@dataclass
class UserInfo:
    """用户信息模型"""
    nickname: str
    qq: str
    card: str = ""
    role: str = ""
    title: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "nickname": self.nickname,
            "qq": self.qq,
            "card": self.card,
            "role": self.role,
            "title": self.title
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserInfo':
        return cls(
            nickname=data.get("nickname", ""),
            qq=data.get("qq", ""),
            card=data.get("card", ""),
            role=data.get("role", ""),
            title=data.get("title", "")
        )


@dataclass
class ChatMessage:
    """聊天消息模型"""
    timestamp: float
    user: UserInfo
    message: str
    # 新增：结构化的消息段列表，保存原始消息中的图片/表情等段
    message_array: Optional[list] = None
    force_reply: bool = False
    message_id: Optional[str] = None
    reply_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "nickname": self.user.nickname,
            "qq": self.user.qq,
            "card": self.user.card,
            "role": self.user.role,
            "title": self.user.title,
            "message": self.message,
            "message_array": self.message_array,
            "force_reply": self.force_reply,
            "message_id": self.message_id,
            "reply_id": self.reply_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        return cls(
            timestamp=data.get("timestamp", time.time()),
            user=UserInfo(
                nickname=data.get("nickname", ""),
                qq=data.get("qq", ""),
                card=data.get("card", ""),
                role=data.get("role", ""),
                title=data.get("title", "")
            ),
            message=data.get("message", ""),
            message_array=data.get("message_array"),
            force_reply=data.get("force_reply", False),
            message_id=data.get("message_id"),
            reply_id=data.get("reply_id")
        )


@dataclass
class BotResponse:
    """机器人回复模型"""
    timestamp: float
    message: str
    qq: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "nickname": "812",
            "qq": self.qq,
            "card": "",
            "role": "",
            "title": "",
            "message": self.message
        }


@dataclass
class ChatHistoryConfig:
    """聊天历史配置模型"""
    context_history: int = 50
    max_history: int | None = None

    @classmethod
    def from_config(cls, config_data: Dict[str, Any]) -> 'ChatHistoryConfig':
        return cls(
            context_history=int(config_data.get("context_history", 50)),
            max_history=config_data.get("max_history")
        )