"""消息处理器"""
import os
import jieba
import html
import random
import yaml
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any
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
        """解析机器人 QQ 号，兼容不同配置来源。"""
        bot_uin = getattr(bot_config, "bot_uin", None) or getattr(bot_config, "bt_uin", None)
        if bot_uin:
            return str(bot_uin)

        # 插件配置中可能存在 bt_uin
        try:
            cfg_uin = self.config_manager.get_bt_uin()
            if cfg_uin:
                return str(cfg_uin)
        except Exception:
            pass

        # 根配置兜底：config.yaml
        try:
            if os.path.exists("config.yaml"):
                with open("config.yaml", "r", encoding="utf-8") as f:
                    root_cfg = yaml.safe_load(f) or {}
                root_uin = root_cfg.get("bot_uin") or root_cfg.get("bt_uin")
                if root_uin:
                    return str(root_uin)
        except Exception:
            pass

        return None
    
    def parse_group_message(self, msg: GroupMessage) -> ChatMessage:
        """解析GroupMessage为ChatMessage对象"""
        user_qq = str(msg.sender.user_id)
        text_content = ""
        message_array = []
        force_reply = False
        reply_id = None
        message_id = None

        # 兼容不同事件字段名，尝试获取消息 id
        for attr in ("message_id", "msg_id", "id", "message_seq", "messageId"):
            try:
                val = getattr(msg, attr, None)
                if val is not None:
                    message_id = str(val)
                    break
            except Exception:
                continue
        
        # 提取消息内容
        for message in msg.message:
            mtype = self._detect_segment_type(message)

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
                    try:
                        message_array.append({"type": "text", "text": txt})
                    except Exception:
                        pass

            if mtype == "at":
                at_target = None
                if hasattr(message, "user_id"):
                    at_target = getattr(message, "user_id")
                elif hasattr(message, "qq"):
                    at_target = getattr(message, "qq")
                else:
                    try:
                        data = message.get("data", {})
                        at_target = data.get("user_id") or data.get("qq")
                    except Exception:
                        at_target = None

                bot_uin = self._resolve_bot_uin()
                if at_target is not None and bot_uin is not None and str(at_target) == str(bot_uin):
                    text_content = f"@812({bot_uin}) " + text_content
                    force_reply = True

            # Reply 段：尝试将被引用的消息文本抽取并附加到当前文本中，便于保存与后续处理
            if mtype == "reply":
                try:
                    # 支持两种访问方式：对象属性或字典式
                    data = None
                    if hasattr(message, "id") or hasattr(message, "msg_seg_type"):
                        data = getattr(message, "data", None) or {}
                    else:
                        data = message.get("data", {})

                    # 尝试直接获取被引用消息的原文（不同平台字段名可能不同）
                    orig_text = None
                    for key in ("message", "raw_message", "text", "content"):
                        try:
                            if isinstance(data, dict) and key in data and data.get(key):
                                orig = data.get(key)
                                if isinstance(orig, list):
                                    parts = []
                                    for seg in orig:
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
                                else:
                                    orig_text = str(orig)
                                break
                        except Exception:
                            continue

                    if not orig_text:
                        try:
                            rid = None
                            try:
                                rid = getattr(message, "id", None)
                            except Exception:
                                rid = None

                            if not rid and isinstance(data, dict):
                                rid = data.get("id") or data.get("message_id") or data.get("msg_id")

                            if rid:
                                orig_text = f"[引用消息 id={rid}]"
                        except Exception:
                            orig_text = None

                    try:
                        rid = None
                        try:
                            rid = getattr(message, "id", None)
                        except Exception:
                            rid = None

                        if not rid and isinstance(data, dict):
                            rid = data.get("id") or data.get("message_id") or data.get("msg_id")

                        if rid:
                            reply_id = str(rid)
                    except Exception:
                        pass
                except Exception as e:
                    _log.debug(f"解析 reply 段失败: {e}")

            # 其它类型（图片/表情等），尽量保留原始段的关键信息到 message_array
            if mtype not in ("text", "at", "reply"):
                try:
                    seg = {"type": mtype}
                    # 尝试从对象属性或字典 data 中取关键字段
                    data = None
                    try:
                        data = getattr(message, "data", None) or {}
                    except Exception:
                        data = {}

                    if isinstance(message, dict):
                        data = message.get("data", {}) if message.get("data") is not None else data

                    # 常见字段
                    for key in ("file", "url", "sub_type", "id", "summary", "file_size"):
                        try:
                            val = None
                            if hasattr(message, key):
                                val = getattr(message, key)
                            else:
                                val = data.get(key) if isinstance(data, dict) else None
                            if val is not None:
                                seg[key] = val
                        except Exception:
                            continue

                    # fallback: 如果段对象本身有直出属性（如 .text / .emoji / .id）
                    try:
                        if hasattr(message, "text"):
                            t = getattr(message, "text")
                            if t:
                                seg.setdefault("text", t)
                    except Exception:
                        pass

                    message_array.append(seg)
                except Exception:
                    pass
        
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
            message_array=message_array if message_array else None,
            force_reply=force_reply,
            message_id=message_id,
            reply_id=reply_id
        )
        
        return chat_message
    
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
        try:
            if getattr(current_message, "message_array", None):
                arr = getattr(current_message, "message_array") or []
                img_lines = []
                for i, seg in enumerate(arr):
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
                    # 如果 message 中包含 CQ:image 标签，解析出其中的 url/file 字段
                    cq_imgs = []
                    try:
                        import re
                        pattern = re.compile(r"\[CQ:image,([^\]]+)\]")
                        for m in pattern.finditer(current_msg_text):
                            params = m.group(1)
                            # 将参数按逗号切分，再解析 key=value
                            parts = [p for p in params.split(',') if '=' in p]
                            info = {}
                            for p in parts:
                                k, v = p.split('=', 1)
                                info[k.strip()] = html.unescape(v.strip())
                            # 优先取 url，其次 file
                            url = info.get('url') or info.get('file') or ''
                            cq_imgs.append(url)
                    except Exception:
                        cq_imgs = []

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
                    messages.append({"role": "system", "content": "当前消息包含图片/表情片段，索引如下：\n" + "\n".join(img_lines)})
        except Exception:
            pass

        messages.append({"role": "user", "content": f"【请回答这条消息】{current_user_name}: {current_msg_text}"})

        return messages
    
    def get_user_info_string(self, chat_message: ChatMessage) -> str:
        """获取用户信息字符串"""
        return (
            f"QQ昵称: {chat_message.user.nickname}, "
            f"QQ号: {chat_message.user.qq}, "
            f"群昵称: {chat_message.user.card}, "
            f"群权限: {self.map_role(chat_message.user.role)}, "
            f"群头衔: {chat_message.user.title}"
        )