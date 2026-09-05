"""本地生成素材构造 + 产物重放校验 + 分享迭代差异描述（V3.0 M4.2/M4.3，架构 §19.5.6）

Web 端本地生成通道（Qwen3-4B）输入素材与产物校验（F-35），MCP 外部通道（glm 5.3）回传产物
复用同一重放校验（F-36）：

- **prompt 构造**：中英审核报告 / 英文 README / 分享迭代差异描述，输入 = 审计结果 + SKILL.md +
  文件树 + 版本对比素材（计划 M4.2 口径），只陈述事实、禁止编造；
- **重放校验** :func:`replay_validate_artifact`：产物写临时目录（连同包内 SKILL.md 原文）→
  重放 14 条审计 + 脱敏校验，只统计产物文件自身命中的违规（SKILL.md 原文已知违规不计数），
  🔴 严重命中拒绝（与广场审核硬门禁同口径）；
- **差异描述**（M4.3）：本地 SKILL.md vs 广场快照 SKILL.md 的行级 diff（difflib）+ 语义相似度
  （BGE-M3 / 降级哈希余弦）→ 模型优先生成双语摘要，失败走确定性模板兜底。

产物来源留痕（generated_by）与性能提示文案见 :mod:`platform_mcp.skills.llm`。
"""

from __future__ import annotations

import difflib
import shutil
import tempfile
from pathlib import Path

from platform_mcp.skills.audit.engine import audit_skill_package
from platform_mcp.skills.audit.models import AuditResult, Severity
from platform_mcp.skills.audit.sanitizer import check_sanitization
from platform_mcp.skills.embedding import cosine_similarity, embed_text
from platform_mcp.skills.llm import (
    GENERATED_BY_MODEL,
    PERFORMANCE_HINT_EN,
    PERFORMANCE_HINT_ZH,
    LlmGenerationError,
    llm_generate,
)
from platform_mcp.skills.versioning import GENERATED_BY_TEMPLATE

#: 产物类型 → 重放校验临时文件名（产物恒为根级 Markdown；file_path 按此过滤产物自身违规）
ARTIFACT_FILENAMES: dict[str, str] = {
    "readme": "README.md",
    "report": "REVIEW_REPORT.md",
}

#: prompt 输入素材截断（n_ctx=8192 下控制 prompt 体积；生成事实性文本无需全量原文）
_MAX_SKILL_MD_LINES = 300
_MAX_FAILED_RULES = 40
_MAX_DIFF_LINES = 120
_MAX_TREE_ENTRIES = 80


def build_file_tree(skill_dir: str | Path | None, *, max_entries: int = _MAX_TREE_ENTRIES) -> str:
    """包内文件树（相对路径 + 目录标注；空目录/超限截断；无源码包返回空串）。"""
    text = str(skill_dir or "").strip()
    if not text:
        return ""
    root = Path(text)
    if not root.is_dir():
        return ""
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            entries.append(f"{rel}/")
        else:
            entries.append(rel)
        if len(entries) >= max_entries:
            entries.append("…（截断）")
            break
    return "\n".join(entries)


def read_package_skill_md(source_path: str | None) -> str:
    """读包内 SKILL.md 原文（大小写不敏感兜底，与 upload._parse_skill_md 同口径）。

    无源码包/文件缺失/读盘失败返回空串（差异比较、prompt 构造按无原文口径降级）。
    """
    text = str(source_path or "").strip()
    if not text:
        return ""
    root = Path(text)
    if not root.is_dir():
        return ""
    target = root / "SKILL.md"
    if not target.exists():
        for item in root.iterdir():
            if item.is_file() and item.name.upper() == "SKILL.MD":
                target = item
                break
        else:
            return ""
    try:
        return target.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - 读盘失败按无原文降级
        return ""


def _truncate_lines(text_value: str, limit: int) -> str:
    lines = text_value.splitlines()
    if len(lines) <= limit:
        return text_value
    return "\n".join(lines[:limit]) + "\n…（截断）"


def _language_name(language: str) -> str:
    return "English" if language == "en" else "中文"


# ==================== prompt 构造（M4.2：输入=审计结果+SKILL.md+文件树）====================


def build_report_prompt(
    *,
    skill_code: str,
    skill_name: str,
    description: str | None,
    version: str,
    audit_result: AuditResult,
    similar_skills: list[dict] | None,
    language: str,
) -> str:
    """中英审核报告生成 prompt（双语各一次调用；事实=审计统计/命中明细/广场比对结论）。"""
    failed = [r for r in audit_result.results if not r.passed]
    failed_lines = (
        "\n".join(
            f"- {r.rule_id} [{r.severity.value}] {r.description or ''} → {r.suggestion or ''}"
            for r in failed[:_MAX_FAILED_RULES]
        )
        or "（无违规命中）"
    )
    similar = similar_skills or []
    similar_lines = (
        "\n".join(
            f"- {s.get('skill_name')}（{s.get('skill_code')}）相似度 {s.get('similarity')}，"
            f"建议 {'合并' if s.get('recommendation') == 'merge' else '新增'}"
            for s in similar
        )
        or "（未发现相似 Skill，建议新增）"
    )
    passed_text = "通过" if audit_result.passed else "未通过（存在严重违规，阻止入广场）"
    if language == "en":
        header = (
            "You are a review-report writer for the Skill platform. Write a Markdown review report "
            f"in {_language_name(language)} strictly from the facts below.\n\n"
            "Rules: 1) never invent rule ids, numbers or conclusions; 2) include sections: Basic Info, "
            "Compliance Audit (14 rules), Plaza Comparison; 3) objective and formal tone, tables for hits; "
            "4) output the report body only (start with '# Skill Review Report'), no explanations or fences."
        )
    else:
        header = (
            f"你是 Skill 平台的审核报告撰写助手，请严格根据以下事实用{_language_name(language)}撰写 "
            "Markdown 审核报告。\n\n"
            "要求：1) 只陈述给定事实，不得编造规则编号、数值或结论；2) 结构包含：基本信息、合规审计"
            "（14 条规则命中情况）、广场比对结论三部分；3) 语气客观正式，命中明细用表格；4) 直接输出报告"
            "正文（以「# Skill 审核报告」开头），不要解释或代码围栏。"
        )
    facts = (
        f"\n\n审计事实 / Audit facts：\n"
        f"- Skill 编码：{skill_code}\n"
        f"- Skill 名称：{skill_name}\n"
        f"- 版本：v{version}\n"
        f"- 描述：{description or '（无）'}\n"
        f"- 审计统计：总规则数 {audit_result.total_rules}；🔴 严重 {audit_result.critical_count}；"
        f"🟡 警告 {audit_result.warning_count}；🟢 建议 {audit_result.suggestion_count}；"
        f"结论：{passed_text}\n"
        f"- 命中明细：\n{failed_lines}\n"
        f"- 广场比对：\n{similar_lines}"
    )
    return header + facts


def build_readme_prompt(
    *,
    skill_name: str,
    description: str | None,
    skill_md: str,
    file_tree: str,
    version: str,
    language: str,
) -> str:
    """README 生成 prompt（英文 README 为主——中文 README 优先保留用户包内原文）。"""
    skill_md_text = _truncate_lines(skill_md, _MAX_SKILL_MD_LINES)
    if language == "en":
        header = (
            f"Write a Markdown README in {_language_name(language)} for the Skill below.\n\n"
            "Rules: 1) use only the given information, never invent features; 2) sections: title, "
            "overview, file structure, quick start, usage; 3) output the README body only, no fences."
        )
    else:
        header = (
            f"请为下面的 Skill 用{_language_name(language)}撰写 Markdown README。\n\n"
            "要求：1) 只使用给定信息，不得编造功能；2) 结构：标题、简介、目录结构、快速开始、"
            "使用说明；3) 直接输出 README 正文，不要代码围栏。"
        )
    facts = (
        f"\n\n信息 / Info：\n"
        f"- Skill 名称：{skill_name}\n"
        f"- 版本：v{version}\n"
        f"- 描述：{description or '（无）'}\n"
        f"- 文件树：\n{file_tree or '（无源码包）'}\n"
        f"- SKILL.md 内容：\n{skill_md_text or '（空）'}"
    )
    return header + facts


def build_diff_prompt(
    *,
    skill_name: str,
    diff_stats: dict,
    similarity: float,
    unified_diff: str,
    language: str,
) -> str:
    """分享迭代差异描述 prompt（素材=行级 diff 统计 + 语义相似度 + unified diff 摘录）。"""
    diff_text = _truncate_lines(unified_diff, _MAX_DIFF_LINES)
    if language == "en":
        header = (
            "The admin merged the local Skill into an existing plaza skill. Write a short diff summary "
            f"in {_language_name(language)} to help the owner decide between 'iterate' (accept the merge, "
            "overwrite local) and 'keep' (keep local).\n\n"
            "Rules: 1) describe the differences objectively from the given stats and diff, never invent; "
            "2) 3-6 sentences: overall scale first, then the main direction of changes if readable; "
            "3) output the summary text only."
        )
    else:
        header = (
            "admin 已将本地 Skill 合并到广场已有版本。请用"
            f"{_language_name(language)}为 Skill 作者写一段差异摘要，帮助其决定「采纳合并（iterate，"
            "以广场内容覆盖本地）」还是「保留本地（keep，忽略本次迭代）」。\n\n"
            "要求：1) 基于给定的 diff 统计与语义相似度客观描述差异，不编造；2) 3~6 句话，先总述差异"
            "规模，再点出主要变化方向（若 diff 可读）；3) 直接输出摘要文本。"
        )
    facts = (
        f"\n\n素材 / Material：\n"
        f"- Skill 名称：{skill_name}\n"
        f"- 语义相似度：{similarity:.1%}\n"
        f"- 本地行数：{diff_stats.get('local_lines', 0)}；广场行数：{diff_stats.get('plaza_lines', 0)}；"
        f"新增行：+{diff_stats.get('added_lines', 0)}；删除行：-{diff_stats.get('removed_lines', 0)}\n"
        f"- unified diff：\n{diff_text or '（无差异）'}"
    )
    return header + facts


# ==================== 重放校验（F-35 输出校验 / F-36 外部产物回传校验）====================


def replay_validate_artifact(
    *,
    artifact_type: str,
    content: str,
    skill_md: str,
    skill_name: str,
) -> tuple[bool, list[dict]]:
    """产物重放校验：临时目录写包内 SKILL.md 原文 + 产物文件 → 重放 14 条审计 + 脱敏校验。

    只统计**产物文件自身**命中的违规（按 ``file_path`` 过滤；SKILL.md 原文已知违规不计数——
    草稿期审计已单独反馈）；🔴 严重命中 → 拒绝（与广场审核硬门禁同口径），🟡/🟢 透传接受
    （随返回清单供调用方留痕展示）。返回 ``(passed, violations)``。
    """
    filename = ARTIFACT_FILENAMES.get(artifact_type)
    if not filename:
        raise ValueError(f"未知产物类型: {artifact_type}（值域 readme|report）")
    root = Path(tempfile.mkdtemp(prefix="skill_artifact_replay_"))
    try:
        (root / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (root / filename).write_text(content, encoding="utf-8")
        audit = audit_skill_package(root, skill_name)
        for r in check_sanitization(root, skill_name):
            if not r.passed:
                audit.results.append(r)
        violations: list[dict] = []
        passed = True
        for r in audit.results:
            if r.passed:
                continue
            path = (r.file_path or "").replace("\\", "/")
            if path != filename:
                continue  # 仅产物文件自身（SKILL.md 原文违规不计数）
            violations.append(
                {
                    "rule_id": r.rule_id,
                    "severity": r.severity.value,
                    "description": r.description,
                    "suggestion": r.suggestion,
                    "line_number": r.line_number,
                }
            )
            if r.severity == Severity.CRITICAL:
                passed = False
        return passed, violations
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ==================== 分享迭代差异（M4.3：行级 diff + 语义相似度 + 描述）====================


def compute_text_diff(local_md: str, plaza_md: str) -> dict:
    """本地/广场 SKILL.md 行级 diff（difflib unified）与行统计（纯同步，无 IO）。"""
    local_lines = local_md.splitlines()
    plaza_lines = plaza_md.splitlines()
    unified = list(
        difflib.unified_diff(
            local_lines, plaza_lines, fromfile="local/SKILL.md", tofile="plaza/SKILL.md", lineterm=""
        )
    )
    added = sum(1 for line in unified if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in unified if line.startswith("-") and not line.startswith("---"))
    return {
        "unified_diff": "\n".join(unified),
        "local_lines": len(local_lines),
        "plaza_lines": len(plaza_lines),
        "added_lines": added,
        "removed_lines": removed,
        "identical": added == 0 and removed == 0,
    }


async def compute_semantic_similarity(local_md: str, plaza_md: str) -> float:
    """本地/广场文本语义相似度（BGE-M3 / 降级哈希余弦，0~1）。"""
    vec_local = await embed_text(local_md or " ")
    vec_plaza = await embed_text(plaza_md or " ")
    return cosine_similarity(vec_local, vec_plaza)


def template_diff_description(*, skill_name: str, diff_stats: dict, similarity: float, language: str) -> str:
    """确定性模板差异摘要（模型缺失/超时/校验失败兜底；双语）。"""
    added = int(diff_stats.get("added_lines", 0))
    removed = int(diff_stats.get("removed_lines", 0))
    if diff_stats.get("identical"):
        zh = f"「{skill_name}」本地版本与广场版本内容一致（无行级差异，语义相似度 {similarity:.1%}）。"
        en = (
            f"The local version of '{skill_name}' is identical to the plaza version "
            f"(no line-level differences; semantic similarity {similarity:.1%})."
        )
    else:
        zh = (
            f"「{skill_name}」本地版本与广场版本存在行级差异：新增 {added} 行、删除 {removed} 行"
            f"（本地 {diff_stats.get('local_lines', 0)} 行 vs 广场 {diff_stats.get('plaza_lines', 0)} 行），"
            f"语义相似度 {similarity:.1%}。选择「采纳合并」将以广场内容覆盖本地；"
            f"选择「保留本地」将忽略本次迭代。差异明细见 unified diff。"
        )
        en = (
            f"'{skill_name}' differs between the local and plaza versions: +{added} / -{removed} lines "
            f"(local {diff_stats.get('local_lines', 0)} vs plaza {diff_stats.get('plaza_lines', 0)}), "
            f"semantic similarity {similarity:.1%}. 'Iterate' overwrites local with the plaza content; "
            f"'keep' ignores this iteration. See the unified diff for details."
        )
    return en if language == "en" else zh


async def build_iteration_diff_material(local_md: str, plaza_md: str) -> dict:
    """差异素材（行级 diff + 语义相似度，不含生成描述）——MCP 通道返回给外部大模型（glm 5.3）用。"""
    stats = compute_text_diff(local_md, plaza_md)
    similarity = await compute_semantic_similarity(local_md, plaza_md)
    return {**stats, "similarity": round(similarity, 3)}


async def build_iteration_diff(*, skill_name: str, local_md: str, plaza_md: str) -> dict:
    """Web 通道差异全量结果：素材 + 双语描述（本地 Qwen3 优先，失败模板兜底）+ 性能提示。

    返回含 ``generated_by``（model|template）与 ``performance_hint``（M4.4 全程提示）；
    模型双语各生成一次（单槽排队），任一失败整体走模板（口径一致，避免中英混杂来源）。
    """
    material = await build_iteration_diff_material(local_md, plaza_md)
    similarity = float(material["similarity"])
    desc_zh = desc_en = ""
    generated_by = GENERATED_BY_TEMPLATE
    try:
        prompt_zh = build_diff_prompt(
            skill_name=skill_name, diff_stats=material, similarity=similarity,
            unified_diff=material["unified_diff"], language="zh",
        )
        prompt_en = build_diff_prompt(
            skill_name=skill_name, diff_stats=material, similarity=similarity,
            unified_diff=material["unified_diff"], language="en",
        )
        desc_zh = await llm_generate(prompt_zh)
        desc_en = await llm_generate(prompt_en)
        generated_by = GENERATED_BY_MODEL
    except LlmGenerationError:
        desc_zh = template_diff_description(
            skill_name=skill_name, diff_stats=material, similarity=similarity, language="zh"
        )
        desc_en = template_diff_description(
            skill_name=skill_name, diff_stats=material, similarity=similarity, language="en"
        )
    return {
        **material,
        "description_zh": desc_zh,
        "description_en": desc_en,
        "generated_by": generated_by,
        "performance_hint_zh": PERFORMANCE_HINT_ZH if generated_by == GENERATED_BY_MODEL else None,
        "performance_hint_en": PERFORMANCE_HINT_EN if generated_by == GENERATED_BY_MODEL else None,
    }


__all__ = [
    "ARTIFACT_FILENAMES",
    "build_diff_prompt",
    "build_file_tree",
    "build_iteration_diff",
    "build_iteration_diff_material",
    "build_readme_prompt",
    "build_report_prompt",
    "compute_semantic_similarity",
    "compute_text_diff",
    "read_package_skill_md",
    "replay_validate_artifact",
    "template_diff_description",
]
