"""命令处理器"""
import re
import time
from datetime import datetime
from typing import Dict, Any, Optional
from ncatbot.utils.logger import get_log
from ..core.config_manager import ConfigManager, PromptManager
from ..core.log_manager import LogManager

_log = get_log()

# Unicode emoji 字符（手机键盘表情，如 🍬😂），用于 /贴表情 直接透传
EMOJI_CHAR_RE = re.compile(
    r"^[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣\U0001F1E6-\U0001F1FF]+$"
)

# QQ 原生表情 ID 映射（OneBot 通用表，0-79）
EMOJI_LIKE_MAP: Dict[str, int] = {
    "惊讶": 0, "撇嘴": 1, "色": 2, "发呆": 3, "得意": 4, "流泪": 5, "害羞": 6,
    "闭嘴": 7, "睡": 8, "大哭": 9, "尴尬": 10, "发怒": 11, "调皮": 12, "呲牙": 13,
    "微笑": 14, "酷": 15, "抓狂": 16, "吐": 17, "偷笑": 18, "愉快": 19, "白眼": 20,
    "傲慢": 21, "饥饿": 22, "困": 23, "惊恐": 24, "流汗": 25, "憨笑": 26, "悠闲": 27,
    "奋斗": 28, "咒骂": 29, "疑问": 30, "嘘": 31, "晕": 32, "疯了": 33, "衰": 34,
    "骷髅": 35, "敲打": 36, "再见": 37, "擦汗": 38, "抠鼻": 39, "鼓掌": 40, "糗大了": 41,
    "坏笑": 42, "左哼哼": 43, "右哼哼": 44, "哈欠": 45, "鄙视": 46, "委屈": 47,
    "快哭了": 48, "阴险": 49, "亲亲": 50, "吓": 51, "可怜": 52, "菜刀": 53, "西瓜": 54,
    "啤酒": 55, "篮球": 56, "乒乓": 57, "咖啡": 58, "饭": 59, "猪头": 60, "玫瑰": 61,
    "凋谢": 62, "嘴唇": 63, "爱心": 64, "心碎": 65, "蛋糕": 66, "闪电": 67, "炸弹": 68,
    "刀": 69, "足球": 70, "便便": 71, "兔": 72, "药丸": 73, "祈祷": 74, "彩带": 75,
    "庆祝": 76, "礼物": 77, "加油": 78, "赞": 79,
}
EMOJI_LIKE_HINT = "、".join(sorted(EMOJI_LIKE_MAP, key=lambda n: EMOJI_LIKE_MAP[n])[:40])
# 口语化别名 → 最接近的 QQ 表情 ID
EMOJI_LIKE_ALIASES: Dict[str, int] = {
    "大笑": 13, "哈哈": 13, "笑哭": 53, "哭": 9, "点赞": 79, "无语": 21, "裂开": 53,
}


class CommandHandler:
    """命令处理器类"""

    def __init__(self, config_manager: ConfigManager, prompt_manager: PromptManager, log_manager: LogManager, rag_manager=None):
        self.config_manager = config_manager
        self.prompt_manager = prompt_manager
        self.log_manager = log_manager
        self.rag_manager = rag_manager
    
    async def handle_private_command(self, api, user_id: int, message: str) -> None:
        """处理私聊命令"""
        if message == "view_config":
            await self._handle_view_config(api, user_id)
        elif message.startswith("set_prompt"):
            await self._handle_set_prompt(api, user_id, message)
        elif message.startswith("set_"):
            await self._handle_set_config(api, user_id, message)
        elif message == "prompt":
            await self._handle_show_prompt(api, user_id)
        # RAG 命令
        elif message == "rag_stats":
            await self._handle_rag_stats(api, user_id)
        elif message == "rag_list":
            await self._handle_rag_list(api, user_id)
        elif message.startswith("rag_add "):
            await self._handle_rag_add(api, user_id, message)
        elif message.startswith("rag_import "):
            await self._handle_rag_import(api, user_id, message)
        elif message.startswith("rag_remove "):
            await self._handle_rag_remove(api, user_id, message)
        elif message == "rag_clear":
            await self._handle_rag_clear(api, user_id)
        elif message == "rag_enable":
            await self._handle_rag_enable(api, user_id, True)
        elif message == "rag_disable":
            await self._handle_rag_enable(api, user_id, False)
    
    async def _handle_view_config(self, api, user_id: int) -> None:
        """查看配置"""
        config = self.config_manager.config
        config_lines = []
        for key, value in config.items():
            if key not in ["api_key", "cat_prompt"]:
                config_lines.append(f"{key}: {value}")
        config_text = "\n".join(config_lines)
        await api.post_private_msg(user_id, text=f"当前配置（除api_key和cat_prompt外）：\n{config_text}")
    
    async def _handle_set_prompt(self, api, user_id: int, message: str) -> None:
        """设置提示词"""
        value = message[10:].strip()
        if self.prompt_manager.save_prompt(value):
            await api.post_private_msg(user_id, text="设置成功")
        else:
            await api.post_private_msg(user_id, text="设置失败")
    
    async def _handle_set_config(self, api, user_id: int, message: str) -> None:
        """设置配置项"""
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await api.post_private_msg(user_id, text="格式错误，请使用 set_<key> <value>")
            return
        
        key = parts[0][4:]  # 去掉"set_"
        value = parts[1]
        
        if key in self.config_manager.config and key != "api_key":
            # 尝试转换类型
            if key in ["active_group_id", "super_user"]:
                normalized_value = str(value)
            else:
                normalized_value = value
            
            if self.config_manager.set(key, normalized_value):
                await api.post_private_msg(user_id, text=f"{key} 设置为 {value} 成功")
            else:
                await api.post_private_msg(user_id, text=f"{key} 设置失败")
        else:
            await api.post_private_msg(user_id, text=f"未知配置项: {key}")
    
    async def _handle_show_prompt(self, api, user_id: int) -> None:
        """显示提示词"""
        cat_prompt = self.prompt_manager.load_prompt()
        await api.post_private_msg(user_id, text=cat_prompt)
    
    async def handle_group_rag_command(self, api, group_id: str, user_id: str, text: str, sender_role: str = "") -> None:
        """处理群内 RAG 命令"""
        if not self.rag_manager:
            await api.post_group_msg(group_id, text="[RAG] 知识库未初始化", reply=True)
            return

        text = text.strip()

        # /记忆 <内容> 或 812记忆 <内容> 或 812记一下 <内容> 或 812学习 <内容>
        if text.startswith("/记忆 ") or text.startswith("812记忆 ") or text.startswith("812记一下 ") or text.startswith("812学习 "):
            for prefix in ["/记忆 ", "812记忆 ", "812记一下 ", "812学习 "]:
                if text.startswith(prefix):
                    content = text[len(prefix):].strip()
                    break
            else:
                content = ""

            if not content:
                await api.post_group_msg(group_id, text="格式: /记忆 <内容> 或 812记忆 <内容>", reply=True)
                return

            title = f"群聊添加_{user_id}_{int(time.time())}"
            count = self.rag_manager.add_text(content, title=title)
            await api.post_group_msg(
                group_id,
                text=f"已记住 ({count} chunks): {content[:100]}{'...' if len(content) > 100 else ''}",
                reply=True,
            )
            return

        # /rag_stats
        if text == "/rag_stats":
            stats = self.rag_manager.get_stats()
            lines = [
                f"RAG 知识库: {stats['total_documents']} 个文档, {stats['total_chunks']} 个 chunks",
                f"状态: {'启用' if self.rag_manager.enabled else '禁用'}",
            ]
            await api.post_group_msg(group_id, text="\n".join(lines), reply=True)
            return

        # /rag_list
        if text == "/rag_list":
            docs = self.rag_manager.list_knowledge()
            if not docs:
                await api.post_group_msg(group_id, text="知识库为空", reply=True)
                return
            lines = [f"知识库（{len(docs)} 个文档）："]
            for doc in docs[:10]:
                lines.append(f"  [{doc['chunk_count']}c] {doc['title']}")
            if len(docs) > 10:
                lines.append(f"  ...还有 {len(docs) - 10} 个")
            await api.post_group_msg(group_id, text="\n".join(lines), reply=True)
            return

        # /rag_remove <source_id>（仅群主/管理员可用）
        if text.startswith("/rag_remove "):
            if sender_role not in ("owner", "admin"):
                await api.post_group_msg(group_id, text="仅群主/管理员可删除知识", reply=True)
                return
            source_id = text[len("/rag_remove "):].strip()
            count = self.rag_manager.remove(source_id)
            await api.post_group_msg(group_id, text=f"已删除 {count} 个 chunks", reply=True)
            return

        # /rag_enable / /rag_disable（仅群主/管理员可用）
        if text in ("/rag_enable", "/rag_disable"):
            if sender_role not in ("owner", "admin"):
                await api.post_group_msg(group_id, text="仅群主/管理员可切换 RAG 状态", reply=True)
                return
            enable = text == "/rag_enable"
            self.rag_manager.enabled = enable
            self.config_manager.set("rag_enabled", enable)
            await api.post_group_msg(group_id, text=f"RAG 已{'启用' if enable else '禁用'}", reply=True)
            return

        # /rag_help
        if text == "/rag_help":
            help_text = (
                "RAG 知识库群指令：\n"
                "/记忆 <内容> — 添加知识\n"
                "812记忆 <内容> — 同上\n"
                "/rag_stats — 查看统计\n"
                "/rag_list — 查看列表\n"
                "/rag_remove <id> — 删除(管理)\n"
                "/rag_enable|disable — 开关(管理)"
            )
            await api.post_group_msg(group_id, text=help_text, reply=True)
            return

    # -- 群交互命令 --

    @staticmethod
    def _resolve_emoji_id(emoji_name: str) -> Optional[int]:
        """将表情名称或数字 ID 解析为 QQ 表情 ID（支持口语化别名）。"""
        name = (emoji_name or "").strip()
        if not name:
            return None
        if name.isdigit():
            return int(name)
        if name in EMOJI_LIKE_ALIASES:
            return EMOJI_LIKE_ALIASES[name]
        return EMOJI_LIKE_MAP.get(name)

    @staticmethod
    def _extract_face_id(message_array) -> Optional[int]:
        """从消息段中提取用户直接发送的 QQ 表情 ID（face/emoji 段）。"""
        for seg in message_array or []:
            try:
                if str(seg.get("type", "")).lower() not in ("face", "emoji"):
                    continue
                fid = seg.get("id") or seg.get("face_id")
                if fid is not None:
                    return int(fid)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _extract_emoji_char(message_array) -> Optional[str]:
        """从文本段中提取 /贴表情 之后的 Unicode emoji 字符（如 🍬）。"""
        try:
            texts = [
                str(seg.get("text", "") or "")
                for seg in (message_array or [])
                if str(seg.get("type", "")).lower() == "text"
            ]
            combined = "".join(texts)
            if "/贴表情" not in combined:
                return None
            rest = combined.replace("/贴表情", "").strip()
            if rest and EMOJI_CHAR_RE.match(rest):
                return rest
        except Exception:
            pass
        return None

    @staticmethod
    def _emoji_to_dec_value(emoji_char: str) -> str:
        """Unicode emoji → QQ NT 协议要求的十进制码点字符串（emojiType=2 的 emojiId 形态）。

        NapCat 按 emojiId 长度判定类型：>3 位视为 unicode dec 值。
        例：🍬 (U+1F36C) → "127852"；😂 → "128514"。
        """
        try:
            for ch in emoji_char:
                cp = ord(ch)
                # 跳过变体选择符/零宽连接符/键帽等附加码点，取主 emoji 码点
                if cp in (0xFE0F, 0x200D, 0x20E3):
                    continue
                return str(cp)
        except Exception:
            pass
        return str(ord(emoji_char[0]))

    async def _set_emoji_like(self, api, message_id, emoji_id: int) -> None:
        """对指定消息贴表情（兼容不同 SDK 调用路径）。"""
        qq_api = api
        if hasattr(qq_api, "set_msg_emoji_like"):
            await qq_api.set_msg_emoji_like(message_id, str(emoji_id))
            return
        messaging = getattr(qq_api, "messaging", None)
        if messaging is not None and hasattr(messaging, "set_msg_emoji_like"):
            await messaging.set_msg_emoji_like(message_id, str(emoji_id))
            return
        raise AttributeError("当前 SDK 未提供 set_msg_emoji_like 接口")

    async def handle_group_emoji_like(self, api, group_id: str, user_id: str, text: str,
                                      reply_id: Optional[str] = None, message_array=None) -> None:
        """处理 /贴表情 [QQ表情] [消息ID]：把命令中的表情贴到目标消息。

        - 表情优先取用户直接发送的 QQ 表情（face 段），如 /贴表情 [大笑]
        - 也支持数字 ID 或表情名称（/贴表情 32、/贴表情 大笑）作为兜底
        - 目标消息：命令后跟的消息 ID > 引用（回复）的消息
        """
        # 表情来源：face 段（QQ 原生表情）> Unicode emoji 字符（如 🍬）> 数字 ID > 名称映射
        emoji_id = self._extract_face_id(message_array)
        emoji_char = None if emoji_id is not None else self._extract_emoji_char(message_array)
        target_id = None
        parts = text[len("/贴表情"):].strip().split() if text.startswith("/贴表情") else []

        if emoji_id is None and emoji_char is None and parts:
            if parts[0].isdigit():
                emoji_id = int(parts[0])
            else:
                emoji_id = self._resolve_emoji_id(parts[0])
            target_id = parts[1] if len(parts) > 1 else None

        if emoji_id is None and emoji_char is None:
            await api.post_group_msg(
                group_id,
                text="请带上一个表情：/贴表情 [QQ表情] 或 /贴表情 [emoji]（也可以 /贴表情 32 或 /贴表情 大笑）",
                reply=True,
            )
            return

        # 目标消息：显式 ID > 引用消息 > 报错
        if target_id is None:
            target_id = reply_id
        if not target_id:
            await api.post_group_msg(group_id, text="需要指定目标消息：引用一条消息后发送，或 /贴表情 <表情> <消息ID>", reply=True)
            return

        # 贴表情：Unicode emoji 需转成十进制码点（NapCat 按长度判定 emojiType，字符会被误判），
        # QQ 原生表情/数字 ID 直接传字符串
        like_value = self._emoji_to_dec_value(emoji_char) if emoji_char is not None else str(emoji_id)
        try:
            await self._set_emoji_like(api, str(target_id), like_value)
        except Exception as e:
            _log.error(f"贴表情失败: {e}")

    async def handle_group_revoked_history(self, api, group_id: str, limit: int = 5) -> None:
        """处理 /撤回记录：放出最近 limit 条被撤回的消息。"""
        records = self.log_manager.load_revoked_messages(group_id, limit=limit)
        if not records:
            await api.post_group_msg(group_id, text="暂时没有撤回记录喵", reply=True)
            return

        lines = [f"最近被撤回的 {len(records)} 条消息："]
        for r in records:
            ts = r.get("timestamp")
            time_str = ""
            if ts:
                try:
                    time_str = datetime.fromtimestamp(float(ts)).strftime("%H:%M")
                except Exception:
                    time_str = ""
            who = r.get("card") or r.get("nickname") or f"QQ号{r.get('qq', '?')}"
            content = str(r.get("message", "") or "")
            if len(content) > 50:
                content = content[:50] + "…"
            lines.append(f"[{time_str}] {who}: {content}")
        await api.post_group_msg(group_id, text="\n".join(lines), reply=True)

    # -- RAG 命令处理 --

    async def _handle_rag_stats(self, api, user_id: int) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        stats = self.rag_manager.get_stats()
        lines = [
            f"RAG 知识库统计：",
            f"文档数: {stats['total_documents']}",
            f"Chunk 数: {stats['total_chunks']}",
            f"状态: {'启用' if self.rag_manager.enabled else '禁用'}",
        ]
        await api.post_private_msg(user_id, text="\n".join(lines))

    async def _handle_rag_list(self, api, user_id: int) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        docs = self.rag_manager.list_knowledge()
        if not docs:
            await api.post_private_msg(user_id, text="知识库为空")
            return
        lines = [f"知识库文档列表（共 {len(docs)} 个）："]
        for doc in docs:
            lines.append(f"  - [{doc['chunk_count']} chunks] {doc['title']} (id: {doc['source_id']})")
        await api.post_private_msg(user_id, text="\n".join(lines))

    async def _handle_rag_add(self, api, user_id: int, message: str) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await api.post_private_msg(user_id, text="格式: rag_add <标题> <内容>")
            return
        # 解析标题和内容
        content = parts[1].strip()
        # 尝试按空格拆分标题和内容
        space_idx = content.find(" ")
        if space_idx > 0:
            title = content[:space_idx].strip()
            body = content[space_idx + 1:].strip()
        else:
            title = f"手动添加_{int(time.time())}"
            body = content

        count = await self.rag_manager.add_text(body, title=title)
        await api.post_private_msg(user_id, text=f"已添加文档 '{title}'，共 {count} 个 chunks")

    async def _handle_rag_import(self, api, user_id: int, message: str) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await api.post_private_msg(user_id, text="格式: rag_import <文件路径> [标题]")
            return
        args = parts[1].strip().split(" ", 1)
        filepath = args[0]
        title = args[1] if len(args) > 1 else ""
        count = await self.rag_manager.import_file(filepath, title)
        await api.post_private_msg(user_id, text=f"已从文件导入 {count} 个 chunks")

    async def _handle_rag_remove(self, api, user_id: int, message: str) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await api.post_private_msg(user_id, text="格式: rag_remove <source_id>")
            return
        source_id = parts[1].strip()
        count = self.rag_manager.remove(source_id)
        await api.post_private_msg(user_id, text=f"已删除 {count} 个 chunks（source_id: {source_id}）")

    async def _handle_rag_clear(self, api, user_id: int) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        self.rag_manager.clear()
        await api.post_private_msg(user_id, text="知识库已清空")

    async def _handle_rag_enable(self, api, user_id: int, enable: bool) -> None:
        if not self.rag_manager:
            await api.post_private_msg(user_id, text="RAG 管理器未初始化")
            return
        self.rag_manager.enabled = enable
        self.config_manager.set("rag_enabled", enable)
        status = "启用" if enable else "禁用"
        await api.post_private_msg(user_id, text=f"RAG 已{status}")