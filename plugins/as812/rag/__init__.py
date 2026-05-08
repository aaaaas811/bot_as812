"""as812 RAG 模块 — 基于 ChromaDB 的检索增强生成"""
from .rag_manager import RAGManager
from .knowledge_base import KnowledgeBase
from .config import RAGConfig

__all__ = ["RAGManager", "KnowledgeBase", "RAGConfig"]
