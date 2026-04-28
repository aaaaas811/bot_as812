"""向量存储 — 基于 numpy 的轻量向量数据库"""
import json
import os
from typing import Optional

from ncatbot.utils.logger import get_log

_log = get_log()

try:
    import numpy as np
    _has_numpy = True
except Exception:
    np = None
    _has_numpy = False


class VectorStore:
    """轻量向量存储，使用 numpy 数组 + JSON 元数据索引"""

    def __init__(self, data_dir: str, collection: str = "default", dim: int = 768):
        self.data_dir = data_dir
        self.collection = collection
        self.dim = dim
        self._vectors: list = []        # list of np.ndarray
        self._metadata: list[dict] = []  # 每条记录的元数据

        os.makedirs(self._collection_dir, exist_ok=True)
        self._load()

    @property
    def _collection_dir(self) -> str:
        return os.path.join(self.data_dir, self.collection)

    @property
    def _vectors_path(self) -> str:
        return os.path.join(self._collection_dir, "vectors.npy")

    @property
    def _metadata_path(self) -> str:
        return os.path.join(self._collection_dir, "metadata.json")

    def _load(self):
        if os.path.exists(self._vectors_path) and os.path.exists(self._metadata_path):
            try:
                if _has_numpy:
                    self._vectors = list(np.load(self._vectors_path, allow_pickle=False))
                else:
                    self._vectors = []
                with open(self._metadata_path, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
            except Exception as e:
                _log.warning(f"加载向量存储失败: {e}")
                self._vectors = []
                self._metadata = []
        else:
            self._vectors = []
            self._metadata = []

    def _save(self):
        try:
            if _has_numpy and self._vectors:
                arr = np.array(self._vectors)
                np.save(self._vectors_path, arr)
            with open(self._metadata_path, "w", encoding="utf-8") as f:
                json.dump(self._metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log.error(f"保存向量存储失败: {e}")

    def add(self, vectors: list[list[float]], metadata_list: list[dict]) -> int:
        """批量添加向量和元数据，返回添加数量"""
        if len(vectors) != len(metadata_list):
            raise ValueError(f"向量数量({len(vectors)})与元数据数量({len(metadata_list)})不匹配")

        count = 0
        for vec, meta in zip(vectors, metadata_list):
            if _has_numpy:
                self._vectors.append(np.array(vec, dtype=np.float32))
            else:
                self._vectors.append(list(vec))
            self._metadata.append(meta)
            count += 1

        self._save()
        return count

    def remove(self, source_id: str) -> int:
        """删除指定来源的所有向量，返回删除数量"""
        indices_to_remove = [
            i for i, meta in enumerate(self._metadata)
            if meta.get("source_id") == source_id
        ]
        for i in reversed(indices_to_remove):
            del self._vectors[i]
            del self._metadata[i]

        if indices_to_remove:
            self._save()

        return len(indices_to_remove)

    def remove_by_ids(self, chunk_ids: list[str]) -> int:
        """按 chunk_id 批量删除"""
        ids_set = set(chunk_ids)
        indices_to_remove = [
            i for i, meta in enumerate(self._metadata)
            if meta.get("chunk_id") in ids_set
        ]
        for i in reversed(indices_to_remove):
            del self._vectors[i]
            del self._metadata[i]

        if indices_to_remove:
            self._save()

        return len(indices_to_remove)

    def search(self, query_vector: list[float], top_k: int = 5, threshold: float = 0.5) -> list[dict]:
        """余弦相似度搜索，返回 top_k 结果"""
        if not self._vectors:
            return []

        if _has_numpy:
            query = np.array(query_vector, dtype=np.float32)
            matrix = np.array(self._vectors)

            # 归一化
            query_norm = query / (np.linalg.norm(query) + 1e-8)
            matrix_norms = np.linalg.norm(matrix, axis=1) + 1e-8
            matrix_normed = matrix / matrix_norms[:, np.newaxis]

            # 余弦相似度
            similarities = np.dot(matrix_normed, query_norm)

            # 排序获取 top_k
            top_indices = np.argsort(similarities)[::-1][:top_k]
            results = []
            for idx in top_indices:
                score = float(similarities[idx])
                if score >= threshold:
                    meta = dict(self._metadata[idx])
                    meta["score"] = score
                    results.append(meta)
            return results
        else:
            # 纯 Python 余弦相似度
            def cosine_sim(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = (sum(x * x for x in a) + 1e-8) ** 0.5
                norm_b = (sum(x * x for x in b) + 1e-8) ** 0.5
                return dot / (norm_a * norm_b)

            scored = []
            for i, vec in enumerate(self._vectors):
                score = cosine_sim(query_vector, vec)
                if score >= threshold:
                    meta = dict(self._metadata[i])
                    meta["score"] = score
                    scored.append(meta)

            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]

    def list_sources(self) -> list[dict]:
        """列出所有知识源"""
        sources = {}
        for meta in self._metadata:
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
        return len(self._vectors)

    def clear(self):
        self._vectors = []
        self._metadata = []
        self._save()
