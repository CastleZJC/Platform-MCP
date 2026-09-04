"""Skill 版本化双语存档（V3.0 M2.5，架构 §19.5.3 / §19.5.6 / 计划 M2.5、F-28）

每次新增/更新 Skill 生成中英双语审核报告（SkillStandard 14 条合规规则命中 + 广场比对
"推荐合并/新增"结论）与中英双语 README，按版本存档到 ``pmcp_skill_version``
（不可篡改：无 update/delete API；同版本再存档为草稿迭代期覆盖，不同版本累积为历史）。

M4 前采用**确定性模板兜底**（§19.5.6）：复用 V2.1 README 模板 + 审计规则结构化报告，
``generated_by="template"``；M4 挂接 Qwen3-4B 本地生成后切换 ``generated_by="model"``，
本模块存档契约（双语字段 + audit_snapshot + generated_by）保持不变。

Web 上传链路（:mod:`platform_mcp.skills.upload`）与 MCP 草稿链路
（:mod:`platform_mcp.skills.ecosystem.draft`）共用本模块，满足 F-28「每次新增/更新」。
事务边界：``archive_skill_version`` 仅 ``mutate + flush`` 不 commit（与审核服务/上传链路一致，
由 ``get_db`` / MCP ``_session_scope`` 统一提交）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.i18n import RESOURCES, get_text, split_bilingual
from platform_mcp.skills.audit.models import AuditResult, AuditRuleResult, Severity
from platform_mcp.skills.models import PmcpSkillVersion
from platform_mcp.skills.readme.generator import generate_readme, generate_readme_en

#: §19.5.6：M4 前模板兜底产物来源标记；M4 挂 Qwen3 本地生成后为 ``"model"``
GENERATED_BY_TEMPLATE = "template"

_SEVERITY_ZH = {
    Severity.CRITICAL: "🔴 严重",
    Severity.WARNING: "🟡 警告",
    Severity.SUGGESTION: "🟢 建议",
}
_SEVERITY_EN = {
    Severity.CRITICAL: "🔴 Critical",
    Severity.WARNING: "🟡 Warning",
    Severity.SUGGESTION: "🟢 Suggestion",
}


#: 无源码包 Skill（source_path 为空）的哨兵目录。不能直接 ``Path("")``：
#: 其等于 CWD，会把仓库根 README.md 误读为包内原文、全仓库目录树扫进英文模板。
_NO_PACKAGE_DIR = Path("__no_skill_package__")


def _localized_tools(
    tools: list[tuple[str, str]] | None, lang: str
) -> list[tuple[str, str]] | None:
    """配套工具描述按语言拆分（ToolMeta.description 为「中文 / English」并列单串）。

    ``lang`` 为 ``"zh"`` 取中文段、``"en"`` 取英文段；未按约定并列的描述两语言同值。
    """
    if not tools:
        return tools
    idx = 0 if lang == "zh" else 1
    return [(name, split_bilingual(desc)[idx]) for name, desc in tools]


def _bilingual_description(
    skill_code: str | None, description: str | None
) -> tuple[str, str]:
    """双语功能描述取值：内置 Skill（``skill.desc.{skill_code}`` 已登记 RESOURCES）按字典取
    真双语；未登记的 Skill 退回 ``split_bilingual`` 拆「中文 / English」并列描述，
    未按约定并列时两语言同值（fail-open，M4 本地模型接入后可自然译出）。"""
    if skill_code:
        key = f"skill.desc.{skill_code}"
        if key in RESOURCES:
            return get_text(key, "zh-CN"), get_text(key, "en-US")
    return split_bilingual(description)


def generate_bilingual_readme(
    skill_name: str,
    description: str | None,
    skill_dir: str | Path,
    version: str = "0.1.0",
    tools: list[tuple[str, str]] | None = None,
    skill_code: str | None = None,
    register_method: str | None = None,
) -> tuple[str, str]:
    """生成中英双语 README，返回 ``(readme_zh, readme_en)``。

    中文优先取包内已存 ``README.md``（用户上传原文），缺失时用 V2.1 中文模板生成；
    英文恒用模板生成（M4 前兜底，M4 由本地模型产出更自然译文）。
    空 ``skill_dir``（内置 Skill 无源码包）归一为哨兵目录：中文走模板、无文件树、
    渲染 ``tools`` 配套工具清单（内置 Skill 经 registry 传入）。
    功能描述与工具描述按语言取纯净单语（内置 Skill 经 ``skill.desc.*`` 字典，
    其余按「中文 / English」并列约定拆分）；``register_method="decorator"``
    快速开始无审核步骤（装饰器注册无需审核，用户验收口径）。
    """
    skill_path = Path(skill_dir) if str(skill_dir).strip() else _NO_PACKAGE_DIR
    desc_zh, desc_en = _bilingual_description(skill_code, description)
    tools_zh, tools_en = _localized_tools(tools, "zh"), _localized_tools(tools, "en")
    readme_path = skill_path / "README.md"
    if readme_path.exists():
        try:
            readme_zh = readme_path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - 读盘失败降级为模板生成
            readme_zh = generate_readme(skill_name, desc_zh, skill_path, version, tools_zh, register_method)
    else:
        readme_zh = generate_readme(skill_name, desc_zh, skill_path, version, tools_zh, register_method)
    readme_en = generate_readme_en(skill_name, desc_en, skill_path, version, tools_en, register_method)
    return readme_zh, readme_en


def _registry_tools(skill_code: str) -> list[tuple[str, str]] | None:
    """内置 Skill 的配套工具清单（Web 进程经工厂实例化后取 list_tools）。

    仅内置 Skill（database/server/生态）可实例化；用户 Skill 或实例化失败时
    返回 ``None``——README 模板按无工具口径渲染（尽力增强，不阻断存档链路）。
    """
    try:
        from platform_mcp.mcp_server.skill.registry import get_skill_instance

        instance = get_skill_instance(skill_code)
        if instance is None:
            return None
        return [(m.tool_name, m.description) for m in instance.list_tools()]
    except Exception:  # noqa: BLE001 - README 尽力增强，任何失败降级为无工具清单
        logger.debug("registry tools lookup failed for skill_code={}", skill_code)
        return None


def _failed_rules(audit_result: AuditResult) -> list[AuditRuleResult]:
    return [r for r in audit_result.results if not r.passed]


def _conclusion(similar_skills: list[dict] | None) -> tuple[str, list[dict]]:
    """从广场相似扫描结果派生推荐结论（merge/new）与展示列表。"""
    similar = similar_skills or []
    recommendation = similar[0].get("recommendation", "new") if similar else "new"
    return recommendation, similar


def _report_zh(
    *,
    skill_code: str,
    skill_name: str,
    description: str | None,
    version: str,
    audit_result: AuditResult,
    similar_skills: list[dict] | None,
) -> str:
    recommendation, similar = _conclusion(similar_skills)
    failed = _failed_rules(audit_result)
    passed_text = "通过" if audit_result.passed else "未通过（存在 🔴 严重违规，阻止入广场）"

    lines = [
        f"# Skill 审核报告：{skill_name}",
        "",
        "> 本报告由确定性模板生成（generated_by=template，架构 §19.5.6 兜底）；"
        "M4 挂接本地生成模型后切换为 model 产物。",
        "",
        "## 一、基本信息",
        "",
        "| 项目 | 值 |",
        "|------|-----|",
        f"| Skill 编码 | {skill_code} |",
        f"| Skill 名称 | {skill_name} |",
        f"| 版本 | v{version} |",
        f"| 描述 | {description or '（无）'} |",
        f"| 生成日期 | {date.today().isoformat()} |",
        "",
        "## 二、合规审计（SkillStandard 14 条规则）",
        "",
        f"- 总规则数：{audit_result.total_rules}",
        f"- 🔴 严重：{audit_result.critical_count}　🟡 警告：{audit_result.warning_count}"
        f"　🟢 建议：{audit_result.suggestion_count}",
        f"- 审计结论：**{passed_text}**",
        "",
        "### 命中明细",
        "",
    ]
    if failed:
        lines += [
            "| 规则 | 级别 | 文件 | 行 | 问题 | 建议 |",
            "|------|------|------|----|------|------|",
        ]
        for r in failed:
            sev = _SEVERITY_ZH.get(r.severity, r.severity.value)
            file_path = r.file_path or "（包级）"
            line_no = r.line_number or "-"
            lines.append(
                f"| {r.rule_id} | {sev} | {file_path} | {line_no} | {r.description or '-'} | {r.suggestion or '-'} |"
            )
    else:
        lines.append("全部规则通过，无违规命中。")

    lines += ["", "## 三、广场比对结论", ""]
    if similar:
        top = similar[0]
        rec_text = "合并到广场现有 Skill" if recommendation == "merge" else "作为新增 Skill 分享"
        lines.append(
            f"广场发现 {len(similar)} 个相似 Skill，最高相似度 {top.get('similarity')}，"
            f"推荐结论：**{rec_text}**。"
        )
        lines += ["", "| 广场 Skill | 版本 | 相似度 | 建议 |", "|------|------|------|------|"]
        for s in similar:
            s_rec = "合并" if s.get("recommendation") == "merge" else "新增"
            lines.append(
                f"| {s.get('skill_name')}（{s.get('skill_code')}） | {s.get('version') or '-'} "
                f"| {s.get('similarity')} | {s_rec} |"
            )
    else:
        lines.append("未在广场发现相似 Skill，推荐作为**新增** Skill 分享。")
    lines.append("")
    return "\n".join(lines)


def _report_en(
    *,
    skill_code: str,
    skill_name: str,
    description: str | None,
    version: str,
    audit_result: AuditResult,
    similar_skills: list[dict] | None,
) -> str:
    recommendation, similar = _conclusion(similar_skills)
    failed = _failed_rules(audit_result)
    passed_text = "PASSED" if audit_result.passed else "FAILED (critical violations block plaza entry)"

    lines = [
        f"# Skill Review Report: {skill_name}",
        "",
        "> Generated by the deterministic template (generated_by=template, architecture §19.5.6 fallback); "
        "switches to a model artifact once the local generation model is wired in M4.",
        "",
        "## 1. Basic Info",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Skill Code | {skill_code} |",
        f"| Skill Name | {skill_name} |",
        f"| Version | v{version} |",
        f"| Description | {description or '(none)'} |",
        f"| Generated | {date.today().isoformat()} |",
        "",
        "## 2. Compliance Audit (SkillStandard 14 rules)",
        "",
        f"- Total rules: {audit_result.total_rules}",
        f"- 🔴 Critical: {audit_result.critical_count}　🟡 Warning: {audit_result.warning_count}"
        f"　🟢 Suggestion: {audit_result.suggestion_count}",
        f"- Conclusion: **{passed_text}**",
        "",
        "### Hits",
        "",
    ]
    if failed:
        lines += [
            "| Rule | Severity | File | Line | Issue | Suggestion |",
            "|------|----------|------|------|-------|------------|",
        ]
        for r in failed:
            sev = _SEVERITY_EN.get(r.severity, r.severity.value)
            file_path = r.file_path or "(package)"
            line_no = r.line_number or "-"
            lines.append(
                f"| {r.rule_id} | {sev} | {file_path} | {line_no} | {r.description or '-'} | {r.suggestion or '-'} |"
            )
    else:
        lines.append("All rules passed; no violations.")

    lines += ["", "## 3. Plaza Comparison", ""]
    if similar:
        top = similar[0]
        rec_text = "merge into the existing plaza skill" if recommendation == "merge" else "share as a new skill"
        lines.append(
            f"Found {len(similar)} similar plaza skill(s); top similarity {top.get('similarity')}; "
            f"recommendation: **{rec_text}**."
        )
        lines += ["", "| Plaza Skill | Version | Similarity | Advice |", "|------|------|------|------|"]
        for s in similar:
            s_rec = "merge" if s.get("recommendation") == "merge" else "new"
            lines.append(
                f"| {s.get('skill_name')} ({s.get('skill_code')}) | {s.get('version') or '-'} "
                f"| {s.get('similarity')} | {s_rec} |"
            )
    else:
        lines.append("No similar plaza skill found; recommended as a **new** skill.")
    lines.append("")
    return "\n".join(lines)


def generate_bilingual_report(
    *,
    skill_code: str,
    skill_name: str,
    description: str | None,
    version: str,
    audit_result: AuditResult,
    similar_skills: list[dict] | None = None,
) -> tuple[str, str]:
    """生成中英双语审核报告，返回 ``(report_zh, report_en)``（14 规则命中 + 广场比对结论）。

    描述为「中文 / English」并列单串时按语言拆分（与双语 README 同口径，单语纯净）。
    """
    desc_zh, desc_en = split_bilingual(description)
    report_zh = _report_zh(
        skill_code=skill_code, skill_name=skill_name, description=desc_zh,
        version=version, audit_result=audit_result, similar_skills=similar_skills,
    )
    report_en = _report_en(
        skill_code=skill_code, skill_name=skill_name, description=desc_en,
        version=version, audit_result=audit_result, similar_skills=similar_skills,
    )
    return report_zh, report_en


def audit_result_from_summary(summary: dict | None, skill_name: str = "") -> AuditResult:
    """从存档的 ``audit_result`` 摘要重建 :class:`AuditResult`（元数据更新无新鲜审计时用）。

    摘要（:meth:`AuditResult.to_audit_summary`）的 ``failed_rules`` 仅含
    rule_id/severity/file_path/line_number，重建结果的 description/suggestion 缺省——
    用于版本存档报告的计数与命中概览已足够，完整明细另见 ``pmcp_skill_audit_report``。
    """
    result = AuditResult(skill_name=skill_name)
    if not summary:
        return result
    result.total_rules = int(summary.get("total_rules", 14))
    result.critical_count = int(summary.get("critical_count", 0))
    result.warning_count = int(summary.get("warning_count", 0))
    result.suggestion_count = int(summary.get("suggestion_count", 0))
    result.passed = bool(summary.get("passed", True))
    for fr in summary.get("failed_rules", []) or []:
        try:
            severity = Severity(fr.get("severity") or "suggestion")
        except ValueError:  # pragma: no cover - 防御非法枚举值
            severity = Severity.SUGGESTION
        result.results.append(
            AuditRuleResult(
                rule_id=fr.get("rule_id", ""),
                severity=severity,
                passed=False,
                file_path=fr.get("file_path", "") or "",
                line_number=int(fr.get("line_number", 0) or 0),
            )
        )
    return result


async def archive_skill_version(
    db: AsyncSession,
    *,
    skill_id: int,
    version: str,
    checksum: str | None,
    readme_zh: str | None,
    readme_en: str | None,
    report_zh: str | None,
    report_en: str | None,
    audit_snapshot: dict | None,
    operator: str | None,
    generated_by: str = GENERATED_BY_TEMPLATE,
) -> PmcpSkillVersion:
    """按 ``(skill_id, version)`` upsert 版本存档（双语 README/报告 + 审计快照 + 产物来源）。

    唯一约束 ``uq_pmcp_skill_version_skill_ver`` 下同版本再存档覆盖（草稿迭代期），
    不同版本累积为不可篡改历史（无 update/delete API）。仅 ``flush`` 不 commit，
    事务由调用方（``get_db`` / MCP ``_session_scope``）统一提交。
    """
    existing: PmcpSkillVersion | None = (
        await db.execute(
            select(PmcpSkillVersion).where(
                PmcpSkillVersion.skill_id == skill_id,
                PmcpSkillVersion.version == version,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.checksum = checksum
        existing.readme_zh = readme_zh
        existing.readme_en = readme_en
        existing.report_zh = report_zh
        existing.report_en = report_en
        existing.audit_snapshot = audit_snapshot
        existing.generated_by = generated_by
        existing.updated_by = operator
        record = existing
    else:
        record = PmcpSkillVersion(
            skill_id=skill_id,
            version=version,
            checksum=checksum,
            readme_zh=readme_zh,
            readme_en=readme_en,
            report_zh=report_zh,
            report_en=report_en,
            audit_snapshot=audit_snapshot,
            generated_by=generated_by,
            inserted_by=operator,
            updated_by=operator,
        )
        db.add(record)
    await db.flush()
    logger.debug(
        "Skill 版本存档：skill_id={} version={} generated_by={}",
        skill_id, version, generated_by,
    )
    return record


async def backfill_missing_archives(db: AsyncSession) -> int:
    """部署期幂等补全：扫描全部 Skill 当前版本存档，补齐缺失的双语 README / 审核报告。

    覆盖三类缺口（Web 启动时执行，已完整条目跳过，返回补全条数）：
    - 无版本存档行（存档机制上线前的历史 Skill）；
    - 存档行 readme_zh / readme_en 为 NULL（单语言缺失）；
    - 存档行 report_zh / report_en 为 NULL（审核报告缺失）。

    已有字段一律保留原值（不覆盖用户上传原文 / 历史报告），仅填充 NULL 字段；
    审计快照优先取存档行、缺失时回退 pmcp_skill.audit_result；产物来源恒为模板兜底
    （generated_by=template，架构 §19.5.6）。事务由调用方提交。
    """
    from platform_mcp.mcp_server.models import PmcpSkill

    skills = (await db.execute(select(PmcpSkill))).scalars().all()
    filled = 0
    for s in skills:
        version = s.version or "0.1.0"
        existing = (await db.execute(
            select(PmcpSkillVersion).where(
                PmcpSkillVersion.skill_id == s.id, PmcpSkillVersion.version == version
            )
        )).scalar_one_or_none()
        need = existing is None or not existing.readme_zh or not existing.readme_en \
            or not existing.report_zh or not existing.report_en
        if not need:
            continue
        skill_dir = s.source_path or ""
        tools = _registry_tools(s.skill_code)
        if existing is None:
            readme_zh, readme_en = generate_bilingual_readme(
                s.skill_name, s.description, skill_dir, version, tools=tools,
                skill_code=s.skill_code, register_method=s.register_method,
            )
            audit = audit_result_from_summary(s.audit_result, s.skill_name)
            report_zh, report_en = generate_bilingual_report(
                skill_code=s.skill_code, skill_name=s.skill_name,
                description=s.description, version=version, audit_result=audit,
            )
            checksum = s.source_checksum
        else:
            if not existing.readme_zh or not existing.readme_en:
                gen_zh, gen_en = generate_bilingual_readme(
                    s.skill_name, s.description, skill_dir, version, tools=tools,
                    skill_code=s.skill_code, register_method=s.register_method,
                )
                readme_zh = existing.readme_zh or gen_zh
                readme_en = existing.readme_en or gen_en
            else:
                readme_zh, readme_en = existing.readme_zh, existing.readme_en
            if not existing.report_zh or not existing.report_en:
                audit = audit_result_from_summary(existing.audit_snapshot or s.audit_result, s.skill_name)
                gen_rz, gen_re = generate_bilingual_report(
                    skill_code=s.skill_code, skill_name=s.skill_name,
                    description=s.description, version=version, audit_result=audit,
                )
                report_zh = existing.report_zh or gen_rz
                report_en = existing.report_en or gen_re
            else:
                report_zh, report_en = existing.report_zh, existing.report_en
            checksum = existing.checksum
        await archive_skill_version(
            db, skill_id=s.id, version=version, checksum=checksum,
            readme_zh=readme_zh, readme_en=readme_en,
            report_zh=report_zh, report_en=report_en,
            audit_snapshot=(existing.audit_snapshot if existing else s.audit_result),
            operator=None, generated_by=GENERATED_BY_TEMPLATE,
        )
        filled += 1
    return filled
