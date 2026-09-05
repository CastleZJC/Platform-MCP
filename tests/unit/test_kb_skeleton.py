"""三期知识库骨架测试（V3.0 M6，架构 §19.6；F-41）

覆盖验收 F-41 四要素：
1. kb 五表 ORM 就绪（表名/关键列/唯一约束）；
2. 7 切片策略枚举（值域 + 非法值拒绝）；
3. RAG/GRAPH 抽象可 import（ABC 强制：不可实例化、缺实现子类被拒、完整子类可用）；
4. api/kb.py 占位端点全部返回 HTTP 501 + 统一响应 code=15002（系统错误段）。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from platform_mcp.api.kb import router as kb_router
from platform_mcp.kb import (
    CHUNKING_STRATEGIES,
    ChunkingStrategy,
    GraphEdge,
    GraphNode,
    GraphStore,
    Indexer,
    PmcpKb,
    PmcpKbChunk,
    PmcpKbDoc,
    PmcpKbShare,
    PmcpKbVersion,
    Retriever,
)
from platform_mcp.kb.chunking import STRATEGY_DESCRIPTIONS, coerce_strategy


# ==== 1. 五表 ORM 就绪（F-41）====


class TestKbOrmReady:
    def test_five_tables_registered(self):
        """五表表名与 ORM 类一一对应（BaseModel 元数据注册即建表就绪）。"""
        assert PmcpKb.__tablename__ == "pmcp_kb"
        assert PmcpKbDoc.__tablename__ == "pmcp_kb_doc"
        assert PmcpKbChunk.__tablename__ == "pmcp_kb_chunk"
        assert PmcpKbVersion.__tablename__ == "pmcp_kb_version"
        assert PmcpKbShare.__tablename__ == "pmcp_kb_share"

    def test_kb_columns(self):
        cols = {c.name for c in PmcpKb.__table__.columns}
        assert {"kb_code", "kb_name", "kb_type", "owner_id", "description", "status"} <= cols
        assert {"id", "inserted_at", "updated_at", "inserted_by", "updated_by"} <= cols

    def test_kb_type_domain_check(self):
        """kb_type 值域 CHECK（personal/shared）随表定义。"""
        checks = {c.name: c.sqltext.text for c in PmcpKb.__table__.constraints if hasattr(c, "sqltext")}
        assert "kb_type IN ('personal', 'shared')" in checks["ck_pmcp_kb_type_domain"]

    def test_chunk_columns_and_unique(self):
        cols = {c.name for c in PmcpKbChunk.__table__.columns}
        assert {"doc_id", "chunk_index", "chunking_strategy", "content", "embedding"} <= cols
        uniques = {
            u.name
            for u in PmcpKbChunk.__table__.constraints
            if u.__class__.__name__ == "UniqueConstraint"
        }
        assert "uq_pmcp_kb_chunk_doc_idx" in uniques

    def test_version_bilingual_columns_align_skill_convention(self):
        """版本表双语字段对齐 pmcp_skill_version 惯例 + UNIQUE(kb_id, version)。"""
        cols = {c.name for c in PmcpKbVersion.__table__.columns}
        assert {"readme_zh", "readme_en", "report_zh", "report_en", "audit_snapshot", "generated_by"} <= cols
        uniques = {
            u.name
            for u in PmcpKbVersion.__table__.constraints
            if u.__class__.__name__ == "UniqueConstraint"
        }
        assert "uq_pmcp_kb_version_kb_ver" in uniques

    def test_share_columns(self):
        cols = {c.name for c in PmcpKbShare.__table__.columns}
        assert {"kb_id", "shared_by", "review_status", "merge_target_id", "review_comment"} <= cols

    def test_public_columns_on_all_tables(self):
        """BaseModel 公共列（id/inserted_at/updated_at/inserted_by/updated_by）全表齐备。"""
        common = {"id", "inserted_at", "updated_at", "inserted_by", "updated_by"}
        for model in (PmcpKb, PmcpKbDoc, PmcpKbChunk, PmcpKbVersion, PmcpKbShare):
            assert common <= {c.name for c in model.__table__.columns}, model.__tablename__


# ==== 2. 7 切片策略枚举（F-41）====


class TestChunkingStrategies:
    def test_exactly_seven_strategies(self):
        assert len(ChunkingStrategy) == 7
        assert CHUNKING_STRATEGIES == frozenset(ChunkingStrategy)

    def test_strategy_values(self):
        assert {s.value for s in ChunkingStrategy} == {
            "fixed",
            "sentence",
            "paragraph",
            "semantic",
            "recursive",
            "markdown_heading",
            "sliding_window",
        }

    def test_every_strategy_has_description(self):
        assert set(STRATEGY_DESCRIPTIONS) == set(ChunkingStrategy)

    def test_coerce_rejects_unknown_value(self):
        assert coerce_strategy("fixed") is ChunkingStrategy.FIXED
        with pytest.raises(ValueError):
            coerce_strategy("not-a-strategy")


# ==== 3. RAG / GRAPH 抽象可 import（F-41）====


class TestAbstractionsImportable:
    def test_abstract_classes_cannot_instantiate(self):
        for cls in (Indexer, Retriever, GraphStore):
            with pytest.raises(TypeError):
                cls()  # type: ignore[abstract]

    def test_partial_implementation_rejected(self):
        class _IncompleteRetriever(Retriever):
            pass  # 缺 retrieve 实现

        with pytest.raises(TypeError):
            _IncompleteRetriever()  # type: ignore[abstract]

    def test_full_implementation_instantiable(self):
        class _StubRetriever(Retriever):
            async def retrieve(self, *, kb_id: int, query: str, top_k: int = 5) -> list:
                return []

        class _StubIndexer(Indexer):
            async def index_document(self, *, kb_id: int, doc_id: int, content: str, strategy) -> int:
                return 0

            async def remove_document(self, doc_id: int) -> int:
                return 0

        class _StubGraphStore(GraphStore):
            async def upsert_nodes(self, *, kb_id: int, nodes: list) -> int:
                return 0

            async def upsert_edges(self, *, kb_id: int, edges: list) -> int:
                return 0

            async def neighbors(self, *, kb_id: int, node_id: str, relation=None, max_depth: int = 1) -> dict:
                return {"nodes": [], "edges": []}

            async def remove_document(self, doc_id: int) -> int:
                return 0

        assert isinstance(_StubRetriever(), Retriever)
        assert isinstance(_StubIndexer(), Indexer)
        assert isinstance(_StubGraphStore(), GraphStore)

    def test_graph_dataclasses(self):
        node = GraphNode(node_id="e1", label="实体一")
        edge = GraphEdge(source_id="e1", target_id="e2", relation="属于")
        assert node.properties == {}
        assert edge.properties == {}
        assert edge.relation == "属于"


# ==== 4. api/kb.py 占位端点 501（F-41）====

_ALL_KB_ENDPOINTS = [
    ("GET", "/api/v1/kb"),
    ("POST", "/api/v1/kb"),
    ("GET", "/api/v1/kb/1"),
    ("POST", "/api/v1/kb/1/docs"),
    ("GET", "/api/v1/kb/1/search"),
    ("GET", "/api/v1/kb/1/graph"),
    ("POST", "/api/v1/kb/1/share"),
]


@pytest.fixture
def client():
    """轻量 app 仅挂 kb router（501 占位无 DB/认证依赖）。"""
    app = FastAPI()
    app.include_router(kb_router, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _ALL_KB_ENDPOINTS)
async def test_kb_endpoints_return_501(client, method, path):
    resp = await client.request(method, path)
    assert resp.status_code == 501
    body = resp.json()
    # 统一 5 字段响应体 + 占位错误码（15002 系统错误段，与 15001 通用码区分）
    assert body["code"] == 15002
    assert {"code", "message", "data", "trace_id", "timestamp"} <= set(body)
    assert "三期" in body["message"] or "骨架" in body["message"]
