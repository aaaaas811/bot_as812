"""as812 RAG 模块 — 检索增强生成

提供文档分块、向量嵌入、存储检索、知识库管理等功能。
"""

from .rag_manager import RAGManager
from .knowledge_base import KnowledgeBase
from .config import RAGConfig

__all__ = ["RAGManager", "KnowledgeBase", "RAGConfig"]
