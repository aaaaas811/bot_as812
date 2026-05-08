"""知识库管理 — 文档 CRUD、导入导出"""
import os
import re
import time
from typing import Optional

from ncatbot.utils.logger import get_log

from .document import DocumentChunker
from .vector_store import VectorStore

_log = get_log()


def _safe_filename(name: str) -> str:
    """将标题转为安全文件名，保留中文"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip().strip('.')
    return name or "untitled"


class KnowledgeBase:
    """知识库：管理文档的添加、删除、查询和导入导出"""

    def __init__(self, vector_store: VectorStore, chunker: DocumentChunker, data_dir: str = ""):
        self.vector_store = vector_store
        self.chunker = chunker
        self._data_dir = data_dir

    def add_document(
        self, content: str, title: str = "", source_id: Optional[str] = None, metadata: Optional[dict] = None
    ) -> int:
        sid = source_id or f"doc_{int(time.time())}_{hash(content) % 10000}"
        title = title or sid

        chunks = self.chunker.chunk(content, metadata=metadata, source_id=sid)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        ids = [f"{sid}_chunk_{c.chunk_index}" for c in chunks]
        metadatas = []
        for c in chunks:
            meta = {
                "source_id": sid,
                "title": title,
                "chunk_index": c.chunk_index,
                "added_at": time.time(),
            }
            if c.metadata:
                meta.update(c.metadata)
            metadatas.append(meta)

        count = self.vector_store.add(texts=texts, metadatas=metadatas, ids=ids)
        _log.info(f"已添加文档 '{title}'（{sid}），共 {count} 个 chunks")

        # 保存为 .txt 文件方便查看管理
        if self._data_dir:
            self._save_text_file(title, sid, content)

        return count

    def _save_text_file(self, title: str, source_id: str, content: str):
        """将知识内容保存为 .txt 文件"""
        os.makedirs(self._data_dir, exist_ok=True)
        safe_title = _safe_filename(title)
        filename = f"{safe_title}.txt"
        filepath = os.path.join(self._data_dir, filename)

        # 避免覆盖已有文件，加后缀区分
        if os.path.exists(filepath):
            base = safe_title
            i = 1
            while os.path.exists(os.path.join(self._data_dir, f"{base}_{i}.txt")):
                i += 1
            filename = f"{base}_{i}.txt"
            filepath = os.path.join(self._data_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            _log.info(f"知识已保存到文件: {filename}")
        except Exception as e:
            _log.warning(f"保存知识文件失败: {e}")

    def add_documents_batch(self, docs: list[dict]) -> int:
        total = 0
        for doc in docs:
            total += self.add_document(
                content=doc.get("content", ""),
                title=doc.get("title", ""),
                source_id=doc.get("source_id"),
                metadata=doc.get("metadata"),
            )
        return total

    def remove_document(self, source_id: str) -> int:
        # 先查标题，以便删除对应文件
        if self._data_dir:
            existing = self.vector_store._collection.get(where={"source_id": source_id})
            if existing["metadatas"]:
                title = existing["metadatas"][0].get("title", source_id)
                safe_title = _safe_filename(title)
                for fname in [f"{safe_title}.txt"] + [f"{safe_title}_{i}.txt" for i in range(1, 100)]:
                    fpath = os.path.join(self._data_dir, fname)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                        break

        return self.vector_store.remove(source_id)

    def list_documents(self) -> list[dict]:
        return self.vector_store.list_sources()

    def import_text_file(self, filepath: str, title: Optional[str] = None) -> int:
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
        return self.add_document(content, title=title, source_id=source_id)

    def clear(self):
        self.vector_store.clear()

    def stats(self) -> dict:
        sources = self.vector_store.list_sources()
        return {
            "total_documents": len(sources),
            "total_chunks": self.vector_store.count(),
            "sources": sources,
        }
