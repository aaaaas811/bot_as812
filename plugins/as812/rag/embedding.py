"""嵌入服务 — ChromaDB EmbeddingFunction，支持 API / TF-IDF 两种模式"""
import os

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
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        base_url = str(cfg.get("api_base_url", "")).strip()
        api_key = str(cfg.get("api_key", "")).strip()
        return base_url, api_key
    except Exception:
        return "", ""


class RAGEmbeddingFunction:
    """ChromaDB 兼容的嵌入函数，优先用 API，失败时回退 TF-IDF"""

    def __init__(self, mode: str = "api", model: str = "text-embedding-3-small", dim: int = 1536, debug: bool = False):
        self.mode = mode
        self.model = model
        self.dim = dim
        self.debug = debug

        # TF-IDF 索引（惰性构建）
        self._tfidf_vocab: dict[str, int] = {}
        self._tfidf_idf: dict[str, float] = {}
        self._tfidf_docs: list[list[str]] = []

        if self.debug:
            _log.info(f"[RAG] EmbeddingFunction 初始化: mode={mode}, model={model}, dim={dim}")

    def name(self) -> str:
        return f"as812-rag-{self.mode}-{self.model}"

    def __call__(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 文档嵌入接口"""
        return self._embed(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 查询嵌入接口 (1.5.x 新增)"""
        return self._embed(input)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """内部嵌入实现"""
        import asyncio

        if self.mode == "api":
            try:
                try:
                    loop = asyncio.get_running_loop()
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, self._embed_api(texts))
                        return future.result()
                except RuntimeError:
                    return asyncio.run(self._embed_api(texts))
            except Exception as e:
                _log.warning(f"[RAG] API 嵌入失败: {e}，回退到 TF-IDF")
                return self._embed_tfidf(texts)
        else:
            return self._embed_tfidf(texts)

    async def _embed_api(self, texts: list[str]) -> list[list[float]]:
        base_url, api_key = _get_api_config()
        if not base_url or not api_key:
            _log.warning("[RAG] API 配置缺失，回退到 TF-IDF")
            return self._embed_tfidf(texts)

        url = f"{base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {"model": self.model, "input": texts}

        try:
            if self.debug:
                _log.info(f"[RAG] 调用 Embedding API: url={url}, model={self.model}, count={len(texts)}")
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        embeddings = [item.get("embedding", []) for item in result.get("data", [])]
                        if self.debug:
                            _log.info(f"[RAG] Embedding API 成功: {len(embeddings)} 个向量, dim={len(embeddings[0]) if embeddings else 0}")
                        return embeddings
                    else:
                        error_text = await resp.text()
                        _log.warning(f"[RAG] Embedding API 返回 {resp.status}: {error_text[:200]}，回退到 TF-IDF")
                        return self._embed_tfidf(texts)
        except Exception as e:
            _log.warning(f"[RAG] Embedding API 调用失败: {e}，回退到 TF-IDF")
            return self._embed_tfidf(texts)

    def _embed_tfidf(self, texts: list[str]) -> list[list[float]]:
        if not _has_numpy:
            return [[0.0] * self.dim for _ in texts]

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
            bigrams = [t[i:i+2] for i in range(len(t)-1)
                       if re.match(r'[一-鿿]', t[i]) and re.match(r'[一-鿿]', t[i+1])]
            tokens.extend(bigrams)
            return tokens

        tokenized = [tokenize(t) for t in texts]

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

        tfidf_vectors = np.zeros((len(texts), V))
        for i, tokens in enumerate(tokenized):
            tf = Counter(tokens)
            for term, count in tf.items():
                if term in vocab_idx:
                    j = vocab_idx[term]
                    tf_val = count / len(tokens) if tokens else 0
                    idf_val = math.log((N + 1) / (df[term] + 1)) + 1
                    tfidf_vectors[i, j] = tf_val * idf_val

        if V <= self.dim:
            padded = np.zeros((len(texts), self.dim))
            padded[:, :V] = tfidf_vectors
            return padded.tolist()

        rng = np.random.RandomState(42)
        proj = rng.randn(V, self.dim) / np.sqrt(self.dim)
        reduced = tfidf_vectors @ proj
        norms = np.linalg.norm(reduced, axis=1, keepdims=True)
        norms[norms == 0] = 1
        reduced = reduced / norms
        return reduced.tolist()
