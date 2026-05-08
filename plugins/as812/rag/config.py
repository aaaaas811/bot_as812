"""RAG 配置"""
from dataclasses import dataclass, field


@dataclass
class RAGConfig:
    """RAG 系统配置"""

    enabled: bool = False

    # 嵌入模型配置
    embedding_mode: str = "api"     # "api" | "tfidf"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # 检索配置
    top_k: int = 5
    similarity_threshold: float = 0.5

    # 分块配置
    chunk_size: int = 512
    chunk_overlap: int = 64
    chunk_strategy: str = "paragraph"

    # 存储路径（相对于 rag 模块目录）
    data_dir: str = "rag_data"

    # 检索触发方式
    trigger_mode: str = "keyword"
    trigger_keywords: list = field(default_factory=lambda: [
        "什么是", "怎么", "如何", "攻略", "帮助", "help", "是什么", "告诉我", "什么", "介绍一下"
    ])

    # 上下文注入方式
    context_template: str = (
        '【参考资料】以下是与当前对话可能相关的知识，请在回复时参考：\n'
        '---\n'
        '{context}\n'
        '---\n'
        '请根据以上参考资料和你的知识，自然地回复用户。'
        '不要直接说「根据参考资料」，而是将知识融入回复中。'
        '如果参考资料与当前问题无关，请忽略。'
    )

    debug: bool = False
