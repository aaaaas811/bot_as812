"""RAG 管理器 — 统一的 RAG 入口，桥接 bot 消息流"""
import os
import re
from typing import Optional

from ncatbot.utils.logger import get_log

from .config import RAGConfig
from .embedding import EmbeddingService
from .document import DocumentChunker
from .vector_store import VectorStore
from .retriever import Retriever
from .knowledge_base import KnowledgeBase

_log = get_log()

try:
    import jieba
    _has_jieba = True
except Exception:
    _has_jieba = False


class RAGManager:
    """RAG 系统总管理器，提供检索和知识库管理的一站式接口"""

    def __init__(self, config: Optional[RAGConfig] = None, base_dir: Optional[str] = None):
        self.config = config or RAGConfig()
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self._base_dir = base_dir

        # 初始化各组件
        self.embedding_service = EmbeddingService(
            mode=self.config.embedding_mode,
            model=self.config.embedding_model,
            dim=self.config.embedding_dim,
        )

        data_dir = os.path.join(self._base_dir, self.config.data_dir)
        self.vector_store = VectorStore(
            data_dir=data_dir,
            collection="default",
            dim=self.config.embedding_dim,
        )

        self.chunker = DocumentChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            strategy=self.config.chunk_strategy,
        )

        self.retriever = Retriever(
            embedding_service=self.embedding_service,
            vector_store=self.vector_store,
            top_k=self.config.top_k,
            similarity_threshold=self.config.similarity_threshold,
        )

        self.knowledge_base = KnowledgeBase(
            embedding_service=self.embedding_service,
            vector_store=self.vector_store,
            chunker=self.chunker,
        )

        # 设置嵌入缓存
        cache_file = os.path.join(data_dir, "embedding_cache.json")
        self.embedding_service.set_cache_file(cache_file)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @enabled.setter
    def enabled(self, value: bool):
        self.config.enabled = value

    async def retrieve(self, query: str, top_k: Optional[int] = None) -> tuple[str, list[dict]]:
        """检索并返回格式化上下文和原始结果"""
        if not self.config.enabled:
            return "", []

        results = await self.retriever.retrieve(query, top_k)
        if not results:
            return "", []

        context = self.retriever.format_context(results, self.config.context_template)
        _log.info(f"RAG 检索到 {len(results)} 条相关内容")
        return context, results

    def should_retrieve(self, message: str) -> bool:
        """根据配置判断是否需要对当前消息进行检索"""
        if not self.config.enabled:
            return False

        if self.config.trigger_mode == "auto":
            return True
        elif self.config.trigger_mode == "keyword":
            for kw in self.config.trigger_keywords:
                if kw in message:
                    return True
            return False
        # "command" 模式：仅通过命令触发，此处始终返回 False
        return False

    # -- 便捷的知识库操作 --

    async def add_text(self, content: str, title: str = "", source_id: str = "") -> int:
        """向知识库添加文本"""
        return await self.knowledge_base.add_document(content, title=title, source_id=source_id)

    async def import_file(self, filepath: str, title: str = "") -> int:
        """从文件导入知识"""
        return await self.knowledge_base.import_text_file(filepath, title)

    def remove(self, source_id: str) -> int:
        """移除知识"""
        return self.knowledge_base.remove_document(source_id)

    def list_knowledge(self) -> list[dict]:
        """列出所有知识"""
        return self.knowledge_base.list_documents()

    def get_stats(self) -> dict:
        """获取统计信息"""
        return self.knowledge_base.stats()

    def clear(self):
        """清空知识库"""
        self.knowledge_base.clear()
