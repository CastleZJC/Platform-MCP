"""Skill 生态 MCP 工具（V3.0 M2.4，架构 §19.5.3 / §19.5.7 / 计划 M2.4、F-29~F-32）

CC 经 MCP 双通道管理个人库 Skill 生命周期：

- ``create_skill_draft``：创建草稿（自动扫广场相似推荐，F-29）；
- ``update_my_skill``：更新自己的 Skill（仅本人；广场副本独立表不受未审核更新影响，F-29）；
- ``submit_skill_for_review``：提交分享审核（重复分享二次确认覆盖，F-31）；
- ``withdraw_review``：撤回审核（仅审核中可撤回；停用视同撤回见 F-32，由 Web 启停承接）；
- ``resolve_share_iteration``：分享迭代解决（迭代 / 保留，F-30）。

状态转移、广场联动与业务审计委托 :class:`platform_mcp.review.service.SkillReviewService`（M2.3，
Web/MCP 双通道共用）；本模块为 MCP 传输适配层：身份贯通（``ReviewActor``）、会话编排
（``mutate + flush`` → 统一 commit）、结果格式化（统一 ``data`` 结构）、成功消息按 ``locale`` 返回。

边界：``ToolMeta.roles`` 角色动态过滤与其余生态工具（search/suggest/readme/add/remove/list/block）
属 M3.5；create/update 的双语报告/README 版本化存档属 M2.5/M4（本模块先落审计重放与模板兜底）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.common.database import get_session_factory
from platform_mcp.common.exceptions import SkillError
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.decorator import register_skill
from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
    ReviewResult,
    SkillReviewError,
    SkillReviewService,
)
from platform_mcp.review.state_machine import ReviewAction, transition
from platform_mcp.skills.ecosystem.draft import DraftBuildResult, build_draft_content
from platform_mcp.skills.plaza import scan_plaza_similar
from platform_mcp.skills.versioning import (
    archive_skill_version,
    audit_result_from_summary,
    generate_bilingual_readme,
    generate_bilingual_report,
)

_TOOL_NAMES = {
    "create_skill_draft",
    "update_my_skill",
    "submit_skill_for_review",
    "withdraw_review",
    "resolve_share_iteration",
}

#: 更新内容时不可直接改动的过渡/在审状态（审核中须先撤回，分享迭代须先解决）
_NON_UPDATABLE_STATES = frozenset({"PENDING_REVIEW", "SHARE_ITERATION", "APPROVED"})


@asynccontextmanager
async def _session_scope() -> AsyncIterator[AsyncSession]:
    """MCP 工具会话编排：成功 commit / 异常 rollback（与 ``common.database.get_db`` 同语义）。

    审核服务与草稿逻辑均 ``mutate + flush`` 不 commit，由本上下文统一提交，保证 MCP 通道
    与 Web 通道（``get_db``）事务边界一致。
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _build_actor(context: Any) -> ReviewActor:
    """从 MCP 调用上下文贯通认证身份为 :class:`ReviewActor`。

    Skill 生态操作强依赖认证身份（归属校验 F-29）；无 API Key 的遗留 stdio 场景 identity 为
    None，无法判定归属 → 拒绝（10004）。MCP identity 键为 ``user_id``（见 api_key_service），
    与 Web ``get_current_user`` 的 ``id`` 不同，故直接构造而非 ``from_user_dict``。
    """
    identity = getattr(context, "identity", None) if context is not None else None
    if not identity:
        raise SkillReviewError(
            "MCP 调用缺少认证身份（PLATFORM_MCP_API_KEY），无法执行 Skill 生态操作",
            code=CODE_FORBIDDEN,
        )
    return ReviewActor(
        username=identity["username"],
        role_code=identity.get("role_code") or "developer",
        user_id=identity.get("user_id"),
        locale=identity.get("locale"),
        trace_id=getattr(context, "trace_id", None),
    )


def _localized(actor: ReviewActor, zh: str, en: str) -> str:
    """动态产物按认证身份 ``locale`` 返回（§19.5.2）；缺省/中文 → zh，en-* → en。"""
    locale = (actor.locale or "zh-CN").lower()
    return en if locale.startswith("en") else zh


def _format_review_result(result: ReviewResult, message: str) -> dict:
    """审核服务结果 → MCP 统一 data 结构（含 owner 可见的 review_comment）。"""
    return {
        "success": True,
        "skill_id": result.skill_id,
        "skill_code": result.skill_code,
        "action": result.action,
        "old_status": result.old_status,
        "new_status": result.new_status,
        "share_status": result.share_status,
        "plaza_id": result.plaza_id,
        "review_comment": result.review_comment,
        "message": message,
    }


async def _audit_skill_action(
    actor: ReviewActor,
    skill: PmcpSkill,
    action: str,
    *,
    old_status: str | None,
    extra: dict | None = None,
) -> None:
    """create/update 业务审计（F-40 ``resource_type="skill"``，操作明细可区分）。

    submit/withdraw/resolve 的审计由 :class:`SkillReviewService` 内部落痕，此处仅补 create/update
    两个非状态机动作；MCP 传输层审计（``call_log``）对本生态工具跳过 audit_log 以避免重复。
    """
    detail: dict = {
        "skill_code": skill.skill_code,
        "action": action,
        "old_status": old_status,
        "new_status": skill.status,
        "share_status": skill.share_status,
        "channel": "mcp",
    }
    if extra:
        detail.update(extra)
    await write_audit_log(
        trace_id=actor.trace_id,
        operator=actor.username,
        skill_name=skill.skill_code,
        resource_type="skill",
        resource_id=str(skill.id),
        request_summary=f"Skill 生态（MCP）：{skill.skill_code} — {action}",
        extra_data=detail,
    )


def _build_tool_meta() -> list[ToolMeta]:
    return [
        ToolMeta(
            tool_name="create_skill_draft",
            display_name="创建Skill草稿",
            description=(
                "在个人库创建 Skill 草稿（status=DRAFT）：传入 skill_code/skill_name/SKILL.md 文本内容，"
                "平台落盘存档并重放 14 条合规审计 + 脱敏校验（第一道审核），自动扫描广场已发布 Skill 给出"
                "相似推荐（merge 合并 / new 新增结论素材）；草稿仅本人可见与经 MCP 使用，可后续 update_my_skill "
                "迭代、submit_skill_for_review 提交分享 / Create a Skill draft in your personal library "
                "(status=DRAFT): pass skill_code/skill_name and the SKILL.md text; the platform archives it, "
                "replays the 14 compliance audit rules + sanitization (first review gate), and automatically scans "
                "the published plaza for similar skills (merge/new recommendation). The draft is visible and "
                "MCP-usable only by you; iterate later via update_my_skill and share via submit_skill_for_review"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_code": {"type": "string"},
                    "skill_name": {"type": "string"},
                    "skill_md": {"type": "string"},
                    "description": {"type": "string"},
                    "version": {"type": "string", "default": "0.1.0"},
                },
                "required": ["skill_code", "skill_name", "skill_md"],
            },
            risk_level="LOW",
            timeout_seconds=60,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="update_my_skill",
            display_name="更新我的Skill",
            description=(
                "更新自己个人库内的 Skill（仅本人，不能更新他人 Skill）：可改 skill_name/description/version，"
                "传入 skill_md 则重新落盘并重放审计；已拒绝(REJECTED)/撤回(WITHDRAWN)状态更新内容后自动回到草稿"
                "(DRAFT)以便重新提交；审核中/分享迭代须先撤回或解决迭代。广场副本为独立表，未过审更新不影响广场 "
                "已发布版本 / Update a Skill in your own personal library (yours only; cannot update others'): "
                "change skill_name/description/version, and pass skill_md to re-archive and replay the audit; "
                "updating a REJECTED/WITHDRAWN skill returns it to DRAFT for resubmission; skills under review or "
                "in share-iteration must be withdrawn/resolved first. The plaza copy is a separate table, so an "
                "unreviewed update never affects the published plaza version"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "skill_name": {"type": "string"},
                    "description": {"type": "string"},
                    "skill_md": {"type": "string"},
                    "version": {"type": "string"},
                },
                "required": ["skill_id"],
            },
            risk_level="LOW",
            timeout_seconds=60,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="submit_skill_for_review",
            display_name="提交分享审核",
            description=(
                "把自己的 Skill 提交到广场分享审核（DRAFT/ENABLED/DISABLED → 审核中 PENDING_REVIEW）；"
                "若该 Skill 已分享或正在审核中，返回 code=10005 要求二次确认，携 confirm_reshare=true 重新调用即"
                "覆盖上一版本并重新通知审核组（F-31）/ Submit your Skill for plaza share review "
                "(DRAFT/ENABLED/DISABLED → PENDING_REVIEW). If it is already shared or under review, returns "
                "code=10005 requiring confirmation; re-call with confirm_reshare=true to overwrite the previous "
                "version and re-notify the review group (F-31)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "confirm_reshare": {"type": "boolean", "default": False},
                },
                "required": ["skill_id"],
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="withdraw_review",
            display_name="撤回审核",
            description=(
                "撤回已提交、尚在审核中的 Skill（PENDING_REVIEW → 撤回 WITHDRAWN），撤回后可经 update_my_skill "
                "修改并重新提交；邮件通知 admin 审核组（M5 挂接）。已启用 Skill 的停用视同撤回由 Web 启停承接"
                "（F-32）/ Withdraw a submitted Skill still under review (PENDING_REVIEW → WITHDRAWN); afterwards "
                "modify via update_my_skill and resubmit. Notifies the admin review group by email (wired in M5). "
                "Disabling an already-submitted skill counts as withdrawal (F-32), handled by the Web enable/disable"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                },
                "required": ["skill_id"],
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="resolve_share_iteration",
            display_name="解决分享迭代",
            description=(
                "admin 合并到广场已有 Skill 后（SHARE_ITERATION），由本人选择：choice=iterate 采纳合并（覆盖本地，"
                "内容级差异描述由 M4 外部大模型提示）/ choice=keep 保留本地忽略本次迭代；解决后状态=已启用 ENABLED"
                "（F-30）/ After admin merges into an existing plaza skill (SHARE_ITERATION), the owner chooses: "
                "choice=iterate to accept the merge (overwrite local; content-level diff is provided by the external "
                "model in M4) or choice=keep to keep local and ignore this iteration; the status becomes ENABLED "
                "after resolution (F-30)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "choice": {"type": "string"},
                },
                "required": ["skill_id", "choice"],
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
    ]


@register_skill("skill_ecosystem")
class SkillEcosystemSkill:
    """Skill 生态双通道工具集（MCP 传输适配层，业务委托审核服务与草稿助手）。"""

    def skill_name(self) -> str:
        return "skill_ecosystem"

    def list_tools(self) -> list[ToolMeta]:
        return _build_tool_meta()

    async def validate(self, tool_name: str, params: dict) -> dict:
        if tool_name == "create_skill_draft":
            if not params.get("skill_code"):
                raise SkillError("skill_code 参数必填")
            if not params.get("skill_name"):
                raise SkillError("skill_name 参数必填")
            if not params.get("skill_md"):
                raise SkillError("skill_md 参数必填（SKILL.md 文本内容）")
        elif tool_name in ("update_my_skill", "submit_skill_for_review", "withdraw_review"):
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
        elif tool_name == "resolve_share_iteration":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
            if params.get("choice") not in ("iterate", "keep"):
                raise SkillError("choice 必须为 iterate 或 keep")
        return params

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any:
        if tool_name == "create_skill_draft":
            return await self._create_skill_draft(params, context)
        if tool_name == "update_my_skill":
            return await self._update_my_skill(params, context)
        if tool_name == "submit_skill_for_review":
            return await self._submit_skill_for_review(params, context)
        if tool_name == "withdraw_review":
            return await self._withdraw_review(params, context)
        if tool_name == "resolve_share_iteration":
            return await self._resolve_share_iteration(params, context)
        raise NotImplementedError(f"Tool {tool_name} 未实现")

    def support(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # --- Tool 实现 ---

    async def _create_skill_draft(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_code = str(params["skill_code"]).strip()
        skill_name = str(params["skill_name"]).strip()
        description = params.get("description")
        skill_md = str(params["skill_md"])
        version = str(params.get("version") or "0.1.0")

        async with _session_scope() as session:
            existing: PmcpSkill | None = (
                await session.execute(select(PmcpSkill).where(PmcpSkill.skill_code == skill_code))
            ).scalar_one_or_none()
            if existing is not None:
                raise SkillReviewError(
                    f"Skill 编码 {skill_code} 已存在，请换一个编码或经 update_my_skill 更新",
                    code=CODE_INVALID_STATE,
                )

            draft = build_draft_content(
                skill_code=skill_code,
                skill_name=skill_name,
                description=description,
                skill_md=skill_md,
                version=version,
            )
            similar = await scan_plaza_similar(session, skill_name, description)

            skill = PmcpSkill(
                skill_code=skill_code,
                skill_name=skill_name,
                description=description,
                status="DRAFT",
                register_method="mcp",
                tool_count=0,
                source_path=draft.source_path,
                source_checksum=draft.source_checksum,
                source_format=None,
                version=version,
                audit_status=draft.audit_status,
                audit_result=draft.audit_result.to_audit_summary(),
                readme_generated=draft.readme_generated,
                origin="ORIGINAL",
                share_status="unshared",
                inserted_by=actor.username,
                updated_by=actor.username,
            )
            session.add(skill)
            await session.flush()
            await _audit_skill_action(actor, skill, "create", old_status=None)

            # V3.0 M2.5：版本化双语存档（F-28）——审核报告含广场比对结论
            report_zh, report_en = generate_bilingual_report(
                skill_code=skill_code, skill_name=skill_name, description=description,
                version=version, audit_result=draft.audit_result, similar_skills=similar,
            )
            await archive_skill_version(
                session, skill_id=skill.id, version=version, checksum=draft.source_checksum,
                readme_zh=draft.readme_zh, readme_en=draft.readme_en,
                report_zh=report_zh, report_en=report_en,
                audit_snapshot=draft.audit_result.to_audit_summary(),
                operator=actor.username,
            )

            recommendation = similar[0]["recommendation"] if similar else "new"
            logger.info(
                "MCP create_skill_draft: code={} owner={} audit={} similar={}",
                skill_code, actor.username, draft.audit_status, len(similar),
            )
            return {
                "success": True,
                "skill_id": skill.id,
                "skill_code": skill.skill_code,
                "skill_name": skill.skill_name,
                "status": skill.status,
                "version": skill.version,
                "audit_status": draft.audit_status,
                "audit_summary": draft.audit_result.to_audit_summary(),
                "readme_generated": draft.readme_generated,
                "similar_skills": similar,
                "recommendation": recommendation,
                "message": _localized(
                    actor,
                    f"草稿已创建（审计结论 {draft.audit_status}），可经 update_my_skill 迭代或 submit_skill_for_review 提交分享",
                    f"Draft created (audit {draft.audit_status}); iterate via update_my_skill or share via submit_skill_for_review",
                ),
            }

    async def _update_my_skill(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])

        async with _session_scope() as session:
            skill: PmcpSkill | None = await session.get(PmcpSkill, skill_id)
            if skill is None:
                raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
            if skill.inserted_by != actor.username:
                # F-29：不能更新他人 Skill
                raise SkillReviewError("无权更新他人 Skill", code=CODE_FORBIDDEN)
            old_status = skill.status
            if old_status in _NON_UPDATABLE_STATES:
                raise SkillReviewError(
                    f"状态 {old_status} 不可直接更新内容（审核中请先 withdraw_review，分享迭代请先 resolve_share_iteration）",
                    code=CODE_INVALID_STATE,
                )

            skill_name = str(params.get("skill_name") or skill.skill_name)
            description = params.get("description") if params.get("description") is not None else skill.description
            version = str(params.get("version") or skill.version or "0.1.0")
            skill_md = params.get("skill_md")

            draft: DraftBuildResult | None = None
            audit_summary = skill.audit_result
            audit_status = skill.audit_status
            if skill_md:
                draft = build_draft_content(
                    skill_code=skill.skill_code,
                    skill_name=skill_name,
                    description=description,
                    skill_md=str(skill_md),
                    version=version,
                )
                skill.source_path = draft.source_path
                skill.source_checksum = draft.source_checksum
                skill.audit_status = draft.audit_status
                skill.audit_result = draft.audit_result.to_audit_summary()
                if draft.readme_generated:
                    skill.readme_generated = True
                audit_summary = draft.audit_result.to_audit_summary()
                audit_status = draft.audit_status

            skill.skill_name = skill_name
            skill.description = description
            skill.version = version

            # 状态联动（§19.5.3「已拒绝 ──修改后──→ 草稿」「撤回 ──恢复──→ 草稿」）：
            # 直接走状态机（单一事实来源），与内容更新同事务、同审计，避免与审核服务重复留痕。
            action_label = "update"
            if old_status == "REJECTED":
                skill.status = transition(old_status, ReviewAction.REVISE).value
                action_label = "update_revise"
            elif old_status == "WITHDRAWN":
                skill.status = transition(old_status, ReviewAction.RESTORE).value
                action_label = "update_restore"
            skill.updated_by = actor.username
            await session.flush()
            await _audit_skill_action(actor, skill, action_label, old_status=old_status)

            # V3.0 M2.5：版本化双语存档（F-28 每次更新均存档）
            arc_checksum: str | None
            if draft is not None:
                arc_readme_zh, arc_readme_en = draft.readme_zh, draft.readme_en
                arc_audit = draft.audit_result
                arc_checksum = draft.source_checksum
            else:
                # 元数据更新（无内容变更）：从已存包重生成双语 README，报告用存档审计摘要重建
                arc_readme_zh, arc_readme_en = generate_bilingual_readme(
                    skill.skill_name, skill.description, skill.source_path or "", skill.version
                )
                arc_audit = audit_result_from_summary(skill.audit_result, skill.skill_name)
                arc_checksum = skill.source_checksum
            arc_similar = await scan_plaza_similar(
                session, skill.skill_name, skill.description, exclude_skill_code=skill.skill_code
            )
            report_zh, report_en = generate_bilingual_report(
                skill_code=skill.skill_code, skill_name=skill.skill_name, description=skill.description,
                version=skill.version, audit_result=arc_audit, similar_skills=arc_similar,
            )
            await archive_skill_version(
                session, skill_id=skill.id, version=skill.version, checksum=arc_checksum,
                readme_zh=arc_readme_zh, readme_en=arc_readme_en,
                report_zh=report_zh, report_en=report_en,
                audit_snapshot=arc_audit.to_audit_summary(),
                operator=actor.username,
            )

            logger.info(
                "MCP update_my_skill: code={} owner={} action={} audit={}",
                skill.skill_code, actor.username, action_label, audit_status,
            )
            return {
                "success": True,
                "skill_id": skill.id,
                "skill_code": skill.skill_code,
                "skill_name": skill.skill_name,
                "action": action_label,
                "old_status": old_status,
                "status": skill.status,
                "version": skill.version,
                "audit_status": audit_status,
                "audit_summary": audit_summary,
                "message": _localized(
                    actor,
                    f"已更新（{old_status} → {skill.status}）；广场副本不受未审核更新影响",
                    f"Updated ({old_status} → {skill.status}); the plaza copy is unaffected by unreviewed updates",
                ),
            }

    async def _submit_skill_for_review(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        confirm_reshare = bool(params.get("confirm_reshare", False))
        async with _session_scope() as session:
            service = SkillReviewService(session)
            result = await service.submit_for_review(actor, skill_id, confirm_reshare=confirm_reshare)
            return _format_review_result(
                result,
                _localized(
                    actor,
                    f"已提交分享审核（{result.old_status} → {result.new_status}），等待 admin 审核",
                    f"Submitted for share review ({result.old_status} → {result.new_status}); pending admin review",
                ),
            )

    async def _withdraw_review(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        async with _session_scope() as session:
            service = SkillReviewService(session)
            result = await service.withdraw(actor, skill_id)
            return _format_review_result(
                result,
                _localized(
                    actor,
                    f"已撤回审核（{result.old_status} → {result.new_status}），可修改后重新提交",
                    f"Review withdrawn ({result.old_status} → {result.new_status}); modify and resubmit later",
                ),
            )

    async def _resolve_share_iteration(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        choice = str(params["choice"])
        async with _session_scope() as session:
            service = SkillReviewService(session)
            result = await service.resolve_share_iteration(actor, skill_id, choice)  # type: ignore[arg-type]
            return _format_review_result(
                result,
                _localized(
                    actor,
                    f"分享迭代已解决（{choice}），状态=已启用",
                    f"Share iteration resolved ({choice}); status is now ENABLED",
                ),
            )
