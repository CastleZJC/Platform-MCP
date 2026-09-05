"""RAG 抽象接口（V3.0 M6 骨架，架构 §19.6；F-41）

三期实现（候选：JSONB + 内存余弦 / pgvector，对齐 ``skills/embedding.py``
EmbeddingStore 双实现惯例）；V3.0 仅交付抽象契约，不含实现类。

契约约定：
- Indexer 负责入库：文档 → 切片（策略见 ``kb/chunking.py``）→ 向量化 → 落
  ``pmcp_kb_chunk``（content + chunking_strategy + embedding）；
- Retriever 负责检索：query 向量化 → 相似度排序 → topK 切片（含来源信息）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from platform_mcp.kb.chunking import ChunkingStrategy


@dataclass
class RetrievedChunk:
    """检索单元结果：切片内容 + 来源定位 + 相似度得分。"""

    chunk_id: int
    doc_id: int
    content: str
    score: float
    chunking_strategy: str | None = None
    extra: dict = field(default_factory=dict)


class Indexer(ABC):
    """切片入库抽象：文档内容 → 切片落库（三期实现）。"""

    @abstractmethod
    async def index_document(
        self,
        *,
        kb_id: int,
        doc_id: int,
        content: str,
        strategy: ChunkingStrategy,
    ) -> int:
        """按 ``strategy`` 切分 ``content`` 并向量化落 ``pmcp_kb_chunk``，返回切片数。

        实现要求（三期）：幂等（同 doc 重复索引先清旧切片）；切片序号从 0 连续；
        ``chunking_strategy`` 落库值必须来自 :class:`ChunkingStrategy`。
        """

    @abstractmethod
    async def remove_document(self, doc_id: int) -> int:
        """删除该文档全部切片（文档移除时联动清理），返回删除数。"""


class Retriever(ABC):
    """语义检索抽象：query → topK 切片（三期实现）。"""

    @abstractmethod
    async def retrieve(self, *, kb_id: int, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """在 ``kb_id`` 内检索与 ``query`` 最相似的 ``top_k`` 个切片（得分降序）。"""
