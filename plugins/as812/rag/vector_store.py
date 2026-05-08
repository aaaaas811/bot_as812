"""向量存储 — 基于 ChromaDB PersistentClient"""
import os
from typing import Optional

from ncatbot.utils.logger import get_log

_log = get_log()

try:
    import chromadb
    _has_chromadb = True
except ImportError:
    chromadb = None  # type: ignore
    _has_chromadb = False


class VectorStore:
    """基于 ChromaDB 的向量存储"""

    def __init__(self, data_dir: str, collection: str = "default", embedding_function=None):
        if not _has_chromadb:
            raise ImportError("chromadb 未安装，请运行: pip install chromadb")

        self.collection_name = collection
        persist_dir = os.path.join(data_dir, "chroma_db")
        os.makedirs(persist_dir, exist_ok=True)

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._embedding_function = embedding_function

        self._collection = self._client.get_or_create_collection(
            name=collection,
            embedding_function=embedding_function,
        )

    def add(self, texts: list[str], metadatas: list[dict], ids: list[str]) -> int:
        """批量添加文本（嵌入自动生成），返回添加数量"""
        if not texts:
            return 0

        self._collection.add(
            documents=texts,
            metadatas=metadatas,
            ids=ids,
        )
        return len(texts)

    def remove(self, source_id: str) -> int:
        """按 source_id 删除，返回删除数量"""
        existing = self._collection.get(
            where={"source_id": source_id},
        )
        if existing["ids"]:
            self._collection.delete(ids=existing["ids"])
            return len(existing["ids"])
        return 0

    def search(self, query_text: str, top_k: int = 5, threshold: float = 0.5) -> list[dict]:
        """文本查询（嵌入和相似度计算由 ChromaDB 完成）"""
        results = self._collection.query(
            query_texts=[query_text],
            n_results=top_k,
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        scored = []
        for i, chunk_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results.get("distances") else 0
            # ChromaDB 默认用余弦距离 (0=相同, 2=相反)，转相似度
            similarity = 1.0 - (distance / 2.0)
            if similarity < threshold:
                continue
            meta = dict(results["metadatas"][0][i]) if results.get("metadatas") else {}
            meta["score"] = similarity
            meta["text"] = results["documents"][0][i] if results.get("documents") else ""
            meta["chunk_id"] = chunk_id
            scored.append(meta)

        return scored

    def list_sources(self) -> list[dict]:
        """列出所有知识源（通过遍历去重 source_id）"""
        all_data = self._collection.get()
        sources: dict[str, dict] = {}
        if all_data["metadatas"]:
            for meta in all_data["metadatas"]:
                sid = meta.get("source_id", "")
                if sid not in sources:
                    sources[sid] = {
                        "source_id": sid,
                        "title": meta.get("title", sid),
                        "chunk_count": 0,
                    }
                sources[sid]["chunk_count"] += 1
        return sorted(sources.values(), key=lambda x: x["title"])

    def count(self) -> int:
        return self._collection.count()

    def clear(self):
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self._embedding_function,
        )
