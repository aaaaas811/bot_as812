"""命令处理器"""
import time
from typing import Dict, Any
from ncatbot.utils.logger import get_log
from ..core.config_manager import ConfigManager, PromptManager
from ..core.log_manager import LogManager

_log = get_log()


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