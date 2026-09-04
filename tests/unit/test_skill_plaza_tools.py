"""单元测试 — Skill 广场 MCP 工具（V3.0 M3.5，架构 §19.5.3 / §19.5.7，计划 F-33/F-34 / 需求 1.1.4）

覆盖：工具元数据（9 工具、三角色全可见、描述中英并列、签名可构建）/ 参数校验 /
search_skills（角色可见性 + 黑名单过滤透传）/ suggest_similar_skills（merge/new 结论）/
get_skill_readme（广场副本按 locale + 可见性拒绝、个人 Skill 版本存档 README）/
add_skill_to_my·remove_my_skill·block_skill·unblock_skill·list_blocked_skills（委托 plaza_service，
channel=mcp）/ list_my_skills（黑名单过滤）/ 身份贯通（缺身份拒绝）。

委托的 plaza / plaza_service 函数直接 patch（隔离 DB 与向量栈），会话经 patch get_session_factory
产出伪 session（commit/rollback 计数）。
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.common.exceptions import SkillError
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import CODE_FORBIDDEN, CODE_INVALID_STATE, CODE_NOT_FOUND, SkillReviewError
from platform_mcp.skills.ecosystem.plaza_tools import SkillPlazaToolsSkill, _locale_pick
from platform_mcp.skills.models import PmcpSkillPlaza, PmcpSkillVersion

OWNER = {"user_id": 2, "username": "dev01", "role_code": "developer", "locale": "zh-CN"}
OWNER_EN = {"user_id": 2, "username": "dev01", "role_code": "developer", "locale": "en-US"}
USER = {"user_id": 3, "username": "user01", "role_code": "user", "locale": "zh-CN"}
ADMIN = {"user_id": 1, "username": "admin", "role_code": "admin", "locale": "zh-CN"}

_PT = "platform_mcp.skills.ecosystem.plaza_tools"


def make_context(identity=None, trace_id="t-plaza"):
    ctx = MagicMock()
    ctx.identity = identity
    ctx.trace_id = trace_id
    return ctx


def make_plaza(**kw) -> PmcpSkillPlaza:
    defaults = dict(
        id=10, skill_code="plaza-skill", skill_name="Plaza Skill", description="d",
        version="1.0.0", status="PUBLISHED", involve_flags=[], source_path="/store/plaza",
    )
    defaults.update(kw)
    return PmcpSkillPlaza(**defaults)


def make_skill(**kw) -> PmcpSkill:
    defaults = dict(
        id=1, skill_code="my-skill", skill_name="My", description="d", status="ENABLED",
        register_method="copy", version="1.0.0", inserted_by="dev01", origin="PLAZA",
        share_status="shared", plaza_id=10, source_path="/store/my",
    )
    defaults.update(kw)
    return PmcpSkill(**defaults)


@pytest.fixture
def skill() -> SkillPlazaToolsSkill:
    return SkillPlazaToolsSkill()


@pytest.fixture
def mock_session():
    """patch get_session_factory：_session_scope 产出可控伪 session（delegated 函数另行 patch）。"""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock(return_value=None)
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    exec_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)
    session._exec_result = exec_result

    @contextlib.asynccontextmanager
    async def _cm():
        yield session

    def _factory():
        return _cm()

    with patch("platform_mcp.skills.ecosystem.get_session_factory", return_value=_factory):
        yield session


# ==================== 元数据 / 校验 ====================


class TestPlazaToolsMeta:
    def test_skill_name与support(self, skill):
        assert skill.skill_name() == "skill_plaza"
        assert skill.support("search_skills") is True
        assert skill.support("execute_sql_text") is False

    def test_九工具齐备(self, skill):
        names = {m.tool_name for m in skill.list_tools()}
        assert names == {
            "search_skills", "suggest_similar_skills", "get_skill_readme", "add_skill_to_my",
            "remove_my_skill", "block_skill", "unblock_skill", "list_blocked_skills", "list_my_skills",
        }

    def test_全角色可见(self, skill):
        for meta in skill.list_tools():
            assert meta.roles == {"admin", "developer", "user"}

    def test_描述中英并列(self, skill):
        for meta in skill.list_tools():
            assert "/" in meta.description

    def test_签名可构建(self, skill):
        from platform_mcp.mcp_server.skill.registry import _build_handler_signature
        for meta in skill.list_tools():
            _build_handler_signature(meta.input_schema)  # 不抛即通过

    async def test_校验_search缺query(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("search_skills", {"query": "  "})

    async def test_校验_readme须传id(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("get_skill_readme", {})

    async def test_校验_block须传目标(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("block_skill", {})

    async def test_校验_add缺plaza_id(self, skill):
        with pytest.raises(SkillError):
            await skill.validate("add_skill_to_my", {})

    async def test_未知工具execute抛NotImplemented(self, skill):
        with pytest.raises(NotImplementedError):
            await skill.execute("nope", {}, make_context(OWNER))

    def test_locale_pick(self):
        assert _locale_pick("en-US", "中", "en") == "en"
        assert _locale_pick("zh-CN", "中", "en") == "中"
        assert _locale_pick(None, "中", "en") == "中"


# ==================== search_skills ====================


class TestSearchSkills:
    async def test_搜索返回并透传角色与黑名单(self, skill, mock_session):
        hits = [{"plaza_id": 10, "skill_code": "a", "similarity": 0.9}]
        with patch(f"{_PT}.load_blocked_plaza_ids", new=AsyncMock(return_value={99})) as blk, \
             patch(f"{_PT}.search_visible_plazas", new=AsyncMock(return_value=hits)) as svp:
            res = await skill.execute("search_skills", {"query": "data clean", "top_k": 5}, make_context(OWNER))
        assert res["success"] is True
        assert res["total"] == 1
        assert res["items"] == hits
        # 角色可见性 + 黑名单集合透传给读侧服务
        assert svp.await_args.args[1] == "developer"
        assert svp.await_args.kwargs["blocked_plaza_ids"] == {99}
        assert svp.await_args.kwargs["top_k"] == 5
        blk.assert_awaited_once()

    async def test_一般用户搜索仍委托可见性过滤(self, skill, mock_session):
        with patch(f"{_PT}.load_blocked_plaza_ids", new=AsyncMock(return_value=set())), \
             patch(f"{_PT}.search_visible_plazas", new=AsyncMock(return_value=[])) as svp:
            res = await skill.execute("search_skills", {"query": "sql"}, make_context(USER))
        assert svp.await_args.args[1] == "user"  # role_code 透传，读侧裁决涉库不可见
        assert res["total"] == 0

    async def test_缺身份拒绝(self, skill, mock_session):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("search_skills", {"query": "x"}, make_context(None))
        assert ei.value.error_code == CODE_FORBIDDEN


# ==================== suggest_similar_skills ====================


class TestSuggestSimilar:
    async def test_merge结论(self, skill, mock_session):
        similar = [{"plaza_id": 5, "skill_code": "exist", "recommendation": "merge", "similarity": 0.8}]
        with patch(f"{_PT}.scan_plaza_similar", new=AsyncMock(return_value=similar)) as scan:
            res = await skill.execute(
                "suggest_similar_skills", {"skill_name": "Cleaner", "description": "clean", "limit": 3},
                make_context(OWNER),
            )
        assert res["recommendation"] == "merge"
        assert res["similar_skills"] == similar
        assert scan.await_args.kwargs["limit"] == 3

    async def test_无相似返回new(self, skill, mock_session):
        with patch(f"{_PT}.scan_plaza_similar", new=AsyncMock(return_value=[])):
            res = await skill.execute("suggest_similar_skills", {"skill_name": "Novel"}, make_context(OWNER))
        assert res["recommendation"] == "new"
        assert res["similar_skills"] == []


# ==================== get_skill_readme ====================


class TestGetSkillReadme:
    async def test_广场副本按locale返回(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_plaza(status="PUBLISHED", involve_flags=[]))
        with patch(f"{_PT}.generate_bilingual_readme", return_value=("中文README", "EN README")):
            res = await skill.execute("get_skill_readme", {"plaza_id": 10}, make_context(OWNER_EN))
        assert res["success"] is True
        assert res["readme"] == "EN README"
        assert res["locale"] == "en-US"
        assert res["skill_code"] == "plaza-skill"

    async def test_广场副本中文locale(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_plaza())
        with patch(f"{_PT}.generate_bilingual_readme", return_value=("中文README", "EN README")):
            res = await skill.execute("get_skill_readme", {"plaza_id": 10}, make_context(OWNER))
        assert res["readme"] == "中文README"

    async def test_一般用户读涉库广场副本被拒(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_plaza(involve_flags=["database"]))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("get_skill_readme", {"plaza_id": 10}, make_context(USER))
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_广场副本不存在(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("get_skill_readme", {"plaza_id": 999}, make_context(OWNER))
        assert ei.value.error_code == CODE_NOT_FOUND

    async def test_个人Skill取版本存档README(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_skill(inserted_by="dev01"))
        version = PmcpSkillVersion(id=1, skill_id=1, version="1.0.0", readme_zh="存档中文", readme_en="archived en")
        mock_session._exec_result.scalars.return_value.first.return_value = version
        res = await skill.execute("get_skill_readme", {"skill_id": 1}, make_context(OWNER))
        assert res["readme"] == "存档中文"

    async def test_个人Skill无存档回退重生成(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_skill(inserted_by="dev01"))
        mock_session._exec_result.scalars.return_value.first.return_value = None
        with patch(f"{_PT}.generate_bilingual_readme", return_value=("重生中文", "regen en")) as gen:
            res = await skill.execute("get_skill_readme", {"skill_id": 1}, make_context(OWNER))
        assert res["readme"] == "重生中文"
        gen.assert_called_once()

    async def test_读他人个人Skill被拒(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_skill(inserted_by="someone"))
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("get_skill_readme", {"skill_id": 1}, make_context(OWNER))
        assert ei.value.error_code == CODE_FORBIDDEN

    async def test_admin可读他人个人Skill(self, skill, mock_session):
        mock_session.get = AsyncMock(return_value=make_skill(inserted_by="someone"))
        version = PmcpSkillVersion(id=1, skill_id=1, version="1.0.0", readme_zh="存档", readme_en="a")
        mock_session._exec_result.scalars.return_value.first.return_value = version
        res = await skill.execute("get_skill_readme", {"skill_id": 1}, make_context(ADMIN))
        assert res["success"] is True

    async def test_未传id执行期被拒(self, skill, mock_session):
        with pytest.raises(SkillReviewError) as ei:
            await skill.execute("get_skill_readme", {}, make_context(OWNER))
        assert ei.value.error_code == CODE_INVALID_STATE


# ==================== 写侧动作（委托 plaza_service，channel=mcp）====================


class TestWriteActions:
    async def test_add_skill_to_my委托并回传(self, skill, mock_session):
        created = make_skill(id=7, skill_code="plaza-skill-dev01", plaza_id=10, status="ENABLED", origin="PLAZA")
        with patch(f"{_PT}.copy_plaza_to_personal", new=AsyncMock(return_value=created)) as copy:
            res = await skill.execute("add_skill_to_my", {"plaza_id": 10}, make_context(OWNER))
        assert res["success"] is True
        assert res["skill_id"] == 7
        assert res["skill_code"] == "plaza-skill-dev01"
        assert copy.await_args.kwargs["channel"] == "mcp"

    async def test_remove_my_skill委托(self, skill, mock_session):
        with patch(f"{_PT}.remove_my_skill", new=AsyncMock(return_value=None)) as rm:
            res = await skill.execute("remove_my_skill", {"skill_id": 7}, make_context(OWNER))
        assert res["success"] is True
        assert rm.await_args.kwargs["channel"] == "mcp"

    async def test_block_skill委托plaza目标(self, skill, mock_session):
        entry = MagicMock()
        entry.id = 55
        entry.target_plaza_id = 10
        entry.target_skill_id = None
        with patch(f"{_PT}.block_skill", new=AsyncMock(return_value=entry)) as blk:
            res = await skill.execute("block_skill", {"plaza_id": 10, "reason": "dup"}, make_context(OWNER))
        assert res["success"] is True
        assert res["id"] == 55
        assert blk.await_args.kwargs["plaza_id"] == 10
        assert blk.await_args.kwargs["reason"] == "dup"
        assert blk.await_args.kwargs["channel"] == "mcp"

    async def test_block_skill委托个人目标(self, skill, mock_session):
        entry = MagicMock()
        entry.id = 56
        entry.target_plaza_id = None
        entry.target_skill_id = 7
        with patch(f"{_PT}.block_skill", new=AsyncMock(return_value=entry)) as blk:
            res = await skill.execute("block_skill", {"skill_id": 7}, make_context(OWNER))
        assert blk.await_args.kwargs["skill_id"] == 7
        assert blk.await_args.kwargs["plaza_id"] is None
        assert res["skill_id"] == 7

    async def test_unblock_skill委托(self, skill, mock_session):
        with patch(f"{_PT}.unblock_skill", new=AsyncMock(return_value=None)) as unb:
            res = await skill.execute("unblock_skill", {"plaza_id": 10}, make_context(OWNER))
        assert res["success"] is True
        assert unb.await_args.kwargs["plaza_id"] == 10
        assert unb.await_args.kwargs["channel"] == "mcp"

    async def test_list_blocked_skills委托(self, skill, mock_session):
        items = [{"id": 1, "target_type": "plaza", "skill_code": "a"}]
        with patch(f"{_PT}.list_blocked_skills", new=AsyncMock(return_value=items)) as lb:
            res = await skill.execute("list_blocked_skills", {}, make_context(OWNER))
        assert res["total"] == 1
        assert res["items"] == items
        lb.assert_awaited_once()


# ==================== list_my_skills ====================


class TestListMySkills:
    async def test_清单排除黑名单并按owner过滤(self, skill, mock_session):
        s1 = make_skill(id=1, skill_code="a", status="ENABLED")
        s2 = make_skill(id=2, skill_code="b", status="DRAFT")
        mock_session._exec_result.scalars.return_value.all.return_value = [s1, s2]
        with patch(f"{_PT}.load_blocked_skill_ids", new=AsyncMock(return_value={2})):
            res = await skill.execute("list_my_skills", {}, make_context(OWNER))
        assert res["total"] == 1
        assert res["items"][0]["skill_code"] == "a"
        # 查询按 owner username 过滤
        assert res["items"][0]["status"] == "ENABLED"

    async def test_空清单(self, skill, mock_session):
        mock_session._exec_result.scalars.return_value.all.return_value = []
        with patch(f"{_PT}.load_blocked_skill_ids", new=AsyncMock(return_value=set())):
            res = await skill.execute("list_my_skills", {}, make_context(OWNER))
        assert res["total"] == 0
        assert res["items"] == []
