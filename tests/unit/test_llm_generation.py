"""单元测试 — 本地生成素材构造 + 产物重放校验 + 分享迭代差异（V3.0 M4.2/M4.3，架构 §19.5.6）

覆盖：
- build_file_tree / read_package_skill_md（文件树与包内原文读取，大小写兜底）；
- 三类 prompt 构造（报告/README/差异描述，中英双语，事实拼接口径）；
- replay_validate_artifact（F-35/F-36 重放校验）：干净产物通过、🔴 严重命中拒绝、
  🟡 警告透传接受、SKILL.md 原文违规不计数、未知类型拒绝；
- compute_text_diff / compute_semantic_similarity（降级哈希）/ template_diff_description；
- build_iteration_diff_material / build_iteration_diff（模型路径留痕 model + 性能提示；
  失败模板兜底 template 无提示；任一侧失败整体走模板，避免中英来源混杂）。

重放校验走真实审计引擎（audit_skill_package + check_sanitization），不 mock；
llm_generate 在 generation 模块引用点 patch。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from platform_mcp.skills.audit.models import AuditResult, AuditRuleResult, Severity
from platform_mcp.skills.llm import LlmGenerationError, PERFORMANCE_HINT_ZH
from platform_mcp.skills.llm.generation import (
    ARTIFACT_FILENAMES,
    build_diff_prompt,
    build_file_tree,
    build_iteration_diff,
    build_iteration_diff_material,
    build_readme_prompt,
    build_report_prompt,
    compute_semantic_similarity,
    compute_text_diff,
    read_package_skill_md,
    replay_validate_artifact,
    template_diff_description,
)

_CLEAN_SKILL_MD = """---
name: demo-skill
description: 演示 Skill
---

# Demo

使用说明。
"""

_CLEAN_REPORT = """# Skill 审核报告

| 规则 | 结果 |
| --- | --- |
| R1-01 | 通过 |

结论：全部通过。
"""


def _audit(passed: bool = True) -> AuditResult:
    ar = AuditResult(skill_name="demo")
    ar.results = [
        AuditRuleResult(rule_id="R4-01", severity=Severity.CRITICAL, passed=passed,
                        description="硬编码密码", suggestion="改用环境变量"),
    ]
    ar.compute_counts()
    return ar


# ==================== 文件树 / 包内原文 ====================


class TestFileTreeAndRead:
    def test_文件树包含目录与文件(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "SKILL.md").write_text("# d", encoding="utf-8")
        tree = build_file_tree(tmp_path)
        assert "sub/" in tree
        assert "sub/a.py" in tree
        assert "SKILL.md" in tree

    def test_文件树超限截断(self, tmp_path):
        for i in range(10):
            (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
        tree = build_file_tree(tmp_path, max_entries=3)
        assert "…（截断）" in tree
        assert "f9.py" not in tree

    def test_无目录返回空串(self):
        assert build_file_tree(None) == ""
        assert build_file_tree("Z:/nope") == ""

    def test_读SKILLmd标准名(self, tmp_path):
        (tmp_path / "SKILL.md").write_text(_CLEAN_SKILL_MD, encoding="utf-8")
        assert read_package_skill_md(str(tmp_path)) == _CLEAN_SKILL_MD

    def test_读SKILLmd大小写兜底(self, tmp_path):
        (tmp_path / "skill.MD").write_text("lower", encoding="utf-8")
        assert read_package_skill_md(str(tmp_path)) == "lower"

    def test_缺失或非目录返回空串(self, tmp_path):
        assert read_package_skill_md(None) == ""
        assert read_package_skill_md("") == ""
        assert read_package_skill_md("Z:/nope-dir") == ""


# ==================== prompt 构造 ====================


class TestPrompts:
    def test_报告prompt中文拼事实(self):
        prompt = build_report_prompt(
            skill_code="demo-skill", skill_name="Demo", description="演示",
            version="0.2.0", audit_result=_audit(passed=False),
            similar_skills=[{"skill_name": "Old", "skill_code": "old", "similarity": 0.92,
                             "recommendation": "merge"}],
            language="zh",
        )
        assert "demo-skill" in prompt and "v0.2.0" in prompt
        assert "R4-01" in prompt and "硬编码密码" in prompt
        assert "0.92" in prompt and "合并" in prompt
        assert "# Skill 审核报告" in prompt

    def test_报告prompt英文与空相似兜底(self):
        prompt = build_report_prompt(
            skill_code="demo-skill", skill_name="Demo", description=None,
            version="0.1.0", audit_result=_audit(passed=True),
            similar_skills=None, language="en",
        )
        assert "English" in prompt
        assert "未发现相似 Skill" in prompt  # 中文事实段兜底文案
        assert "（无违规命中）" in prompt

    def test_READMEprompt含文件树与原文(self):
        prompt = build_readme_prompt(
            skill_name="Demo", description="d", skill_md=_CLEAN_SKILL_MD,
            file_tree="SKILL.md\nsub/a.py", version="0.1.0", language="zh",
        )
        assert "Demo" in prompt and "SKILL.md 内容" in prompt
        assert "sub/a.py" in prompt

    def test_READMEprompt英文与空素材兜底(self):
        prompt = build_readme_prompt(
            skill_name="Demo", description=None, skill_md="", file_tree="",
            version="0.1.0", language="en",
        )
        assert "（无源码包）" in prompt and "（空）" in prompt

    def test_差异prompt拼统计与相似度(self):
        stats = compute_text_diff("# 本地\nA", "# 广场\nA\nB")
        prompt = build_diff_prompt(
            skill_name="Demo", diff_stats=stats, similarity=0.87,
            unified_diff=stats["unified_diff"], language="zh",
        )
        assert "87.0%" in prompt
        assert "本地行数：2" in prompt
        assert "+1" in prompt
        assert "iterate" in prompt

    def test_差异prompt英文(self):
        stats = compute_text_diff("a", "b")
        prompt = build_diff_prompt(
            skill_name="Demo", diff_stats=stats, similarity=0.5,
            unified_diff=stats["unified_diff"], language="en",
        )
        assert "English" in prompt


# ==================== 重放校验（F-35 / F-36）====================


class TestReplayValidate:
    def test_干净产物通过(self):
        passed, violations = replay_validate_artifact(
            artifact_type="report", content=_CLEAN_REPORT,
            skill_md=_CLEAN_SKILL_MD, skill_name="demo",
        )
        assert passed is True
        assert violations == []

    def test_严重命中拒绝(self):
        bad = _CLEAN_REPORT + "\n配置：password = \"hunter2secret\"\n"
        passed, violations = replay_validate_artifact(
            artifact_type="report", content=bad,
            skill_md=_CLEAN_SKILL_MD, skill_name="demo",
        )
        assert passed is False
        ids = {v["rule_id"] for v in violations}
        assert "R4-01" in ids
        hit = next(v for v in violations if v["rule_id"] == "R4-01")
        assert hit["severity"] == "critical"
        assert hit["line_number"] >= 1

    def test_警告透传接受(self):
        # R3-02（app.run 监听，WARNING）不触发任何 critical → 接受但留痕
        warn = _CLEAN_REPORT + "\n启动：app.run(host='0.0.0.0')\n"
        passed, violations = replay_validate_artifact(
            artifact_type="readme", content=warn,
            skill_md=_CLEAN_SKILL_MD, skill_name="demo",
        )
        assert passed is True  # 🟡 不阻断
        assert any(v["rule_id"] == "R3-02" and v["severity"] == "warning" for v in violations)

    def test_SKILLmd原文违规不计数(self):
        dirty_md = "---\nname: d\ndescription: x\n---\n\napi_key = \"sk-1234567890abcdef\"\n"
        passed, violations = replay_validate_artifact(
            artifact_type="report", content=_CLEAN_REPORT,
            skill_md=dirty_md, skill_name="demo",
        )
        assert passed is True
        assert violations == []  # 原文 R4-01 命中被 file_path 过滤

    def test_readme类型文件名对齐(self):
        bad_readme = "# README\n\n下载：requests.get(\"https://x\")\n"
        passed, violations = replay_validate_artifact(
            artifact_type="readme", content=bad_readme,
            skill_md=_CLEAN_SKILL_MD, skill_name="demo",
        )
        assert passed is False
        assert any(v["rule_id"] == "R3-01" for v in violations)

    def test_未知类型拒绝(self):
        with pytest.raises(ValueError, match="未知产物类型"):
            replay_validate_artifact(
                artifact_type="poem", content="x",
                skill_md=_CLEAN_SKILL_MD, skill_name="demo",
            )

    def test_产物文件名映射(self):
        assert ARTIFACT_FILENAMES == {"readme": "README.md", "report": "REVIEW_REPORT.md"}


# ==================== 差异计算与模板描述 ====================


class TestDiffCompute:
    def test_相同文本无差异(self):
        stats = compute_text_diff("# a\n# b", "# a\n# b")
        assert stats["identical"] is True
        assert stats["added_lines"] == 0 and stats["removed_lines"] == 0

    def test_增删统计与unified头(self):
        stats = compute_text_diff("# 本地\nkeep\nold1", "# 广场\nkeep\nnew1\nnew2")
        assert stats["identical"] is False
        assert stats["added_lines"] == 3  # # 广场 / new1 / new2（首行替换计 +1）
        assert stats["removed_lines"] == 2  # # 本地 / old1
        assert stats["local_lines"] == 3 and stats["plaza_lines"] == 4
        assert "--- local/SKILL.md" in stats["unified_diff"]
        assert "+++ plaza/SKILL.md" in stats["unified_diff"]

    async def test_语义相似度相同为一(self):
        sim = await compute_semantic_similarity("Oracle 备份恢复", "Oracle 备份恢复")
        assert sim == pytest.approx(1.0)

    async def test_语义相似度不同低于相同(self):
        same = await compute_semantic_similarity("数据库 备份", "数据库 备份")
        diff = await compute_semantic_similarity("数据库 备份", "前端 页面 渲染")
        assert diff < same

    def test_模板描述一致分支(self):
        stats = compute_text_diff("x", "x")
        zh = template_diff_description(skill_name="Demo", diff_stats=stats, similarity=1.0, language="zh")
        en = template_diff_description(skill_name="Demo", diff_stats=stats, similarity=1.0, language="en")
        assert "内容一致" in zh
        assert "identical" in en

    def test_模板描述差异分支双语(self):
        stats = compute_text_diff("a\nb", "a\nc\nd")
        zh = template_diff_description(skill_name="Demo", diff_stats=stats, similarity=0.75, language="zh")
        en = template_diff_description(skill_name="Demo", diff_stats=stats, similarity=0.75, language="en")
        assert "新增 2 行、删除 1 行" in zh and "75.0%" in zh
        assert "+2 / -1" in en and "75.0%" in en

    async def test_差异素材字段齐全(self):
        material = await build_iteration_diff_material("# a\nb", "# a\nc")
        assert {"unified_diff", "local_lines", "plaza_lines", "added_lines",
                "removed_lines", "identical", "similarity"} <= set(material)
        assert 0.0 <= material["similarity"] <= 1.0


# ==================== 差异全量（模型 / 模板路径）====================


class TestBuildIterationDiff:
    async def test_模型路径留痕与性能提示(self):
        with patch("platform_mcp.skills.llm.generation.llm_generate",
                   new=AsyncMock(side_effect=["中文摘要", "english summary"])) as gen:
            result = await build_iteration_diff(skill_name="Demo", local_md="# a", plaza_md="# b")
        assert result["generated_by"] == "model"
        assert result["description_zh"] == "中文摘要"
        assert result["description_en"] == "english summary"
        assert result["performance_hint_zh"] == PERFORMANCE_HINT_ZH
        assert result["performance_hint_en"] is not None
        assert gen.await_count == 2  # 双语各一次

    async def test_模型缺失模板兜底(self):
        with patch("platform_mcp.skills.llm.generation.llm_generate",
                   new=AsyncMock(side_effect=LlmGenerationError("不可用"))):
            result = await build_iteration_diff(skill_name="Demo", local_md="# a\nx", plaza_md="# b\ny")
        assert result["generated_by"] == "template"
        assert "差异" in result["description_zh"]
        assert "differ" in result["description_en"]
        assert result["performance_hint_zh"] is None
        assert result["performance_hint_en"] is None

    async def test_任一侧失败整体走模板(self):
        # zh 成功、en 抛错 → 整体模板（口径一致，避免中英来源混杂）
        with patch("platform_mcp.skills.llm.generation.llm_generate",
                   new=AsyncMock(side_effect=["中文摘要", LlmGenerationError("boom")])):
            result = await build_iteration_diff(skill_name="Demo", local_md="# a", plaza_md="# b")
        assert result["generated_by"] == "template"
        assert result["description_zh"].startswith("「Demo」")
