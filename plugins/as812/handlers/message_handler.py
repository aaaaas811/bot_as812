"""消息处理器：解析事件、构建聊天上下文"""
import re
import html
import time
from datetime import datetime
from typing import List, Dict, Any
from ncatbot.event.qq import GroupMessageEvent as GroupMessage, PrivateMessageEvent
from ..models.message_models import ChatMessage, UserInfo, ChatHistoryConfig
from ..core.log_manager import LogManager
from ..core.config_manager import ConfigManager


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

    @staticmethod
    def _get_first_attr(obj, attrs, default=None):
        """按顺序取第一个存在的属性值（兼容不同 SDK 字段名）。"""
        for attr in attrs:
            try:
                val = getattr(obj, attr, None)
                if val is not None:
                    return val
            except Exception:
                continue
        return default

    @staticmethod
    def _detect_segment_type(message) -> str | None:
        """检测消息段类型，兼容旧 dict 段与 v5 pydantic 段。"""
        # 1) 旧式 dict 段
        try:
            if isinstance(message, dict):
                mtype = message.get("type")
                if mtype:
                    return str(mtype)
        except Exception:
            pass

        # 2) 旧式对象段
        mtype = getattr(message, "msg_seg_type", None)
        if mtype:
            return str(mtype)

        # 3) v5 pydantic 段（无 type 字段）
        cls_name = message.__class__.__name__.lower()
        class_map = {
            "plaintext": "text",
            "text": "text",
            "at": "at",
            "reply": "reply",
            "image": "image",
            "record": "record",
            "video": "video",
            "file": "file",
            "face": "face",
            "emoji": "face",
            "forward": "forward",
        }
        if cls_name in class_map:
            return class_map[cls_name]

        # 4) 字段兜底推断
        if hasattr(message, "user_id"):
            return "at"
        if hasattr(message, "text"):
            return "text"
        if hasattr(message, "id"):
            return "reply"
        if hasattr(message, "file"):
            return "image"

        return None

    def _resolve_bot_uin(self) -> str | None:
        """解析机器人 QQ 号（统一由 ConfigManager 归口，兼容 bot_uin / bt_uin 与根配置兜底）。"""
        try:
            return self.config_manager.get_bt_uin()
        except Exception:
            return None

    @staticmethod
    def _extract_text(message) -> str:
        """从文本段提取文本内容（兼容 v5 对象与旧 dict 段）。"""
        try:
            if hasattr(message, "text"):
                return getattr(message, "text") or ""
            return (message.get("data", {}) or {}).get("text", "") or ""
        except Exception:
            return ""

    @staticmethod
    def _extract_at_target(message):
        """从 at 段提取被 @ 的 QQ。"""
        try:
            if hasattr(message, "user_id"):
                return getattr(message, "user_id")
            if hasattr(message, "qq"):
                return getattr(message, "qq")
            data = message.get("data", {}) or {}
            return data.get("user_id") or data.get("qq")
        except Exception:
            return None

    @staticmethod
    def _extract_reply_id(message) -> str | None:
        """从 reply 段提取被引用消息的 id（兼容对象与 dict 段）。"""
        try:
            rid = getattr(message, "id", None)
            if rid:
                return str(rid)
            data = getattr(message, "data", None) or {}
            if isinstance(message, dict) and message.get("data") is not None:
                data = message.get("data", {})
            if isinstance(data, dict):
                rid = data.get("id") or data.get("message_id") or data.get("msg_id")
                if rid:
                    return str(rid)
        except Exception:
            pass
        return None

    @staticmethod
    def _capture_other_segment(message, mtype) -> dict:
        """提取非 text/at/reply 段的关键字段，用于历史记录（兼容对象与 dict 段）。"""
        seg = {"type": mtype}
        try:
            data = getattr(message, "data", None) or {}
        except Exception:
            data = {}
        if isinstance(message, dict) and message.get("data") is not None:
            data = message.get("data", {})
        for key in ("file", "url", "sub_type", "id", "summary", "file_size"):
            try:
                val = getattr(message, key, None)
                if val is None and isinstance(data, dict):
                    val = data.get(key)
                if val is not None:
                    seg[key] = val
            except Exception:
                continue
        try:
            t = getattr(message, "text", None)
            if t:
                seg.setdefault("text", t)
        except Exception:
            pass
        return seg

    def _parse_message(self, msg, is_private: bool) -> ChatMessage:
        """解析消息事件的公共逻辑（群聊/私聊共用）。"""
        text_content = ""
        message_array = []
        reply_id = None
        force_reply = bool(is_private)
        bot_uin = self._resolve_bot_uin()

        # 兼容不同事件字段名，尝试获取消息 id
        raw_id = self._get_first_attr(msg, ("message_id", "msg_id", "id", "message_seq", "messageId"))
        message_id = str(raw_id) if raw_id is not None else None

        for message in getattr(msg, "message", None) or []:
            mtype = self._detect_segment_type(message)

            if mtype == "text":
                txt = self._extract_text(message)
                if txt:
                    text_content += txt + ","
                    message_array.append({"type": "text", "text": txt})

            elif mtype == "at" and not is_private:
                at_target = self._extract_at_target(message)
                if at_target is not None and bot_uin is not None and str(at_target) == str(bot_uin):
                    text_content = f"@812({bot_uin}) " + text_content
                    force_reply = True

            elif mtype == "reply" and not is_private:
                rid = self._extract_reply_id(message)
                if rid:
                    reply_id = rid

            elif mtype not in ("text", "at", "reply"):
                message_array.append(self._capture_other_segment(message, mtype))

        # 如果文本中包含'812'字样，也视为被提及（群聊）
        if text_content and not is_private:
            compact = text_content.replace(" ", "")
            if "812" in compact and not ("812睡觉" in compact or "812起床" in compact):
                force_reply = True

        # 用户信息
        if is_private:
            nickname = getattr(msg, "nickname", "") or ""
            if not nickname:
                sender = getattr(msg, "sender", None)
                if sender:
                    nickname = getattr(sender, "nickname", "") or ""
            user_info = UserInfo(
                nickname=nickname,
                qq=str(msg.user_id),
                card="",
                role="",
                title=""
            )
        else:
            user_info = UserInfo(
                nickname=msg.sender.nickname,
                qq=str(msg.sender.user_id),
                card=getattr(msg.sender, "card", "") or "",
                role=getattr(msg.sender, "role", "") or "",
                title=getattr(msg.sender, "title", "") or ""
            )

        ts = self._get_first_attr(msg, ("timestamp", "time", "recv_time", "receive_time", "created_at"))
        if ts is None:
            ts = time.time()

        return ChatMessage(
            timestamp=float(ts),
            user=user_info,
            message=text_content.rstrip(','),
            message_array=message_array if message_array else None,
            force_reply=force_reply,
            message_id=None if is_private else message_id,
            reply_id=None if is_private else reply_id
        )

    def parse_group_message(self, msg: GroupMessage) -> ChatMessage:
        """解析GroupMessage为ChatMessage对象"""
        return self._parse_message(msg, is_private=False)

    def parse_private_message(self, msg: PrivateMessageEvent) -> ChatMessage:
        """解析 PrivateMessageEvent 为 ChatMessage 对象"""
        return self._parse_message(msg, is_private=True)

    def build_chat_history(self,
                          group_id: str,
                          current_message: ChatMessage) -> List[Dict[str, str]]:
        """构建聊天历史"""
        config_data = {
            "context_history": self.config_manager.get("context_history", 50),
        }

        chat_config = ChatHistoryConfig.from_config(config_data)

        # 按照规则生成合并后的历史：
        # 1) 先添加系统角色，明确规则只回答最新一条消息、忽略其他用户间对话、不加用户名前缀
        # 2) 如果有历史，合并为一条用户消息（只保留机器人和当前用户相关的历史）
        # 3) 添加当前消息，明确标记为“请回答这条消息”

        messages: List[Dict[str, str]] = []

        current_user_name = current_message.user.nickname or current_message.user.qq
        current_user_qq = str(current_message.user.qq)

        # 加载群历史并合并为一条（只保留机器人和当前用户的消息）
        group_messages = self.log_manager.load_group_history(group_id, chat_config.context_history)
        bot_qq = str(self.config_manager.get_bt_uin() or "")

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
            messages.append({"role": "user", "content": "以下是最新几条对话历史：\n" +
                             "==================\n"+merged
                             + "\n==================\n"
                             })

        # 添加当前时间显示
        try:
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            messages.append({"role": "user", "content": f"当前时间：{now_time}"})
        except Exception:
            pass

        # 添加当前消息，明确标记要回复的那条消息
        current_msg_text = current_message.message or ""
        # 若当前消息包含结构化段（如图片/表情），将其列出供模型选择是否需要识图
        img_msg = self._build_image_index_message(
            current_msg_text, getattr(current_message, "message_array", None)
        )
        if img_msg:
            messages.append({"role": "system", "content": img_msg})

        messages.append({"role": "user", "content": f"【请回答这条消息】{current_user_name}: {current_msg_text}"})

        return messages

    @staticmethod
    def _build_image_index_message(current_msg_text: str, message_array) -> str | None:
        """将当前消息中的图片/表情片段整理为索引（含 CQ:image 解析），供模型选择识图。

        返回形如 "当前消息包含图片/表情片段，索引如下：\n图片[0]: <url>" 的 system 内容；无图片时返回 None。
        """
        try:
            img_lines = []
            for i, seg in enumerate(message_array or []):
                try:
                    t = (seg.get("type") or "").lower()
                    has_file = bool(seg.get("file") or seg.get("url") or seg.get("image_url") or seg.get("file_url"))
                    # 更宽松的判断：类型包含 image 或显式带有 file/url 字段均视为图片段
                    if "image" in t or t in ("face", "sticker") or has_file:
                        # 优先显示 url，其次 file 字段，再fallback为 summary 或空占位
                        url = seg.get("url") or seg.get("file") or seg.get("image_url") or seg.get("file_url") or seg.get("summary") or ""
                        img_lines.append(f"图片[{i}]: {url}")
                except Exception:
                    continue

            # 解析当前消息文本中可能存在的 CQ:image（例如引用中的展开文本）
            try:
                cq_imgs = []
                pattern = re.compile(r"\[CQ:image,([^\]]+)\]")
                for m in pattern.finditer(current_msg_text):
                    params = m.group(1)
                    # 将参数按逗号切分，再解析 key=value
                    info = {}
                    for p in [p for p in params.split(',') if '=' in p]:
                        try:
                            k, v = p.split('=', 1)
                            info[k.strip()] = html.unescape(v.strip())
                        except Exception:
                            continue
                    # 优先取 url，其次 file
                    cq_imgs.append(info.get('url') or info.get('file') or '')

                if cq_imgs:
                    start_idx = len(img_lines)
                    for j, u in enumerate(cq_imgs):
                        try:
                            img_lines.append(f"图片[{start_idx + j}]: {u}")
                        except Exception:
                            continue
            except Exception:
                pass

            if img_lines:
                return "当前消息包含图片/表情片段，索引如下：\n" + "\n".join(img_lines)
        except Exception:
            pass
        return None

    def get_user_info_string(self, chat_message: ChatMessage) -> str:
        """获取用户信息字符串"""
        return (
            f"QQ昵称: {chat_message.user.nickname}, "
            f"QQ号: {chat_message.user.qq}, "
            f"群昵称: {chat_message.user.card}, "
            f"群权限: {self.map_role(chat_message.user.role)}, "
            f"群头衔: {chat_message.user.title}"
        )
