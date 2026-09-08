"""Skill 生态账户/审核 MCP 工具（V3.0 M3.5，架构 §19.5.4 / §19.5.7，双端承接）

承接 Web 侧的广场审核、审计查询与个人设置功能到 MCP 通道（除四类“仅 Web”外双端均可操作），
业务委托既有服务，避免装饰性直改：

- ``review_skill``：广场审核（approve 新增 / merge 合并 / reject 拒绝），**仅 admin**（roles={"admin"}），
  委托 :class:`platform_mcp.review.service.SkillReviewService`（与 Web ``POST /skills/{id}/review`` 同编排，
  触发 skill_review 邮件由 M5 挂接）；
- ``query_audit_logs``：审计日志查询（分页/时间/资源类型过滤），admin 全量、其他角色仅自己
  （同 Web ``GET /audit/logs`` 可见性）；
- ``update_profile``：个人设置（nickname / email / locale，locale 重登录生效，同 Web ``PUT /profile``）；
- ``change_password``：修改密码（校验当前密码，同 Web ``POST /profile/change-password``）。

传输适配复用 :mod:`platform_mcp.skills.ecosystem` 的会话编排 / 身份贯通 / locale 消息。审计口令类
操作（改密）不落明文（request_summary 仅记动作，密码参数不入审计——见 context._build_request_summary）。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.audit.service import query_logs
from platform_mcp.auth.models import PmcpUser
from platform_mcp.auth.service import hash_password, verify_password
from platform_mcp.common.exceptions import SkillError
from platform_mcp.i18n import SUPPORTED_LOCALES
from platform_mcp.mcp_server.skill.decorator import register_skill
from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.review.service import (
    CODE_INVALID_STATE,
    ReviewActor,
    SkillReviewError,
    SkillReviewService,
)
from platform_mcp.skills.ecosystem import (
    _build_actor,
    _format_review_result,
    _localized,
    _session_scope,
)

_TOOL_NAMES = {
    "review_skill",
    "query_audit_logs",
    "update_profile",
    "change_password",
}

_REVIEW_ACTIONS = ("approve", "merge", "reject")


def _build_tool_meta() -> list[ToolMeta]:
    return [
        ToolMeta(
            tool_name="review_skill",
            display_name="广场审核",
            description=(
                "【仅 admin】审核提交到广场的 Skill：action=approve（新增入广场）/ merge（合并到广场已有 "
                "Skill，含迭代说明）/ reject（拒绝，含原因 comment）。委托与 Web 审核弹窗同一编排（8 状态机 + "
                "广场副本 upsert + 审计），审核后触发 skill_review 邮件通知（M5 挂接） / [admin only] Review a"
                "skill submitted to the plaza: action=approve (publish as new) / merge (fold into an existing plaza "
                "skill, with an iteration note) / reject (with a reason in comment). Shares the same orchestration "
                "as the Web review dialog; triggers the skill_review email after review (wired in M5)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "action": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["skill_id", "action"],
            },
            risk_level="MEDIUM",
            timeout_seconds=60,
            audit_required=True,
            roles={"admin"},
        ),
        ToolMeta(
            tool_name="query_audit_logs",
            display_name="审计日志查询",
            description=(
                "查询审计日志（分页 + 时间/资源类型/风险等级/结果状态过滤）：admin 可见全量，其他角色仅见"
                "本人（operator 自动收敛为当前用户，同 Web 审计页可见性） / Query audit logs (paginated, filter by"
                "time/resource type/risk level/result status): admin sees all, other roles see only their own "
                "(operator is forced to the current user, matching the Web audit page visibility)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                    "operator": {"type": "string"},
                    "skill_name": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "resource_type": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "risk_level": {"type": "string"},
                    "result_status": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                },
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="update_profile",
            display_name="更新个人设置",
            description=(
                "更新本人个人设置：nickname（昵称）/ email（邮箱）/ locale（界面语言，仅支持 "
                "zh-CN/en-US，重登录生效，语义同 §19.5.2）；仅传需修改的字段 / Update your own profile: "
                "nickname / email / locale (UI language, only zh-CN/en-US, takes effect on next login). Pass only "
                "the fields you want to change"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "nickname": {"type": "string"},
                    "email": {"type": "string"},
                    "locale": {"type": "string"},
                },
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="change_password",
            display_name="修改密码",
            description=(
                "修改本人登录密码：校验当前密码（old_password）正确后设置为 new_password；当前密码错误返回 "
                "11004。口令经加密存储，明文不落审计 / Change your own login password: verifies the current "
                "password (old_password) before setting new_password; a wrong current password returns 11004. "
                "Passwords are stored hashed and never written to the audit log in plaintext"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "old_password": {"type": "string"},
                    "new_password": {"type": "string"},
                },
                "required": ["old_password", "new_password"],
            },
            risk_level="MEDIUM",
            timeout_seconds=30,
            audit_required=True,
        ),
    ]


@register_skill("skill_account")
class SkillAccountToolsSkill:
    """账户/审核双通道工具集（MCP 传输适配层，业务委托审核/审计/认证服务）。"""

    def skill_name(self) -> str:
        return "skill_account"

    def list_tools(self) -> list[ToolMeta]:
        return _build_tool_meta()

    async def validate(self, tool_name: str, params: dict) -> dict:
        if tool_name == "review_skill":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
            if params.get("action") not in _REVIEW_ACTIONS:
                raise SkillError("action 必须为 approve/merge/reject")
        elif tool_name == "update_profile":
            locale = params.get("locale")
            if locale is not None and locale not in SUPPORTED_LOCALES:
                raise SkillError(f"locale 仅支持 {'/'.join(SUPPORTED_LOCALES)}")
            if all(params.get(k) is None for k in ("nickname", "email", "locale")):
                raise SkillError("至少提供 nickname / email / locale 之一")
        elif tool_name == "change_password":
            if not params.get("old_password"):
                raise SkillError("old_password 参数必填")
            if not params.get("new_password"):
                raise SkillError("new_password 参数必填")
        return params

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any:
        if tool_name == "review_skill":
            return await self._review_skill(params, context)
        if tool_name == "query_audit_logs":
            return await self._query_audit_logs(params, context)
        if tool_name == "update_profile":
            return await self._update_profile(params, context)
        if tool_name == "change_password":
            return await self._change_password(params, context)
        raise NotImplementedError(f"Tool {tool_name} 未实现")

    def support(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # --- Tool 实现 ---

    async def _review_skill(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        action = str(params["action"])
        comment = params.get("comment")
        async with _session_scope() as session:
            service = SkillReviewService(session)
            result = await service.review(actor, skill_id, action, comment=comment)  # type: ignore[arg-type]
            logger.info(
                "MCP review_skill: skill_id={} action={} admin={} → {}",
                skill_id, action, actor.username, result.new_status,
            )
            return _format_review_result(
                result,
                _localized(
                    actor,
                    f"审核完成（{action}）：{result.old_status} → {result.new_status}",
                    f"Review completed ({action}): {result.old_status} → {result.new_status}",
                ),
            )

    async def _query_audit_logs(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        page = int(params.get("page") or 1)
        page_size = int(params.get("page_size") or 20)
        operator = params.get("operator")
        # 非 admin 仅见自己（同 Web GET /audit/logs 可见性收敛）
        if not actor.is_admin:
            operator = actor.username
        async with _session_scope() as session:
            items, total = await query_logs(
                session,
                page=page,
                page_size=page_size,
                operator=operator,
                skill_name=params.get("skill_name"),
                tool_name=params.get("tool_name"),
                resource_type=params.get("resource_type"),
                resource_id=params.get("resource_id"),
                risk_level=params.get("risk_level"),
                result_status=params.get("result_status"),
                start_time=params.get("start_time"),
                end_time=params.get("end_time"),
            )
            return {
                "success": True,
                "total": total,
                "page": page,
                "page_size": page_size,
                "scope": "all" if actor.is_admin else "self",
                "items": items,
                "message": _localized(
                    actor,
                    f"审计日志 {total} 条（{'全量' if actor.is_admin else '仅本人'}）",
                    f"{total} audit log(s) ({'all' if actor.is_admin else 'yours only'})",
                ),
            }

    async def _update_profile(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        nickname = params.get("nickname")
        email = params.get("email")
        locale = params.get("locale")
        async with _session_scope() as session:
            user = await session.get(PmcpUser, actor.user_id) if actor.user_id else None
            if user is None:
                raise SkillReviewError("用户不存在", code=CODE_INVALID_STATE)
            changes: list[str] = []
            if nickname is not None:
                user.nickname = nickname
                changes.append(f"nickname={nickname}")
            if email is not None:
                user.email = email
                changes.append(f"email={email}")
            if locale is not None:
                user.locale = locale
                changes.append(f"locale={locale}")
            await session.flush()
            await write_audit_log(
                trace_id=actor.trace_id,
                operator=actor.username,
                resource_type="permission",
                resource_id=str(actor.user_id),
                request_summary=f"更新个人资料（MCP）: {', '.join(changes) if changes else '无'}",
                result_status="success",
                extra_data={"changes": changes, "channel": "mcp"},
            )
            return {
                "success": True,
                "changes": changes,
                "message": _localized(
                    actor,
                    "个人资料已更新（locale 重登录生效）",
                    "Profile updated (locale takes effect on next login)",
                ),
            }

    async def _change_password(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        old_password = str(params["old_password"])
        new_password = str(params["new_password"])
        async with _session_scope() as session:
            user = await session.get(PmcpUser, actor.user_id) if actor.user_id else None
            if user is None:
                raise SkillReviewError("用户不存在", code=CODE_INVALID_STATE)
            if not verify_password(old_password, user.password):
                # 失败也留痕（不含明文口令），与 Web 一致返回 11004
                await write_audit_log(
                    trace_id=actor.trace_id,
                    operator=actor.username,
                    resource_type="permission",
                    resource_id=str(actor.user_id),
                    request_summary="修改密码失败：当前密码错误（MCP）",
                    result_status="error",
                    error_code="11004",
                    error_message="当前密码错误",
                )
                raise SkillReviewError("当前密码错误", code=11004)
            user.password = hash_password(new_password)
            await session.flush()
            await write_audit_log(
                trace_id=actor.trace_id,
                operator=actor.username,
                resource_type="permission",
                resource_id=str(actor.user_id),
                request_summary="修改个人密码（MCP）",
                result_status="success",
                extra_data={"channel": "mcp"},
            )
            return {
                "success": True,
                "message": _localized(actor, "密码修改成功", "Password changed successfully"),
            }
