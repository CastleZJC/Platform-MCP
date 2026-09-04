"""单元测试 — 广场可见性过滤与查询（V3.0 M3.1/M3.3，架构 §19.5.3 / 需求 1.1.4 / F-23/F-33/F-34）

覆盖：
- plaza_visible_to_role 三角色 × 涉库标记矩阵（一般用户不见涉库/涉服务器，admin/developer 全可见）；
- involves_restricted 受限标记判定；
- load_blocked_plaza_ids 黑名单读侧加载（F-34，user_id 空短路）；
- list_visible_plazas 角色过滤 + 关键词搜索 + 黑名单排除；
- search_visible_plazas 可见候选内语义排序 + involve_flags 输出。

用轻量 FakeSession 按 SQL 表名分派 execute 结果，provider 走确定性哈希降级，不触真实 DB / pgvector。
"""

from __future__ import annotations

import pytest

from platform_mcp.skills.embedding import embed_text, reset_embedding_provider
from platform_mcp.skills.models import PmcpSkillBlacklist, PmcpSkillPlaza
from platform_mcp.skills.plaza import (
    INVOLVE_DATABASE,
    INVOLVE_SERVER,
    REGULAR_USER_ROLE,
    involves_restricted,
    list_visible_plazas,
    load_blocked_plaza_ids,
    plaza_visible_to_role,
    search_visible_plazas,
)


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return self._rows


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


class FakeSession:
    """按 SQL 表名分派：pg_extension 探测 / 黑名单 / 广场实体 / 向量列投影。"""

    def __init__(self) -> None:
        self._store: dict[tuple[type, int], object] = {}
        self.plaza_rows: list[PmcpSkillPlaza] = []
        self.blacklist_plaza_ids: list[int] = []
        self.embedding_rows: list[tuple[int, list[float]]] = []
        self.pgvector_row: object | None = None

    def seed(self, obj):
        self._store[(type(obj), obj.id)] = obj
        return obj

    async def get(self, model, pk):
        return self._store.get((model, pk))

    def add(self, obj) -> None:  # pragma: no cover - 查询层不新增
        pass

    async def flush(self) -> None:  # pragma: no cover
        pass

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        result = _FakeResult()
        if "pg_extension" in sql:
            result.first_value = self.pgvector_row
        elif "pmcp_skill_blacklist" in sql:
            result.scalar_rows = list(self.blacklist_plaza_ids)
        elif "pmcp_skill_plaza.embedding" in sql and "pmcp_skill_plaza.skill_code" not in sql:
            result.all_rows = list(self.embedding_rows)
        elif "pmcp_skill_plaza" in sql:
            result.scalar_rows = list(self.plaza_rows)
        return result


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_embedding_provider()
    yield
    reset_embedding_provider()


def _plaza(pid, code, name="N", desc="d", flags=None, status="PUBLISHED") -> PmcpSkillPlaza:
    return PmcpSkillPlaza(
        id=pid, skill_code=code, skill_name=name, description=desc,
        involve_flags=flags, status=status, version="1.0",
    )


# ==================== 可见性判定（三角色 × 涉库矩阵）====================


class TestPlazaVisibleToRole:
    def test_仅PUBLISHED可见(self):
        assert plaza_visible_to_role("PUBLISHED", [], "admin") is True
        assert plaza_visible_to_role("DISABLED", [], "admin") is False
        assert plaza_visible_to_role(None, [], "admin") is False

    def test_一般用户不见涉库(self):
        assert plaza_visible_to_role("PUBLISHED", [INVOLVE_DATABASE], REGULAR_USER_ROLE) is False

    def test_一般用户不见涉服务器(self):
        assert plaza_visible_to_role("PUBLISHED", [INVOLVE_SERVER], REGULAR_USER_ROLE) is False

    def test_一般用户不见双标记(self):
        assert plaza_visible_to_role("PUBLISHED", [INVOLVE_DATABASE, INVOLVE_SERVER], REGULAR_USER_ROLE) is False

    def test_一般用户可见无标记(self):
        assert plaza_visible_to_role("PUBLISHED", [], REGULAR_USER_ROLE) is True
        assert plaza_visible_to_role("PUBLISHED", None, REGULAR_USER_ROLE) is True

    def test_admin可见涉库(self):
        assert plaza_visible_to_role("PUBLISHED", [INVOLVE_DATABASE], "admin") is True

    def test_developer可见涉库(self):
        assert plaza_visible_to_role("PUBLISHED", [INVOLVE_SERVER], "developer") is True

    def test_未知角色按非一般用户处理(self):
        # 非 "user" 角色（含 None/未来角色）默认可见涉库项，与"一般用户特判"一致
        assert plaza_visible_to_role("PUBLISHED", [INVOLVE_DATABASE], None) is True


class TestInvolvesRestricted:
    def test_命中标记为真(self):
        assert involves_restricted([INVOLVE_DATABASE]) is True
        assert involves_restricted([INVOLVE_SERVER]) is True
        assert involves_restricted(["other", INVOLVE_DATABASE]) is True

    def test_空或无标记为假(self):
        assert involves_restricted([]) is False
        assert involves_restricted(None) is False
        assert involves_restricted(["other"]) is False


# ==================== 黑名单读侧加载 ====================


class TestLoadBlockedPlazaIds:
    async def test_无user_id短路返回空(self):
        db = FakeSession()
        assert await load_blocked_plaza_ids(db, None) == set()

    async def test_加载屏蔽集合(self):
        db = FakeSession()
        db.blacklist_plaza_ids = [3, 7]
        assert await load_blocked_plaza_ids(db, 1) == {3, 7}

    async def test_空黑名单返回空集(self):
        db = FakeSession()
        db.blacklist_plaza_ids = []
        assert await load_blocked_plaza_ids(db, 1) == set()


# ==================== list_visible_plazas ====================


class TestListVisiblePlazas:
    async def test_一般用户过滤涉库项(self):
        db = FakeSession()
        db.plaza_rows = [
            _plaza(1, "plain", "普通工具", "无涉库"),
            _plaza(2, "db-tool", "数据库工具", "直连", flags=[INVOLVE_DATABASE]),
            _plaza(3, "srv-tool", "服务器工具", "监听", flags=[INVOLVE_SERVER]),
        ]
        visible = await list_visible_plazas(db, REGULAR_USER_ROLE)
        codes = {p.skill_code for p in visible}
        assert codes == {"plain"}  # 涉库/涉服务器对一般用户不可见

    async def test_admin见全部(self):
        db = FakeSession()
        db.plaza_rows = [
            _plaza(1, "plain"),
            _plaza(2, "db-tool", flags=[INVOLVE_DATABASE]),
        ]
        visible = await list_visible_plazas(db, "admin")
        assert {p.skill_code for p in visible} == {"plain", "db-tool"}

    async def test_developer见全部(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "plain"), _plaza(2, "db-tool", flags=[INVOLVE_DATABASE])]
        visible = await list_visible_plazas(db, "developer")
        assert len(visible) == 2

    async def test_仅PUBLISHED(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "a", status="PUBLISHED"), _plaza(2, "b", status="DISABLED")]
        # 注：SQL 已按 status 过滤，此处再经 plaza_visible_to_role 双保险
        visible = await list_visible_plazas(db, "admin")
        assert {p.skill_code for p in visible} == {"a"}

    async def test_黑名单排除(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "a"), _plaza(2, "b"), _plaza(3, "c")]
        visible = await list_visible_plazas(db, "admin", blocked_plaza_ids={2})
        assert {p.skill_code for p in visible} == {"a", "c"}

    async def test_关键词搜索命中名称(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "oracle-backup", "Oracle 备份"), _plaza(2, "ssh-tool", "SSH 服务器")]
        visible = await list_visible_plazas(db, "admin", search="oracle")
        assert [p.skill_code for p in visible] == ["oracle-backup"]

    async def test_关键词搜索命中描述(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "a", "工具甲", "数据库备份"), _plaza(2, "b", "工具乙", "网络监听")]
        visible = await list_visible_plazas(db, "admin", search="备份")
        assert [p.skill_code for p in visible] == ["a"]

    async def test_空搜索返回全部可见(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "a"), _plaza(2, "b")]
        assert len(await list_visible_plazas(db, "admin", search="   ")) == 2


# ==================== search_visible_plazas ====================


class TestSearchVisiblePlazas:
    async def test_一般用户搜索结果不含涉库(self):
        db = FakeSession()
        db.plaza_rows = [
            _plaza(1, "oracle-backup", "Oracle 备份", "数据库备份恢复"),
            _plaza(2, "db-admin", "数据库管理", "直连执行 DML", flags=[INVOLVE_DATABASE]),
        ]
        results = await search_visible_plazas(db, REGULAR_USER_ROLE, "数据库管理")
        codes = {r["skill_code"] for r in results}
        assert "db-admin" not in codes  # 涉库项对一般用户不可见

    async def test_admin搜索含涉库并带标记(self):
        db = FakeSession()
        db.plaza_rows = [
            _plaza(1, "oracle-backup", "Oracle 备份", "备份 恢复"),
            _plaza(2, "db-admin", "数据库管理", "直连 DML", flags=[INVOLVE_DATABASE]),
        ]
        results = await search_visible_plazas(db, "admin", "数据库管理")
        by_code = {r["skill_code"]: r for r in results}
        assert "db-admin" in by_code
        assert by_code["db-admin"]["involve_flags"] == [INVOLVE_DATABASE]

    async def test_搜索结果按相似度降序(self):
        db = FakeSession()
        db.plaza_rows = [
            _plaza(1, "oracle-backup", "Oracle 备份 恢复", "数据库 备份 恢复 归档"),
            _plaza(2, "ssh-tool", "SSH 服务器", "远程 端口 监听"),
        ]
        results = await search_visible_plazas(db, "admin", "Oracle 备份 恢复")
        scores = [r["similarity"] for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0]["skill_code"] == "oracle-backup"

    async def test_黑名单排除搜索结果(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")]
        results = await search_visible_plazas(db, "admin", "Oracle 备份", blocked_plaza_ids={1})
        assert results == []

    async def test_返回结构含关键字段(self):
        db = FakeSession()
        db.plaza_rows = [_plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")]
        results = await search_visible_plazas(db, "admin", "Oracle 备份")
        assert results
        assert set(results[0].keys()) >= {
            "plaza_id", "skill_code", "skill_name", "description", "version",
            "involve_flags", "iteration_note", "similarity",
        }

    async def test_向量优先命中已建向量副本(self):
        db = FakeSession()
        p1 = _plaza(1, "oracle-backup", "Oracle 备份", "数据库备份恢复")
        db.plaza_rows = [p1]
        qvec = await embed_text("Oracle 备份")
        db.embedding_rows = [(1, qvec)]
        results = await search_visible_plazas(db, "admin", "Oracle 备份")
        assert results[0]["plaza_id"] == 1
        assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-6)
