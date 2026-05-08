"""RAG 管理器 — 统一的 RAG 入口，基于 ChromaDB"""
import os
import time
from typing import Optional

from ncatbot.utils.logger import get_log

from .config import RAGConfig
from .embedding import RAGEmbeddingFunction
from .document import DocumentChunker
from .vector_store import VectorStore
from .retriever import Retriever
from .knowledge_base import KnowledgeBase

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

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @enabled.setter
    def enabled(self, value: bool):
        self.config.enabled = value

    def retrieve(self, query: str, top_k: Optional[int] = None) -> tuple[str, list[dict]]:
        """检索并返回格式化上下文和原始结果（同步）"""
        if not self.config.enabled:
            if self.config.debug:
                _log.info("[RAG] 检索跳过: RAG 未启用")
            return "", []

        if self.config.debug:
            total = self.vector_store.count()
            _log.info(f"[RAG] 开始检索: query='{query[:60]}...', top_k={top_k or self.config.top_k}, 知识库总量={total} chunks")

        results = self.retriever.retrieve(query, top_k)
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
        return self.knowledge_base.remove_document(source_id)

    def list_knowledge(self) -> list[dict]:
        return self.knowledge_base.list_documents()

    def get_stats(self) -> dict:
        return self.knowledge_base.stats()

    def clear(self):
        self.knowledge_base.clear()
