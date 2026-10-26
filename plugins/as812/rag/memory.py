"""保守的原话记忆：本地索引、会话隔离、按用户纠正和时间遗忘。"""
import hashlib
import math
import re
import threading
import time
from pathlib import Path


class LocalMemoryEmbedding:
    """固定哈希特征，避免词表随批次或重启变化；不访问网络。"""

    def name(self):
        return "as812-memory-hash-v1"

    def is_legacy(self):
        # 由 VectorStore 显式传入实例，沿用 Chroma 的自定义嵌入兼容接口。
        return True

    def __call__(self, input):
        vectors = []
        for text in input:
            vector = [0.0] * 1536
            parts = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", text.lower())
            for part in parts:
                tokens = [part] if part.isascii() else [part[i:i+2] for i in range(len(part) - 1)]
                for token in tokens:
                    digest = hashlib.sha256(token.encode()).digest()
                    index = int.from_bytes(digest[:4], "little") % len(vector)
                    vector[index] += 1.0 if digest[4] & 1 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

    def embed_query(self, input):
        return self(input)


class ChatMemory:
    # 保留原话，不让模型替用户编造事实；不保存临时状态、引用、问题、凭据和指令。
    _reject = re.compile(
        r'[?？“”"「」『』\n]|(?:吗|么|呢)[，,。！!\s]*$|什么|怎么|如何|哪里|哪种|是否|'
        r'今天|现在|暂时|刚刚|开玩笑|假如|如果|他说|她说|引用|转发|'
        r'别记|不要记|不用记|忘记|密码|口令|密钥|验证码|token|api.?key|'
        r'忽略|规则|指令|system|prompt|##|https?://', re.I
    )
    _fact = re.compile(
        r'^我(?:(?:最|更|很|一直|平时|特别|比较)?(?:喜欢|不喜欢|讨厌|偏好|习惯|擅长|爱吃|不吃|常用)|'
        r'(?:的)?(?:主武器|职业|生日|昵称)(?:是|为)|住在|来自|叫)'
    )

    def __init__(self, store, config):
        self.store = store
        self.config = config
        self.lock = threading.RLock()
        self._last_prune = 0.0
        background = Path(__file__).with_name("background_knowledge.txt").read_text(encoding="utf-8").strip()
        existing = store.records({"kind": "background"})
        if not existing or existing[0]["text"] != background:
            store.upsert([background], [{"kind": "background", "source_id": "prompt_avatar_v1",
                                        "title": "as812 头像外观"}], ["prompt_avatar_v1"])

    def strength(self, record, now):
        age = max(0, now - record["last_seen"]) / 86400
        if age > self.config.memory_max_age_days:
            return 0.0
        return record["importance"] * 2 ** (-age / max(0.1, self.config.memory_half_life_days))

    def prune(self, now):
        if now - self._last_prune < 3600:
            return
        records = self.store.records({"kind": "memory"})
        self.store.delete_ids([r["chunk_id"] for r in records
                               if self.strength(r, now) < self.config.memory_min_strength])
        self._last_prune = now

    def observe(self, scope, messages, bot_qq):
        if not self.config.memory_enabled:
            return
        with self.lock:
            now = time.time()
            self.prune(now)
            where = {"$and": [{"kind": "memory"}, {"scope": scope}]}
            records = {r["chunk_id"]: r for r in self.store.records(where)}
            for message in messages:
                text = str(message.get("message") or "").strip()
                qq = str(message.get("qq") or "")
                if not qq or qq == str(bot_qq) or len(text) > 160 or self._reject.search(text):
                    continue
                text = re.sub(r'^@\S+\s*', '', text).strip()
                text = re.sub(r'^(?:as)?812[，,:：\s]*', '', text, flags=re.I).strip()
                explicit = re.match(r'^(?:请)?(?:帮我)?记住[：:,，\s]*(.+)$', text)
                if explicit:
                    text = explicit[1].strip()
                elif not self._fact.match(text):
                    continue
                if len(text) < 4:
                    continue
                try:
                    observed_at = min(float(message.get("timestamp", now)), now)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(observed_at):
                    continue
                importance = 0.95 if explicit else 0.7
                record = {"kind": "memory", "scope": scope, "user_qq": qq,
                          "last_seen": observed_at, "importance": importance,
                          "title": "聊天记忆", "fact": text}
                if self.strength(record, now) < self.config.memory_min_strength:
                    continue
                # 单值信息按用户替换；偏好按对象去重，保留不同喜好。
                slot = text.rstrip('，,。.!！ ')
                for prefix in ("我住在", "我来自", "我叫"):
                    if text.startswith(prefix):
                        slot = prefix
                        break
                single_value = re.match(r'^我(?:的)?(主武器|职业|生日|昵称)(?:是|为)', text)
                if single_value:
                    slot = single_value[1]
                preference = re.match(r'^我(?:最|更|很|一直|平时|特别|比较)?(?:喜欢|不喜欢|讨厌)(.+)$', text)
                if preference:
                    slot = "偏好:" + preference[1].rstrip('，,。.!！ ')
                key = hashlib.sha256(f"{scope}\0{qq}\0{slot}".encode()).hexdigest()
                cid = "memory_" + key
                previous = records.get(cid)
                if previous and previous["last_seen"] >= observed_at - 0.001:
                    continue
                nickname = str(message.get("nickname") or qq)[:32]
                content = f"{nickname}(QQ:{qq})曾说：{text}"
                record["source_id"] = cid
                self.store.upsert([content], [record], [cid])
                records[cid] = dict(record, text=content, chunk_id=cid)
            # 每个会话只保留少量记忆，先淘汰已弱化的信息。
            ranked = sorted(records.values(), key=lambda r: self.strength(r, now), reverse=True)
            self.store.delete_ids([r["chunk_id"] for r in ranked[max(0, self.config.memory_max_per_scope):]])

    def retrieve(self, query, scope, user_qq):
        with self.lock:
            now = time.time()
            self.prune(now)
            filters = [{"kind": "background"}]
            if scope and self.config.memory_enabled:
                personal = [{"kind": "memory"}, {"scope": scope}]
                if re.search(r'我(?:的|喜欢|不喜欢|讨厌|偏好|习惯|擅长|住|叫|来自|最|更|生日|职业|主武器|是谁)|本人', query) and user_qq:
                    personal.append({"user_qq": str(user_qq)})
                filters.append({"$and": personal})
            where = filters[0] if len(filters) == 1 else {"$or": filters}
            results = self.store.search(query, top_k=12, threshold=0.16, where=where)
            selected = []
            for result in results:
                strength = self.strength(result, now) if result["kind"] == "memory" else 1.0
                if strength < self.config.memory_min_strength:
                    continue
                result["score"] *= strength
                selected.append(result)
            return sorted(selected, key=lambda r: r["score"], reverse=True)
