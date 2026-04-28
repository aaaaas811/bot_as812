"""文档分块 — 支持多种分块策略"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    """文档块"""
    text: str
    metadata: dict = field(default_factory=dict)
    chunk_index: int = 0
    source_id: str = ""  # 来源文档 ID


class DocumentChunker:
    """文档分块器"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64, strategy: str = "paragraph"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy

    def chunk(self, text: str, metadata: Optional[dict] = None, source_id: str = "") -> list[Chunk]:
        """将文本分块"""
        meta = metadata or {}
        if self.strategy == "paragraph":
            chunks = self._chunk_by_paragraph(text)
        elif self.strategy == "sentence":
            chunks = self._chunk_by_sentence(text)
        else:
            chunks = self._chunk_fixed(text)

        return [
            Chunk(text=c, metadata=meta, chunk_index=i, source_id=source_id)
            for i, c in enumerate(chunks)
        ]

    def _chunk_by_paragraph(self, text: str) -> list[str]:
        """按段落分块，合并短段落以接近 chunk_size"""
        paragraphs = re.split(r'\n\s*\n+', text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) <= self.chunk_size:
                current = (current + "\n\n" + p).strip() if current else p
            else:
                if current:
                    chunks.append(current)
                # 如果单个段落超过 chunk_size，递归用 fixed 策略再分
                if len(p) > self.chunk_size:
                    sub_chunks = self._chunk_fixed(p)
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    current = p

        if current:
            chunks.append(current)

        return chunks

    def _chunk_by_sentence(self, text: str) -> list[str]:
        """按句子分块"""
        sentences = re.split(r'(?<=[。！？.!?\n])\s*', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) <= self.chunk_size:
                current = (current + s).strip() if current else s
            else:
                if current:
                    chunks.append(current)
                if len(s) > self.chunk_size:
                    sub_chunks = self._chunk_fixed(s)
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    current = s

        if current:
            chunks.append(current)

        return chunks

    def _chunk_fixed(self, text: str) -> list[str]:
        """固定大小分块（带重叠）"""
        chunks = []
        start = 0
        text_len = len(text)
        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start += (self.chunk_size - self.chunk_overlap)
        return chunks
