"""嵌入服务 — 将文本转换为向量"""
import asyncio
import hashlib
import json
import os
from typing import Optional

import aiohttp
import yaml
from ncatbot.utils.logger import get_log

_log = get_log()

try:
    import numpy as np
    _has_numpy = True
except Exception:
    np = None
    _has_numpy = False


def _get_api_config() -> tuple[str, str]:
    """读取 API base_url 和 api_key"""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        base_url = str(cfg.get("api_base_url", "")).strip()
        api_key = str(cfg.get("api_key", "")).strip()
        return base_url, api_key
    except Exception:
        return "", ""


class EmbeddingService:
    """文本嵌入服务，支持 API / TF-IDF 两种模式"""

    def __init__(self, mode: str = "api", model: str = "text-embedding-3-small", dim: int = 1536):
        self.mode = mode
        self.model = model
        self.dim = dim
        self._tfidf_vocab: dict[str, int] = {}
        self._tfidf_idf: Optional[dict] = None
        self._cache: dict[str, list[float]] = {}
        self._cache_file: Optional[str] = None

    def set_cache_file(self, path: str):
        self._cache_file = path
        self._load_cache()

    def _load_cache(self):
        if self._cache_file and os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}

    def _save_cache(self):
        if self._cache_file:
            try:
                os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
                with open(self._cache_file, "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, ensure_ascii=False)
            except Exception:
                pass

    def _cache_key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """将文本列表转换为向量列表"""
        results = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                results.append((i, self._cache[key]))
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)
                results.append((i, None))

        if uncached_texts:
            if self.mode == "api":
                embeddings = await self._embed_api(uncached_texts)
            else:
                embeddings = self._embed_tfidf(uncached_texts)

            for idx, emb in zip(uncached_indices, embeddings):
                results[idx] = (idx, emb)
                key = self._cache_key(uncached_texts[uncached_indices.index(idx)])
                self._cache[key] = emb

            self._save_cache()

        return [emb for _, emb in sorted(results, key=lambda x: x[0])]

    async def embed_text(self, text: str) -> list[float]:
        """单文本嵌入"""
        results = await self.embed_texts([text])
        return results[0]

    async def _embed_api(self, texts: list[str]) -> list[list[float]]:
        """通过兼容 OpenAI 的 API 获取嵌入"""
        base_url, api_key = _get_api_config()
        if not base_url or not api_key:
            _log.warning("API 配置缺失，回退到 TF-IDF 嵌入")
            return self._embed_tfidf(texts)

        url = f"{base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {"model": self.model, "input": texts}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        embeddings = []
                        for item in result.get("data", []):
                            embeddings.append(item.get("embedding", []))
                        return embeddings
                    else:
                        _log.warning(f"Embedding API 错误: {resp.status}，回退到 TF-IDF")
                        return self._embed_tfidf(texts)
        except Exception as e:
            _log.warning(f"Embedding API 调用失败: {e}，回退到 TF-IDF")
            return self._embed_tfidf(texts)

    def _embed_tfidf(self, texts: list[str]) -> list[list[float]]:
        """TF-IDF 回退嵌入（无需外部依赖，仅需 numpy）"""
        if not _has_numpy:
            # 纯 Python 回退：返回零向量
            return [[0.0] * self.dim for _ in texts]

        import re
        import math
        from collections import Counter

        # 分词（简单的中文按字符 + 英文按词）
        def tokenize(t: str) -> list[str]:
            tokens = []
            for ch in t:
                if re.match(r'[一-鿿]', ch):
                    tokens.append(ch)
                elif re.match(r'[a-zA-Z0-9]', ch):
                    tokens.append(ch.lower())
            # 同时加入 2-gram 字符
            bigrams = [t[i:i+2] for i in range(len(t)-1) if re.match(r'[一-鿿]', t[i]) and re.match(r'[一-鿿]', t[i+1])]
            tokens.extend(bigrams)
            return tokens

        tokenized = [tokenize(t) for t in texts]

        # 构建全局词汇表
        df = Counter()
        for tokens in tokenized:
            for term in set(tokens):
                df[term] += 1

        N = len(texts)
        vocab = sorted(df.keys())
        vocab_idx = {term: i for i, term in enumerate(vocab)}
        V = len(vocab)

        if V == 0:
            return [[0.0] * self.dim for _ in texts]

        # TF-IDF 向量
        tfidf_vectors = np.zeros((len(texts), V))
        for i, tokens in enumerate(tokenized):
            tf = Counter(tokens)
            for term, count in tf.items():
                if term in vocab_idx:
                    j = vocab_idx[term]
                    tf_val = count / len(tokens) if tokens else 0
                    idf_val = math.log((N + 1) / (df[term] + 1)) + 1
                    tfidf_vectors[i, j] = tf_val * idf_val

        # 通过 SVD 风格的随机投影降维到 target dim
        if V <= self.dim:
            # 补零
            padded = np.zeros((len(texts), self.dim))
            padded[:, :V] = tfidf_vectors
            return padded.tolist()

        # 随机投影降维
        rng = np.random.RandomState(42)
        proj = rng.randn(V, self.dim) / np.sqrt(self.dim)
        reduced = tfidf_vectors @ proj
        # 归一化
        norms = np.linalg.norm(reduced, axis=1, keepdims=True)
        norms[norms == 0] = 1
        reduced = reduced / norms
        return reduced.tolist()

    def build_tfidf_index(self, corpus: list[str]):
        """为 TF-IDF 模式预构建稀疏检索索引"""
        if not _has_numpy:
            return
        import re
        import math
        from collections import Counter

        def tokenize(t: str) -> list[str]:
            tokens = []
            for ch in t:
                if re.match(r'[一-鿿]', ch):
                    tokens.append(ch)
                elif re.match(r'[a-zA-Z0-9]', ch):
                    tokens.append(ch.lower())
            bigrams = [t[i:i+2] for i in range(len(t)-1) if re.match(r'[一-鿿]', t[i]) and re.match(r'[一-鿿]', t[i+1])]
            tokens.extend(bigrams)
            return tokens

        tokenized_corpus = [tokenize(doc) for doc in corpus]
        df = Counter()
        for tokens in tokenized_corpus:
            for term in set(tokens):
                df[term] += 1

        N = len(corpus)
        self._tfidf_vocab = {term: i for i, term in enumerate(sorted(df.keys()))}
        self._tfidf_idf = {}
        for term, count in df.items():
            self._tfidf_idf[term] = math.log((N + 1) / (count + 1)) + 1
