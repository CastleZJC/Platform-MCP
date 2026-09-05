"""版本存档本地模型升级任务（V3.0 M4.2，架构 §19.5.6 / 计划 M4.2、F-35、VNF-01）

Web 上传链路（:mod:`platform_mcp.api.skills.upload_skill`）经 FastAPI ``BackgroundTasks``
挂接：上传时先以确定性模板即时存档（满足 F-28「每次新增/更新均存档」即时性），响应返回后
后台把 ``generated_by=template`` 存档升级为本地 Qwen3-4B 产物（``generated_by=model``）。

升级口径：

- **不阻塞主链路**（VNF-01）：任务内部全捕获异常（仅日志留痕），任何失败保留模板存档；
- **重放校验门禁**：模型产物（report_zh / report_en / readme_en）逐一经
  :func:`platform_mcp.skills.llm.generation.replay_validate_artifact` 重放校验，任一 🔴 命中
  整体放弃升级（与广场审核硬门禁同口径）；readme_zh 恒保留存档现值（包内用户原文优先契约，
  :func:`platform_mcp.skills.versioning.generate_bilingual_readme`）；
- **幂等**：仅 ``generated_by=template`` 的存档可升级（model/external 为终态或外部通道产物）；
- **独立会话**：``get_session_factory`` 自持 session（后台任务不依赖请求级 ``get_db``）。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.common.database import get_session_factory
from platform_mcp.skills.llm import GENERATED_BY_MODEL, llm_available, llm_generate
from platform_mcp.skills.llm.generation import (
    build_file_tree,
    build_readme_prompt,
    build_report_prompt,
    read_package_skill_md,
    replay_validate_artifact,
)
from platform_mcp.skills.models import PmcpSkillVersion
from platform_mcp.skills.plaza import scan_plaza_similar
from platform_mcp.skills.versioning import (
    GENERATED_BY_TEMPLATE,
    archive_skill_version,
    audit_result_from_summary,
)


async def upgrade_version_artifacts(skill_id: int, version: str, *, operator: str | None = None) -> bool:
    """后台升级 ``generated_by=template`` 存档为本地模型产物（model）。

    供 Web 上传链路 ``BackgroundTasks`` 挂接（响应返回后执行）；全捕获异常，失败保留模板存档
    并返回 False（模板兜底保证可用性）。升级成功写 ``action="artifact_upgrade"`` 审计留痕。
    """
    try:
        if not llm_available():
            logger.debug("本地生成模型未就绪，跳过存档升级：skill_id={} v{}", skill_id, version)
            return False
        factory = get_session_factory()
        async with factory() as session:
            from platform_mcp.mcp_server.models import PmcpSkill

            skill = await session.get(PmcpSkill, skill_id)
            if skill is None:
                logger.warning("升级任务未找到 Skill：skill_id={}", skill_id)
                return False
            existing: PmcpSkillVersion | None = (
                await session.execute(
                    select(PmcpSkillVersion).where(
                        PmcpSkillVersion.skill_id == skill_id,
                        PmcpSkillVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
            if existing is None or existing.generated_by != GENERATED_BY_TEMPLATE:
                return False  # 无存档行（模板存档已失败）或已升级/外部产物 —— 幂等跳过

            # 素材：审计摘要重建 + 广场比对 + 包内 SKILL.md + 文件树（M4.2 输入口径）
            audit = audit_result_from_summary(skill.audit_result, skill.skill_name)
            similar = await scan_plaza_similar(
                session, skill.skill_name, skill.description, exclude_skill_code=skill.skill_code
            )
            skill_md = read_package_skill_md(skill.source_path)
            file_tree = build_file_tree(skill.source_path)

            report_zh_prompt = build_report_prompt(
                skill_code=skill.skill_code, skill_name=skill.skill_name,
                description=skill.description, version=version,
                audit_result=audit, similar_skills=similar, language="zh",
            )
            report_en_prompt = build_report_prompt(
                skill_code=skill.skill_code, skill_name=skill.skill_name,
                description=skill.description, version=version,
                audit_result=audit, similar_skills=similar, language="en",
            )
            artifacts = {
                "report_zh": await llm_generate(report_zh_prompt),
                "report_en": await llm_generate(report_en_prompt),
                "readme_en": await llm_generate(
                    build_readme_prompt(
                        skill_name=skill.skill_name, description=skill.description,
                        skill_md=skill_md, file_tree=file_tree, version=version, language="en",
                    )
                ),
            }
            # 重放校验门禁：任一产物 🔴 命中整体放弃（保留模板存档）；
            # 键 → 重放类型映射（replay_validate_artifact 值域 readme|report，
            # 与 generation.ARTIFACT_FILENAMES 对齐：readme_en→readme，report_zh/en→report）
            _REPLAY_KIND = {"readme_en": "readme", "report_zh": "report", "report_en": "report"}
            for artifact_key, content in artifacts.items():
                passed, violations = replay_validate_artifact(
                    artifact_type=_REPLAY_KIND[artifact_key], content=content,
                    skill_md=skill_md, skill_name=skill.skill_name,
                )
                if not passed:
                    logger.warning(
                        "模型产物重放校验失败，保留模板存档：skill_id={} v{} {} violations={}",
                        skill_id, version, artifact_key, violations,
                    )
                    return False

            await archive_skill_version(
                session,
                skill_id=skill_id,
                version=version,
                checksum=existing.checksum,
                readme_zh=existing.readme_zh,  # 包内用户原文优先，恒不覆盖
                readme_en=artifacts["readme_en"],
                report_zh=artifacts["report_zh"],
                report_en=artifacts["report_en"],
                audit_snapshot=existing.audit_snapshot,
                operator=operator,
                generated_by=GENERATED_BY_MODEL,
            )
            await session.commit()
            await write_audit_log(
                operator=operator or "system",
                resource_type="skill",
                resource_id=str(skill_id),
                request_summary=f"Skill 版本存档本地模型升级：{skill.skill_code} v{version}",
                extra_data={
                    "action": "artifact_upgrade",
                    "channel": "web-background",
                    "skill_code": skill.skill_code,
                    "version": version,
                    "generated_by": GENERATED_BY_MODEL,
                },
            )
            logger.info("版本存档已升级为本地模型产物：skill_id={} v{}", skill_id, version)
            return True
    except Exception as exc:  # noqa: BLE001 - 后台任务全捕获（VNF-01 不阻塞主链路）
        logger.warning("存档升级任务失败（保留模板兜底）：skill_id={} v{} — {}", skill_id, version, exc)
        return False


__all__ = ["upgrade_version_artifacts"]
