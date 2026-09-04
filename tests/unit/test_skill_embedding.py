"""单元测试 — 广场语义向量栈（V3.0 M3.2，架构 §19.5.6 / 计划 M3.2、F-33、VNF-02、R-12）

覆盖：
- tokenize / cosine_similarity 基础算子；
- FallbackHashEmbeddingProvider 确定性 + L2 归一化（权重缺失降级路径，dev/test 默认）；
- get_embedding_provider 单例与降级选定；
- EmbeddingStore 双实现（JsonbEmbeddingStore upsert/search/clear；PgVectorEmbeddingStore 维度不匹配退回 JSONB）；
- create_embedding_store 工厂按运行期探测降级（pgvector 不可用 → JSONB，R-12/VNF-02）；
- plaza.derive_involve_flags（R2→database / R3→server / 混合 / 空）；
- plaza.scan_plaza_similar（向量优先 + 关键词兜底 + exclude 自身）；
- plaza.search_plaza_semantic（空候选/空查询短路 + 委托 store 排序）。

用轻量 FakeSession 替代真实 AsyncSession（按 SQL 文本分派 execute 结果），provider 走确定性哈希降级，
不依赖 fastembed / 真实 DB / pgvector。
"""

from __future__ import annotations

import math

import pytest

from platform_mcp.skills.embedding import (
    FallbackHashEmbeddingProvider,
    JsonbEmbeddingStore,
    PgVectorEmbeddingStore,
    cosine_similarity,
    create_embedding_store,
    embed_text,
    get_embedding_provider,
    reset_embedding_provider,
    tokenize,
)
from platform_mcp.skills.models import PmcpSkillPlaza
from platform_mcp.skills.plaza import (
    INVOLVE_DATABASE,
    INVOLVE_SERVER,
    derive_involve_flags,
    scan_plaza_similar,
    search_plaza_semantic,
)


class FakeSession:
    """轻量伪 AsyncSession：按 SQL 文本分派 execute 结果，支持 get/add/flush。

    - ``pg_extension`` 查询 → ``.first()`` 返回可配置的 pgvector 探测结果；
    - 列投影查询（``pmcp_skill_plaza.embedding`` 且非全实体）→ ``.all()`` 返回 ``embedding_rows``；
    - 全实体查询（``pmcp_skill_plaza``）→ ``.scalars().all()`` 返回 ``plaza_rows``。
    """

    def __init__(self) -> None:
        self._store: dict[tuple[type, int], object] = {}
        self._added: list[object] = []
        self._id_seq = 500
        self.flush_count = 0
        self.pgvector_row: object | None = None
        self.plaza_rows: list[PmcpSkillPlaza] = []
        self.embedding_rows: list[tuple[int, list[float]]] = []
        self.raw_sql: list[str] = []

    def seed(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._id_seq
            self._id_seq += 1
        self._store[(type(obj), obj.id)] = obj
        return obj

    async def get(self, model, pk):
        return self._store.get((model, pk))

    def add(self, obj) -> None:
        self._added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        for obj in self._added:
            if getattr(obj, "id", None) is None:
                obj.id = self._id_seq
                self._id_seq += 1
                self._store[(type(obj), obj.id)] = obj

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.raw_sql.append(sql)
        result = _FakeResult()
        if "pg_extension" in sql:
            result.first_value = self.pgvector_row
        elif "pmcp_skill_plaza.embedding" in sql and "pmcp_skill_plaza.skill_code" not in sql:
            result.all_rows = list(self.embedding_rows)
        elif "pmcp_skill_plaza" in sql:
            result.scalar_rows = list(self.plaza_rows)
        if params and "embedding_vec" in sql:
            # PgVectorEmbeddingStore 的原生 UPDATE/SELECT —— 记录后按列投影返回
            result.all_rows = list(self.embedding_rows)
        return result


class _FakeResult:
    def __init__(self) -> None:
        self.first_value: object | None = None
        self.all_rows: list = []
        self.scalar_rows: list = []

    def first(self):
        return self.first_value

    def all(self):
        return self.all_rows

    def scalars(self):
        return _Scalars(self.scalar_rows)

    def scalar_one_or_none(self):
        return self.scalar_rows[0] if self.scalar_rows else None


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return self._rows


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_embedding_provider()
    yield
    reset_embedding_provider()


# ==================== 基础算子 ====================


class TestTokenize:
    def test_中英文切分并去停用词(self):
        tokens = tokenize("数据库 备份 skill of the Oracle")
        assert "数据库" in tokens
        assert "oracle" in tokens
        assert "skill" not in tokens  # 停用词
        assert "of" not in tokens
        assert "the" not in tokens

    def test_单字被过滤(self):
        assert tokenize("a b 我 是") == []

    def test_空值返回空(self):
        assert tokenize(None) == []
        assert tokenize("") == []


class TestCosine:
    def test_相同向量相似度为1(self):
        assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_正交向量相似度为0(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_维度不一致返回0(self):
        assert cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0

    def test_空向量返回0(self):
        assert cosine_similarity(None, [1.0]) == 0.0
        assert cosine_similarity([], []) == 0.0

    def test_零向量返回0(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


# ==================== 降级哈希 Provider ====================


class TestFallbackProvider:
    def test_确定性同文本同向量(self):
        p = FallbackHashEmbeddingProvider(dim=64)
        assert p.embed(["Oracle 备份"]) == p.embed(["Oracle 备份"])

    def test_维度符合配置(self):
        p = FallbackHashEmbeddingProvider(dim=128)
        assert len(p.embed(["x"])[0]) == 128
        assert p.dim == 128

    def test_L2归一化(self):
        p = FallbackHashEmbeddingProvider(dim=64)
        vec = p.embed(["数据库 备份 恢复"])[0]
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0, abs=1e-6)

    def test_相似文本余弦高于无关文本(self):
        p = FallbackHashEmbeddingProvider(dim=256)
        base = p.embed(["Oracle 数据库 备份 恢复"])[0]
        near = p.embed(["Oracle 数据库 备份 归档"])[0]
        far = p.embed(["SSH 服务器 端口 监听"])[0]
        assert cosine_similarity(base, near) > cosine_similarity(base, far)

    def test_空文本零向量(self):
        p = FallbackHashEmbeddingProvider(dim=32)
        assert all(x == 0.0 for x in p.embed([""])[0])

    def test_available恒为真(self):
        assert FallbackHashEmbeddingProvider().available is True
        assert FallbackHashEmbeddingProvider().name == "fallback-hash"


class TestProviderSelection:
    def test_无权重路径选定降级哈希(self):
        # settings.skill.embedding_model_path 默认空 → 降级哈希（dev/test 默认，VNF-03 不联网）
        provider = get_embedding_provider()
        assert provider.name == "fallback-hash"
        assert provider.available is True

    def test_单例复用(self):
        assert get_embedding_provider() is get_embedding_provider()

    def test_reset后重新选定(self):
        first = get_embedding_provider()
        reset_embedding_provider()
        second = get_embedding_provider()
        assert first is not second

    async def test_embed_text异步返回向量(self):
        vec = await embed_text("Oracle 备份")
        assert isinstance(vec, list)
        assert all(isinstance(x, float) for x in vec)
        assert len(vec) == get_embedding_provider().dim


# ==================== JsonbEmbeddingStore ====================


class TestJsonbStore:
    async def test_upsert写入plaza_embedding并flush(self):
        db = FakeSession()
        plaza = db.seed(PmcpSkillPlaza(skill_code="s1", skill_name="N", status="PUBLISHED"))
        store = JsonbEmbeddingStore(db)
        await store.upsert(plaza.id, [0.1, 0.2, 0.3])
        assert plaza.embedding == [0.1, 0.2, 0.3]
        assert db.flush_count >= 1

    async def test_upsert不存在plaza静默跳过(self):
        db = FakeSession()
        store = JsonbEmbeddingStore(db)
        await store.upsert(9999, [1.0])  # 不抛异常

    async def test_search按余弦降序(self):
        db = FakeSession()
        db.embedding_rows = [(1, [1.0, 0.0]), (2, [0.0, 1.0]), (3, [0.9, 0.1])]
        store = JsonbEmbeddingStore(db)
        ranked = await store.search([1.0, 0.0], top_k=3, candidate_ids=[1, 2, 3])
        assert ranked[0][0] == 1  # 完全一致最高分
        assert ranked[0][1] == pytest.approx(1.0)
        assert [pid for pid, _ in ranked] == [1, 3, 2]

    async def test_search_top_k截断(self):
        db = FakeSession()
        db.embedding_rows = [(1, [1.0, 0.0]), (2, [0.5, 0.5]), (3, [0.0, 1.0])]
        store = JsonbEmbeddingStore(db)
        ranked = await store.search([1.0, 0.0], top_k=1, candidate_ids=[1, 2, 3])
        assert len(ranked) == 1

    async def test_search空候选或top_k非正返回空(self):
        db = FakeSession()
        store = JsonbEmbeddingStore(db)
        assert await store.search([1.0], top_k=5, candidate_ids=[]) == []
        db.embedding_rows = [(1, [1.0])]
        assert await store.search([1.0], top_k=0, candidate_ids=[1]) == []

    async def test_search跳过无向量副本(self):
        db = FakeSession()
        db.embedding_rows = [(1, [1.0, 0.0]), (2, None)]
        store = JsonbEmbeddingStore(db)
        ranked = await store.search([1.0, 0.0], top_k=5, candidate_ids=[1, 2])
        assert [pid for pid, _ in ranked] == [1]

    async def test_clear置空向量(self):
        db = FakeSession()
        plaza = db.seed(PmcpSkillPlaza(skill_code="s1", skill_name="N", status="PUBLISHED", embedding=[1.0]))
        store = JsonbEmbeddingStore(db)
        await store.clear(plaza.id)
        assert plaza.embedding is None

    def test_backend标识(self):
        assert JsonbEmbeddingStore(FakeSession()).backend == "jsonb"


# ==================== PgVectorEmbeddingStore ====================


class TestPgVectorStore:
    async def test_维度不匹配退回JSONB内存余弦(self):
        db = FakeSession()
        db.embedding_rows = [(1, [1.0, 0.0]), (2, [0.0, 1.0])]
        store = PgVectorEmbeddingStore(db, dim=1024)
        # 256 维降级哈希向量 ≠ 1024 → 退回 JSONB 路径，仍返回可用结果
        ranked = await store.search([1.0, 0.0], top_k=2, candidate_ids=[1, 2])
        assert ranked[0][0] == 1
        assert not any("embedding_vec <=>" in s for s in db.raw_sql)

    async def test_upsert镜像写JSONB(self):
        db = FakeSession()
        plaza = db.seed(PmcpSkillPlaza(skill_code="s1", skill_name="N", status="PUBLISHED"))
        store = PgVectorEmbeddingStore(db, dim=4)
        await store.upsert(plaza.id, [0.5, 0.5, 0.5, 0.5])
        assert plaza.embedding == [0.5, 0.5, 0.5, 0.5]  # JSONB 镜像（切换无损）

    async def test_upsert维度匹配触发原生SQL(self):
        db = FakeSession()
        plaza = db.seed(PmcpSkillPlaza(skill_code="s1", skill_name="N", status="PUBLISHED"))
        store = PgVectorEmbeddingStore(db, dim=2)
        await store.upsert(plaza.id, [0.1, 0.2])
        assert any("embedding_vec" in s for s in db.raw_sql)

    async def test_upsert维度不匹配跳过原生SQL(self):
        db = FakeSession()
        plaza = db.seed(PmcpSkillPlaza(skill_code="s1", skill_name="N", status="PUBLISHED"))
        store = PgVectorEmbeddingStore(db, dim=1024)
        await store.upsert(plaza.id, [0.1, 0.2])
        assert not any("SET embedding_vec" in s for s in db.raw_sql)

    def test_backend标识(self):
        assert PgVectorEmbeddingStore(FakeSession(), dim=1024).backend == "pgvector"

    def test_literal向量字面量(self):
        assert PgVectorEmbeddingStore._literal([1.0, 2.5]) == "[1.0,2.5]"


# ==================== create_embedding_store 工厂 ====================


class TestStoreFactory:
    async def test_pgvector不可用降级JSONB(self):
        db = FakeSession()
        db.pgvector_row = None  # 运行期探测：扩展未安装
        store = await create_embedding_store(db, backend="auto")
        assert isinstance(store, JsonbEmbeddingStore)

    async def test_pgvector可用选原生后端(self):
        db = FakeSession()
        db.pgvector_row = (1,)  # 扩展已安装
        store = await create_embedding_store(db, backend="auto")
        assert isinstance(store, PgVectorEmbeddingStore)

    async def test_显式jsonb忽略探测(self):
        db = FakeSession()
        db.pgvector_row = (1,)
        store = await create_embedding_store(db, backend="jsonb")
        assert isinstance(store, JsonbEmbeddingStore)

    async def test_显式pgvector但不可用降级JSONB(self):
        db = FakeSession()
        db.pgvector_row = None
        store = await create_embedding_store(db, backend="pgvector")
        assert isinstance(store, JsonbEmbeddingStore)


# ==================== derive_involve_flags（F-23 / 需求 1.1.4）====================


class TestDeriveInvolveFlags:
    def test_R2命中派生database(self):
        audit = {"failed_rules": [{"rule_id": "R2-01"}, {"rule_id": "R2-02"}]}
        assert derive_involve_flags(audit) == [INVOLVE_DATABASE]

    def test_R3命中派生server(self):
        audit = {"failed_rules": [{"rule_id": "R3-01"}, {"rule_id": "R3-02"}]}
        assert derive_involve_flags(audit) == [INVOLVE_SERVER]

    def test_R2R3混合排序去重(self):
        audit = {"failed_rules": [{"rule_id": "R3-01"}, {"rule_id": "R2-01"}, {"rule_id": "R3-02"}]}
        assert derive_involve_flags(audit) == [INVOLVE_DATABASE, INVOLVE_SERVER]

    def test_仅R1R4R5无涉库标记(self):
        audit = {"failed_rules": [{"rule_id": "R1-01"}, {"rule_id": "R4-01"}, {"rule_id": "R5-01"}]}
        assert derive_involve_flags(audit) == []

    def test_空审计或无failed_rules(self):
        assert derive_involve_flags(None) == []
        assert derive_involve_flags({}) == []
        assert derive_involve_flags({"failed_rules": []}) == []
        assert derive_involve_flags({"failed_rules": None}) == []


# ==================== scan_plaza_similar ====================


def _make_plaza(pid: int, code: str, name: str, desc: str) -> PmcpSkillPlaza:
    return PmcpSkillPlaza(id=pid, skill_code=code, skill_name=name, description=desc, status="PUBLISHED")


class TestScanPlazaSimilar:
    async def test_无候选返回空(self):
        db = FakeSession()
        db.plaza_rows = []
        assert await scan_plaza_similar(db, "Oracle", "备份") == []

    async def test_向量优先精确匹配merge推荐(self):
        db = FakeSession()
        db.pgvector_row = None  # JSONB 路径
        p1 = _make_plaza(1, "oracle-backup", "Oracle 备份", "数据库备份恢复")
        db.plaza_rows = [p1]
        # 广场副本向量 = 查询向量 → 余弦 1.0 ≥ 阈值 → merge
        qvec = await embed_text("Oracle 备份 数据库备份恢复")
        db.embedding_rows = [(1, qvec)]
        recs = await scan_plaza_similar(db, "Oracle 备份", "数据库备份恢复")
        assert len(recs) == 1
        assert recs[0]["skill_code"] == "oracle-backup"
        assert recs[0]["similarity"] == pytest.approx(1.0, abs=1e-6)
        assert recs[0]["recommendation"] == "merge"

    async def test_低相似度推荐new(self):
        db = FakeSession()
        db.pgvector_row = None
        p1 = _make_plaza(1, "ssh-tool", "SSH 服务器", "远程端口监听")
        db.plaza_rows = [p1]
        qvec = await embed_text("SSH 服务器 远程端口监听")
        # 存储一个与查询正交的向量 → 相似度低 → new
        ortho = [0.0] * len(qvec)
        ortho[0] = 1.0
        if qvec[0] != 0.0:
            ortho = [0.0] * len(qvec)
            # 找一个查询向量为 0 的维度置 1，保证正交
            for i, v in enumerate(qvec):
                if v == 0.0:
                    ortho[i] = 1.0
                    break
        db.embedding_rows = [(1, ortho)]
        recs = await scan_plaza_similar(db, "SSH 服务器", "远程端口监听")
        assert recs[0]["recommendation"] == "new"

    async def test_无向量走关键词兜底(self):
        db = FakeSession()
        db.pgvector_row = None
        p1 = _make_plaza(1, "oracle-backup", "Oracle 备份 恢复", "数据库 备份 恢复 归档")
        p2 = _make_plaza(2, "ssh-tool", "SSH 服务器", "远程 端口 监听")
        db.plaza_rows = [p1, p2]
        db.embedding_rows = []  # 广场副本尚无向量 → 关键词重叠度兜底
        recs = await scan_plaza_similar(db, "Oracle 备份 恢复", "数据库 备份 恢复")
        codes = [r["skill_code"] for r in recs]
        assert "oracle-backup" in codes
        assert codes[0] == "oracle-backup"  # 名称重叠高排前

    async def test_exclude_skill_code排除自身(self):
        db = FakeSession()
        db.pgvector_row = None
        p1 = _make_plaza(1, "self-code", "Oracle 备份", "数据库")
        db.plaza_rows = [p1]
        db.embedding_rows = []
        recs = await scan_plaza_similar(db, "Oracle 备份", "数据库", exclude_skill_code="self-code")
        assert recs == []

    async def test_返回契约字段完整(self):
        db = FakeSession()
        db.pgvector_row = None
        p1 = _make_plaza(1, "c1", "Oracle 备份", "数据库")
        db.plaza_rows = [p1]
        db.embedding_rows = []
        recs = await scan_plaza_similar(db, "Oracle 备份", "数据库")
        assert set(recs[0].keys()) == {
            "plaza_id", "skill_code", "skill_name", "description", "version", "similarity", "recommendation"
        }


# ==================== search_plaza_semantic ====================


class TestSearchPlazaSemantic:
    async def test_空候选返回空(self):
        db = FakeSession()
        assert await search_plaza_semantic(db, "Oracle", []) == []

    async def test_空查询返回空(self):
        db = FakeSession()
        assert await search_plaza_semantic(db, "   ", [1, 2]) == []

    async def test_委托store按余弦排序(self):
        db = FakeSession()
        db.pgvector_row = None
        db.embedding_rows = [(1, [1.0, 0.0]), (2, [0.0, 1.0])]
        ranked = await search_plaza_semantic(db, "查询", [1, 2], top_k=2)
        # 只验证委托排序返回 [(plaza_id, score)] 结构且降序
        assert isinstance(ranked, list)
        assert all(isinstance(item, tuple) and len(item) == 2 for item in ranked)
        scores = [s for _, s in ranked]
        assert scores == sorted(scores, reverse=True)
