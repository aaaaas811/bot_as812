"""知识库管理 — 文档 CRUD、导入导出"""
import os
import json
import time
from typing import Optional

from ncatbot.utils.logger import get_log

from .document import DocumentChunker, Chunk
from .embedding import EmbeddingService
from .vector_store import VectorStore

_log = get_log()


class KnowledgeBase:
    """知识库：管理文档的添加、删除、查询和导入导出"""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        chunker: DocumentChunker,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.chunker = chunker

    async def add_document(
        self, content: str, title: str = "", source_id: Optional[str] = None, metadata: Optional[dict] = None
    ) -> int:
        """添加文档到知识库，返回 chunk 数量"""
        sid = source_id or f"doc_{int(time.time())}_{hash(content) % 10000}"
        title = title or sid

        chunks = self.chunker.chunk(content, metadata=metadata, source_id=sid)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = await self.embedding_service.embed_texts(texts)

        metadata_list = []
        for c in chunks:
            meta = {
                "chunk_id": f"{sid}_chunk_{c.chunk_index}",
                "source_id": sid,
                "title": title,
                "text": c.text,
                "chunk_index": c.chunk_index,
                "added_at": time.time(),
            }
            if c.metadata:
                meta.update(c.metadata)
            metadata_list.append(meta)

        count = self.vector_store.add(embeddings, metadata_list)
        _log.info(f"已添加文档 '{title}'（{sid}），共 {count} 个 chunks")
        return count

    async def add_documents_batch(self, docs: list[dict]) -> int:
        """批量添加文档，每个文档为 {"content": ..., "title": ..., "source_id": ...}"""
        total = 0
        for doc in docs:
            total += await self.add_document(
                content=doc.get("content", ""),
                title=doc.get("title", ""),
                source_id=doc.get("source_id"),
                metadata=doc.get("metadata"),
            )
        return total

    def remove_document(self, source_id: str) -> int:
        """删除指定 source_id 的文档"""
        return self.vector_store.remove(source_id)

    def list_documents(self) -> list[dict]:
        """列出所有文档"""
        return self.vector_store.list_sources()

    def get_document_chunks(self, source_id: str) -> list[dict]:
        """获取指定文档的所有 chunk"""
        # 通过元数据查找
        chunks = []
        for meta in self._all_metadata():
            if meta.get("source_id") == source_id:
                chunks.append(meta)
        return sorted(chunks, key=lambda x: x.get("chunk_index", 0))

    def _all_metadata(self) -> list[dict]:
        return self.vector_store._metadata

    async def import_text_file(self, filepath: str, title: Optional[str] = None) -> int:
        """从文本文件导入知识"""
        if not os.path.exists(filepath):
            _log.warning(f"文件不存在: {filepath}")
            return 0

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            _log.error(f"读取文件失败: {e}")
            return 0

        source_id = os.path.basename(filepath)
        title = title or os.path.splitext(source_id)[0]
        return await self.add_document(content, title=title, source_id=source_id)

    def clear(self):
        """清空知识库"""
        self.vector_store.clear()

    def stats(self) -> dict:
        """知识库统计"""
        sources = self.vector_store.list_sources()
        return {
            "total_documents": len(sources),
            "total_chunks": self.vector_store.count(),
            "sources": sources,
        }
