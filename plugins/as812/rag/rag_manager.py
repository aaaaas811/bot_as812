"""RAG 管理器 — 统一的 RAG 入口，基于 ChromaDB"""
import os
from typing import Optional

from ncatbot.utils.logger import get_log

from .config import RAGConfig
from .embedding import RAGEmbeddingFunction
from .document import DocumentChunker
from .vector_store import VectorStore
from .retriever import Retriever
from .knowledge_base import KnowledgeBase
from .memory import ChatMemory, LocalMemoryEmbedding

_log = get_log()


class RAGManager:
    """RAG 系统总管理器"""

    def __init__(self, config: Optional[RAGConfig] = None, base_dir: Optional[str] = None):
        self.config = config or RAGConfig()
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self._base_dir = base_dir

        data_dir = os.path.join(self._base_dir, self.config.data_dir)

        # ChromaDB 嵌入函数
        self.embedding_function = RAGEmbeddingFunction(
            mode=self.config.embedding_mode,
            model=self.config.embedding_model,
            dim=self.config.embedding_dim,
            debug=self.config.debug,
        )

        # ChromaDB 向量存储
        self.vector_store = VectorStore(
            data_dir=data_dir,
            collection="default",
            embedding_function=self.embedding_function,
        )

        self.chunker = DocumentChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            strategy=self.config.chunk_strategy,
        )

        self.retriever = Retriever(
            vector_store=self.vector_store,
            top_k=self.config.top_k,
            similarity_threshold=self.config.similarity_threshold,
            debug=self.config.debug,
        )

        self.knowledge_base = KnowledgeBase(
            vector_store=self.vector_store,
            chunker=self.chunker,
            data_dir=data_dir,
        )
        # 与已有手动知识分开索引，保留原有模型和已有向量。
        self.memory_store = VectorStore(data_dir=data_dir, collection="chat_memory",
                                        embedding_function=LocalMemoryEmbedding())
        self.memory = ChatMemory(self.memory_store, self.config)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @enabled.setter
    def enabled(self, value: bool):
        self.config.enabled = value

    def retrieve(self, query: str, top_k: Optional[int] = None,
                 scope: str = "", user_qq: str = "",
                 known_messages: Optional[list[dict]] = None) -> tuple[str, list[dict]]:
        """检索并返回格式化上下文和原始结果（同步）"""
        if not self.config.enabled:
            if self.config.debug:
                _log.info("[RAG] 检索跳过: RAG 未启用")
            return "", []

        if self.config.debug:
            total = self.vector_store.count()
            _log.info(f"[RAG] 开始检索: query='{query[:60]}...', top_k={top_k or self.config.top_k}, 知识库总量={total} chunks")

        if not query.strip():
            return "", []
        results = self.memory.retrieve(query, str(scope), str(user_qq))
        # 无会话的显式检索沿用原有接口；聊天中的手动知识检索仍按触发配置执行。
        if not scope or self.should_retrieve(query):
            results.extend(self.retriever.retrieve(query, top_k))
        results.sort(key=lambda r: r.get("score", 0), reverse=True)
        # 连标题与提示模板一起计入预算，整条记忆装不下时跳过。
        selected = []
        seen = set()
        for result in results:
            if result.get("kind") == "memory" and any(
                str(message.get("qq")) == result["user_qq"]
                and result.get("fact", result["text"]) in str(message.get("message", ""))
                for message in (known_messages or [])
            ):
                continue
            text = result.get("text", "").strip()
            if not text or text in seen:
                continue
            candidate = selected + [result]
            context = self.retriever.format_context(candidate, self.config.context_template)
            if len(context) > self.config.max_context_chars:
                continue
            selected = candidate
            seen.add(text)
            if len(selected) >= max(1, min(top_k or self.config.context_top_k, self.config.context_top_k)):
                break
        results = selected
        if not results:
            if self.config.debug:
                _log.info("[RAG] 未检索到相关内容")
            return "", []

        context = self.retriever.format_context(results, self.config.context_template)
        if self.config.debug:
            _log.info(f"[RAG] 上下文已注入 LLM（{len(results)} 个 chunks，共 {len(context)} 字符）")
        else:
            _log.info(f"RAG 检索到 {len(results)} 条相关内容")
        return context, results

    def context_for_chat(self, scope: str, history: list[dict],
                         current_messages: list[dict], bot_qq: str = "") -> str:
        """所有聊天入口共用：检查已加载的有限历史，保存后只检索相关内容。"""
        if not self.enabled or not current_messages:
            return ""
        try:
            self.memory.observe(str(scope), history + current_messages, bot_qq)
            query = "\n".join(str(m.get("message") or "") for m in current_messages)[-500:]
            user_qq = str(current_messages[-1].get("qq") or "")
            visible = [m for m in history if str(m.get("qq")) == user_qq] + current_messages
            context, _ = self.retrieve(query, scope=str(scope),
                                       user_qq=user_qq, known_messages=visible)
            return context
        except Exception:
            _log.exception("[RAG] 记忆处理失败，本次继续使用原有聊天上下文")
            return ""

    def should_retrieve(self, message: str) -> bool:
        if not self.config.enabled:
            return False

        if self.config.trigger_mode == "auto":
            if self.config.debug:
                _log.info(f"[RAG] 触发模式=auto，对消息触发检索: '{message[:40]}...'")
            return True
        elif self.config.trigger_mode == "keyword":
            for kw in self.config.trigger_keywords:
                if kw in message:
                    if self.config.debug:
                        _log.info(f"[RAG] 关键词触发: 命中 '{kw}' in '{message[:40]}...'")
                    return True
            if self.config.debug:
                _log.info(f"[RAG] 关键词未命中，跳过检索: '{message[:40]}...'")
            return False
        return False

    # -- 便捷的知识库操作 --

    def add_text(self, content: str, title: str = "", source_id: str = "") -> int:
        return self.knowledge_base.add_document(content, title=title, source_id=source_id)

    def import_file(self, filepath: str, title: str = "") -> int:
        return self.knowledge_base.import_text_file(filepath, title)

    def remove(self, source_id: str) -> int:
        with self.memory.lock:
            return self.memory_store.remove(source_id) + self.knowledge_base.remove_document(source_id)

    def list_knowledge(self) -> list[dict]:
        return self.knowledge_base.list_documents() + self.memory_store.list_sources()

    def get_stats(self) -> dict:
        sources = self.list_knowledge()
        return {"total_documents": len(sources),
                "total_chunks": self.vector_store.count() + self.memory_store.count(),
                "sources": sources}

    def clear(self):
        with self.memory.lock:
            self.knowledge_base.clear()
            self.memory_store.clear()
