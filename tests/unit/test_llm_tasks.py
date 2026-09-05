"""单元测试 — 版本存档本地模型升级任务（V3.0 M4.2，架构 §19.5.6 / 计划 M4.2、F-35、VNF-01）

覆盖 upgrade_version_artifacts 各分支：
- 本地模型未就绪快速返回 False（不建会话）；
- Skill 不存在 / 无存档行 / 非 template 存档（model|external）→ 幂等跳过 False；
- 成功升级：三项模型产物入档（report_zh/report_en/readme_en）、readme_zh 恒保留存档现值
  （包内用户原文优先契约）、generated_by=model、commit、artifact_upgrade 审计；
- 重放校验 🔴 命中整体放弃（保留模板存档，archive 不被调用）；
- 生成异常全捕获返回 False（VNF-01 后台任务不阻塞主链路）。

用轻量 FakeSession（get/execute/commit）+ patch get_session_factory，依赖
（llm_available / llm_generate / scan_plaza_similar / archive_skill_version /
write_audit_log）在 tasks 模块引用点替换；重放校验走真实引擎（干净产物可通过）。
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.skills.llm.tasks import upgrade_version_artifacts
from platform_mcp.skills.models import PmcpSkillVersion


class FakeSession:
    """轻量伪 AsyncSession：get 分派 skill，execute 分派版本存档查询。"""

    def __init__(self, skill=None, version_row=None) -> None:
        self.skill = skill
        self.version_row = version_row
        self.commit_count = 0

    async def get(self, model, pk):
        if model is PmcpSkill and pk == (self.skill.id if self.skill else 1):
            return self.skill
        return None

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.version_row
        return result

    async def commit(self) -> None:
        self.commit_count += 1


def make_skill(**kw) -> PmcpSkill:
    defaults = dict(
        id=1, skill_code="demo-skill", skill_name="Demo", description="演示",
        status="DRAFT", register_method="upload", tool_count=0, version="0.1.0",
        source_path="/store/demo", source_checksum="a" * 64, inserted_by="dev01",
        origin="ORIGINAL", share_status="unshared", plaza_id=None, review_comment=None,
        audit_status="passed", audit_result={"total_rules": 14, "critical_count": 0},
    )
    defaults.update(kw)
    return PmcpSkill(**defaults)


def make_version(**kw) -> PmcpSkillVersion:
    defaults = dict(
        skill_id=1, version="0.1.0", checksum="a" * 64,
        readme_zh="包内中文 README 原文", readme_en="old en",
        report_zh="旧中文报告", report_en="old en report",
        audit_snapshot={"total_rules": 14, "critical_count": 0},
        generated_by="template", inserted_by="dev01", updated_by="dev01",
    )
    defaults.update(kw)
    return PmcpSkillVersion(**defaults)


@contextlib.contextmanager
def _patched_session(session: FakeSession):
    @contextlib.asynccontextmanager
    async def _cm():
        yield session

    with patch("platform_mcp.skills.llm.tasks.get_session_factory", return_value=lambda: _cm()):
        yield session


_CLEAN_DOC = "# 模型产物\n\n全部规则通过，无违规命中。\n"


class TestUpgradeVersionArtifacts:
    async def test_模型未就绪快速返回(self):
        with patch("platform_mcp.skills.llm.tasks.llm_available", return_value=False), \
                patch("platform_mcp.skills.llm.tasks.get_session_factory") as factory:
            assert await upgrade_version_artifacts(1, "0.1.0") is False
        factory.assert_not_called()

    async def test_skill不存在跳过(self):
        with _patched_session(FakeSession(skill=None)):
            assert await upgrade_version_artifacts(999, "0.1.0") is False

    async def test_无存档行幂等跳过(self):
        with _patched_session(FakeSession(skill=make_skill(), version_row=None)), \
                patch("platform_mcp.skills.llm.tasks.llm_available", return_value=True):
            assert await upgrade_version_artifacts(1, "0.1.0") is False

    async def test_已升级存档幂等跳过(self):
        session = FakeSession(skill=make_skill(), version_row=make_version(generated_by="model"))
        with _patched_session(session), \
                patch("platform_mcp.skills.llm.tasks.llm_available", return_value=True), \
                patch("platform_mcp.skills.llm.tasks.llm_generate", new=AsyncMock()) as gen:
            assert await upgrade_version_artifacts(1, "0.1.0") is False
        gen.assert_not_awaited()

    async def test_外部产物存档不覆盖(self):
        session = FakeSession(skill=make_skill(), version_row=make_version(generated_by="external"))
        with _patched_session(session), \
                patch("platform_mcp.skills.llm.tasks.llm_available", return_value=True), \
                patch("platform_mcp.skills.llm.tasks.llm_generate", new=AsyncMock()) as gen:
            assert await upgrade_version_artifacts(1, "0.1.0") is False
        gen.assert_not_awaited()

    async def test_成功升级三项产物且保留中文README(self):
        session = FakeSession(skill=make_skill(), version_row=make_version())
        archive = AsyncMock()
        audit_log = AsyncMock()
        prompts: list[str] = []

        async def _fake_generate(prompt, **kw):
            prompts.append(prompt)
            return _CLEAN_DOC

        with _patched_session(session), \
                patch("platform_mcp.skills.llm.tasks.llm_available", return_value=True), \
                patch("platform_mcp.skills.llm.tasks.llm_generate", side_effect=_fake_generate), \
                patch("platform_mcp.skills.llm.tasks.scan_plaza_similar", new=AsyncMock(return_value=[])), \
                patch("platform_mcp.skills.llm.tasks.archive_skill_version", archive), \
                patch("platform_mcp.skills.llm.tasks.write_audit_log", audit_log):
            assert await upgrade_version_artifacts(1, "0.1.0", operator="dev01") is True

        assert len(prompts) == 3  # report_zh / report_en / readme_en
        assert session.commit_count == 1
        # archive 参数口径：三项模型产物 + readme_zh 保留现值 + generated_by=model
        kwargs = archive.await_args.kwargs
        assert kwargs["readme_zh"] == "包内中文 README 原文"
        assert kwargs["readme_en"] == _CLEAN_DOC
        assert kwargs["report_zh"] == _CLEAN_DOC
        assert kwargs["report_en"] == _CLEAN_DOC
        assert kwargs["generated_by"] == "model"
        assert kwargs["checksum"] == "a" * 64
        # 审计留痕
        assert audit_log.await_count == 1
        audit_kwargs = audit_log.await_args.kwargs
        assert audit_kwargs["extra_data"]["action"] == "artifact_upgrade"
        assert audit_kwargs["extra_data"]["channel"] == "web-background"
        assert audit_kwargs["operator"] == "dev01"

    async def test_重放校验严重命中整体放弃(self):
        session = FakeSession(skill=make_skill(), version_row=make_version())
        archive = AsyncMock()
        bad_doc = _CLEAN_DOC + "\npassword = \"hunter2secret\"\n"

        async def _fake_generate(prompt, **kw):
            return bad_doc

        with _patched_session(session), \
                patch("platform_mcp.skills.llm.tasks.llm_available", return_value=True), \
                patch("platform_mcp.skills.llm.tasks.llm_generate", side_effect=_fake_generate), \
                patch("platform_mcp.skills.llm.tasks.scan_plaza_similar", new=AsyncMock(return_value=[])), \
                patch("platform_mcp.skills.llm.tasks.archive_skill_version", archive):
            assert await upgrade_version_artifacts(1, "0.1.0") is False
        archive.assert_not_awaited()
        assert session.version_row.generated_by == "template"  # 模板存档保留

    async def test_生成异常全捕获返回False(self):
        session = FakeSession(skill=make_skill(), version_row=make_version())
        with _patched_session(session), \
                patch("platform_mcp.skills.llm.tasks.llm_available", return_value=True), \
                patch("platform_mcp.skills.llm.tasks.llm_generate",
                      new=AsyncMock(side_effect=RuntimeError("boom"))), \
                patch("platform_mcp.skills.llm.tasks.scan_plaza_similar", new=AsyncMock(return_value=[])):
            assert await upgrade_version_artifacts(1, "0.1.0") is False
        assert session.commit_count == 0
