"""检索器 — 查询预处理 + 混合检索 + 重排序"""
import re
from typing import Optional

from ncatbot.utils.logger import get_log

from .embedding import EmbeddingService
from .vector_store import VectorStore

_log = get_log()

try:
    import jieba
    _has_jieba = True
except Exception:
    _has_jieba = False


class Retriever:
    """检索器：负责查询预处理、向量检索、结果重排"""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        top_k: int = 5,
        similarity_threshold: float = 0.5,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

    async def retrieve(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        """检索相关文档块"""
        k = top_k or self.top_k
        if not query.strip():
            return []

        # 查询预处理
        processed_query = self._preprocess_query(query)

        # 向量检索
        query_vector = await self.embedding_service.embed_text(processed_query)
        results = self.vector_store.search(query_vector, top_k=k, threshold=self.similarity_threshold)

        # 重排序（按相关度 + 去重）
        results = self._rerank(query, results)

        return results[:k]

    def _preprocess_query(self, query: str) -> str:
        """查询预处理：去除噪声、提取关键信息"""
        # 去除 @提及
        query = re.sub(r'@\S+', '', query)
        # 去除纯表情符号
        query = re.sub(r'\[[^\]]{1,10}\]', '', query)
        # 去除多余空白
        query = re.sub(r'\s+', ' ', query).strip()
        return query

    def _rerank(self, query: str, results: list[dict]) -> list[dict]:
        """对检索结果重排序"""
        if not results:
            return results

        if _has_jieba:
            query_tokens = set(jieba.cut(query))
        else:
            query_tokens = set(query)

        for r in results:
            text = r.get("text", "")
            # BM25 风格的词匹配加分
            if _has_jieba:
                text_tokens = set(jieba.cut(text))
            else:
                text_tokens = set(text)

            overlap = len(query_tokens & text_tokens)
            keyword_bonus = min(0.2, overlap * 0.02)

            # 标题匹配加分
            title = r.get("title", "")
            if _has_jieba:
                title_tokens = set(jieba.cut(title))
            else:
                title_tokens = set(title)
            title_overlap = len(query_tokens & title_tokens)
            title_bonus = min(0.15, title_overlap * 0.03)

            r["score"] = r.get("score", 0) + keyword_bonus + title_bonus

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results

    def format_context(self, results: list[dict], template: Optional[str] = None) -> str:
        """将检索结果格式化为 LLM 上下文"""
        if not results:
            return ""

        if template:
            context_parts = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "未知")
                text = r.get("text", "")
                context_parts.append(f"[{i}] ({title}) {text}")
            return template.format(context="\n\n".join(context_parts))

        # 默认格式
        lines = ["【相关知识】"]
        for i, r in enumerate(results, 1):
            text = r.get("text", "")
            lines.append(f"{i}. {text}")
        return "\n".join(lines)
