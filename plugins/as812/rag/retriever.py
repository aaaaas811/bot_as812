"""检索器 — 查询预处理 + ChromaDB 检索 + 重排序"""
import re
from typing import Optional

from ncatbot.utils.logger import get_log

from .vector_store import VectorStore

_log = get_log()

try:
    import jieba
    _has_jieba = True
except Exception:
    _has_jieba = False


class Retriever:
    """检索器：查询预处理、ChromaDB 检索、结果重排"""

    def __init__(
        self,
        vector_store: VectorStore,
        top_k: int = 5,
        similarity_threshold: float = 0.5,
        debug: bool = False,
    ):
        self.vector_store = vector_store
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.debug = debug

    def retrieve(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        """检索相关文档块（同步，ChromaDB 原生支持文本查询）"""
        k = top_k or self.top_k
        if not query.strip():
            return []

        processed_query = self._preprocess_query(query)

        if self.debug:
            _log.info(f"[RAG] 检索查询: '{query[:80]}' -> 预处理后: '{processed_query[:80]}'")

        results = self.vector_store.search(
            query_text=processed_query,
            top_k=k * 2,  # 多取一些给 rerank 筛选
            threshold=self.similarity_threshold,
        )

        if self.debug:
            _log.info(f"[RAG] ChromaDB 返回 {len(results)} 条 (threshold={self.similarity_threshold})")

        results = self._rerank(query, results)
        results = results[:k]

        if self.debug and results:
            _log.info(f"[RAG] 检索到 {len(results)} 个 chunks:")
            for i, r in enumerate(results, 1):
                score = r.get("score", 0)
                title = r.get("title", "?")
                chunk_id = r.get("chunk_id", "?")
                text_preview = r.get("text", "")[:60].replace("\n", " ")
                _log.info(f"[RAG]   [{i}] score={score:.4f} title='{title}' chunk='{chunk_id}' text='{text_preview}...'")

        return results

    def _preprocess_query(self, query: str) -> str:
        query = re.sub(r'@\S+', '', query)
        query = re.sub(r'\[[^\]]{1,10}\]', '', query)
        query = re.sub(r'\s+', ' ', query).strip()
        return query

    def _rerank(self, query: str, results: list[dict]) -> list[dict]:
        if not results:
            return results

        if _has_jieba:
            query_tokens = set(jieba.cut(query))
        else:
            query_tokens = set(query)

        for r in results:
            text = r.get("text", "")
            if _has_jieba:
                text_tokens = set(jieba.cut(text))
            else:
                text_tokens = set(text)

            overlap = len(query_tokens & text_tokens)
            keyword_bonus = min(0.2, overlap * 0.02)

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
        if not results:
            return ""

        if template:
            context_parts = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "未知")
                text = r.get("text", "")
                context_parts.append(f"[{i}] ({title}) {text}")
            return template.format(context="\n\n".join(context_parts))

        lines = ["【相关知识】"]
        for i, r in enumerate(results, 1):
            text = r.get("text", "")
            lines.append(f"{i}. {text}")
        return "\n".join(lines)
