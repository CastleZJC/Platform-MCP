"""GRAPH 抽象接口（V3.0 M6 骨架，架构 §19.6；F-41）

三期「RAG + GRAPH 双维护」的图谱侧抽象：知识库文档抽取的实体/关系存图，
与切片向量并行维护，检索期可图邻接扩展。V3.0 仅交付抽象契约，不含实现类
（存储候选三期评估：JSONB 邻接表起步 / 图数据库按生产环境引入）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GraphNode:
    """图谱节点：实体（节点 ID 在知识库内唯一）。"""

    node_id: str
    label: str
    properties: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """图谱有向边：实体间关系（source → target，relation 为关系类型）。"""

    source_id: str
    target_id: str
    relation: str
    properties: dict = field(default_factory=dict)


class GraphStore(ABC):
    """图谱存储抽象：节点/边 upsert + 邻接查询 + 文档级清理（三期实现）。"""

    @abstractmethod
    async def upsert_nodes(self, *, kb_id: int, nodes: list[GraphNode]) -> int:
        """批量 upsert 节点（按 ``kb_id`` + ``node_id`` 去重），返回写入数。"""

    @abstractmethod
    async def upsert_edges(self, *, kb_id: int, edges: list[GraphEdge]) -> int:
        """批量 upsert 有向边（端点节点须已存在），返回写入数。"""

    @abstractmethod
    async def neighbors(
        self, *, kb_id: int, node_id: str, relation: str | None = None, max_depth: int = 1
    ) -> dict:
        """查询 ``node_id`` 的 ``max_depth`` 跳邻接子图（可按关系类型过滤）。

        返回 ``{"nodes": [...], "edges": [...]}``（序列化 GraphNode/GraphEdge）。
        """

    @abstractmethod
    async def remove_document(self, doc_id: int) -> int:
        """删除该文档抽取的全部节点/边（文档移除时联动清理），返回删除数。"""
