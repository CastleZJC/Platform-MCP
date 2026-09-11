"""Skill 生态账户/审核 MCP 工具（V3.0 M3.5，架构 §19.5.4 / §19.5.7，双端承接）

承接 Web 侧的广场审核与审计查询功能到 MCP 通道（除四类“仅 Web”外双端均可操作），
业务委托既有服务，避免装饰性直改：

- ``review_skill``：广场审核（approve 新增 / merge 合并 / reject 拒绝），**仅 admin**（roles={"admin"}），
  委托 :class:`platform_mcp.review.service.SkillReviewService`（与 Web ``POST /skills/{id}/review`` 同编排，
  触发 skill_review 邮件由 M5 挂接）；merge 可带 ``target_plaza_id`` 显式指定目标广场（原创并入场景①）；
- ``build_merge_version`` / ``publish_merge_version``：广场 merge 工作台（设计定稿④，2026-09-10），
  **仅 admin**，委托 :mod:`platform_mcp.skills.merge_service`（临时包 + 冲突清单 + 🔴 终审阻断 +
  发布全链路，与 Web ``/plaza/merge/*`` 端点同编排）；
- ``query_audit_logs``：审计日志查询（分页/时间/资源类型过滤），admin 全量、其他角色仅自己
  （同 Web ``GET /audit/logs`` 可见性）。

个人设置（nickname/email/locale/密码）自 2026-09-09 起仅限 Web 端（原 update_profile /
change_password 工具移除，“其他标签页仅限 Web”口径对齐）。

传输适配复用 :mod:`platform_mcp.skills.ecosystem` 的会话编排 / 身份贯通 / locale 消息。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from platform_mcp.audit.service import query_logs
from platform_mcp.common.exceptions import SkillError
from platform_mcp.mcp_server.skill.decorator import register_skill
from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.review.service import SkillReviewService
from platform_mcp.skills.ecosystem import (
    _artifact_fields,
    _build_actor,
    _format_review_result,
    _localized,
    _session_scope,
)

_TOOL_NAMES = {
    "review_skill",
    "build_merge_version",
    "publish_merge_version",
    "query_audit_logs",
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
                    "iteration_note": {"type": "string"},
                    "target_plaza_id": {"type": "integer"},
                },
                "required": ["skill_id", "action"],
            },
            risk_level="MEDIUM",
            timeout_seconds=60,
            audit_required=True,
            roles={"admin"},
        ),
        ToolMeta(
            tool_name="build_merge_version",
            display_name="构建合并版本",
            description=(
                "【仅 admin】merge 工作台第一步：把一个或多个个人 Skill 与广场基线（当前快照 / 指定历史版本 "
                "base_version / 源复制时版本）做文件级并集，生成临时合并包（merge_token）。多源同路径内容"
                "不同记入冲突清单（默认主源=源列表首位）；14 条合规审计预跑（摘要入 audit_summary）。之后可用"
                "get_skill_file(merge_token=...) 试用，再用 publish_merge_version 发布或丢弃 / [admin only] "
                "Merge workbench step 1: build a file-level union of one or more personal skills onto the plaza "
                "baseline (current snapshot / a historical base_version / the copied-from version), producing a "
                "temp merge package (merge_token). Same-path conflicts across sources are listed (default = primary "
                "source, the first in the list); the 14 compliance rules are pre-run into audit_summary. Trial it "
                "via get_skill_file(merge_token=...), then publish or discard with publish_merge_version"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plaza_id": {"type": "integer"},
                    "source_skill_ids": {"type": "array", "items": {"type": "integer"}},
                    "base_version": {"type": "string"},
                    "target_version": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["plaza_id", "source_skill_ids"],
            },
            risk_level="MEDIUM",
            timeout_seconds=120,
            audit_required=True,
            roles={"admin"},
        ),
        ToolMeta(
            tool_name="publish_merge_version",
            display_name="发布/丢弃合并版本",
            description=(
                "【仅 admin】merge 工作台第二步：action=publish 应用逐文件裁决 resolutions（{path: "
                "source_skill_id|\"base\"}，仅冲突路径）→ 14 条终审重放（🔴 严重命中阻断）→ 覆盖广场快照 + "
                "版本归档（广场 +patch，提交人版本存 source_version）→ 广场 description 取主源 → 持有者副本批量"
                "置迭代态 → skill_review 组通知；action=discard 丢弃临时包。发布后临时包清理，merge_token 失效 "
                "/ [admin only] Merge workbench step 2: action=publish applies per-file resolutions ({path: "
                "source_skill_id|\"base\"}, conflict paths only), replays the 14 rules (critical hits BLOCK), "
                "overwrites the plaza snapshot, archives the new +patch version (submitter version kept as "
                "source_version), refreshes the plaza description from the primary source, marks holder copies for "
                "iteration and notifies the skill_review group; action=discard drops the temp package. After either "
                "terminal action the merge_token is invalidated"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "merge_token": {"type": "string"},
                    "action": {"type": "string", "enum": ["publish", "discard"]},
                    "resolutions": {"type": "object"},
                    "target_version": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["merge_token", "action"],
            },
            risk_level="HIGH",
            timeout_seconds=180,
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
        elif tool_name == "build_merge_version":
            if params.get("plaza_id") is None:
                raise SkillError("plaza_id 参数必填")
            if not params.get("source_skill_ids"):
                raise SkillError("source_skill_ids 参数必填（至少一个来源 Skill）")
        elif tool_name == "publish_merge_version":
            if not params.get("merge_token"):
                raise SkillError("merge_token 参数必填")
            if params.get("action") not in ("publish", "discard"):
                raise SkillError("action 必须为 publish/discard")
        return params

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any:
        if tool_name == "review_skill":
            return await self._review_skill(params, context)
        if tool_name == "build_merge_version":
            return await self._build_merge_version(params, context)
        if tool_name == "publish_merge_version":
            return await self._publish_merge_version(params, context)
        if tool_name == "query_audit_logs":
            return await self._query_audit_logs(params, context)
        raise NotImplementedError(f"Tool {tool_name} 未实现")

    def support(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # --- Tool 实现 ---

    async def _review_skill(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        action = str(params["action"])
        comment = params.get("comment")
        target_plaza_id = params.get("target_plaza_id")
        async with _session_scope() as session:
            service = SkillReviewService(session)
            result = await service.review(
                actor,
                skill_id,
                action,  # type: ignore[arg-type]
                comment=comment,
                iteration_note=params.get("iteration_note"),
                target_plaza_id=int(target_plaza_id) if target_plaza_id is not None else None,
            )
            logger.info(
                "MCP review_skill: skill_id={} action={} admin={} → {}",
                skill_id, action, actor.username, result.new_status,
            )
            return {
                **_format_review_result(
                    result,
                    _localized(
                        actor,
                        f"审核完成（{action}）：{result.old_status} → {result.new_status}",
                        f"Review completed ({action}): {result.old_status} → {result.new_status}",
                    ),
                ),
                # 批次 5.1：admin 审核当时经 CC 可直接补足外部产物（设计定稿⑧）
                **await _artifact_fields(session, skill_id, actor.locale),
            }

    async def _build_merge_version(self, params: dict, context: Any) -> dict:
        from platform_mcp.skills.merge_service import build_merge_version

        actor = _build_actor(context)
        async with _session_scope() as session:
            result = await build_merge_version(
                session,
                plaza_id=int(params["plaza_id"]),
                source_skill_ids=[int(s) for s in params["source_skill_ids"]],
                actor=actor,
                base_version=params.get("base_version"),
                target_version=params.get("target_version"),
                comment=params.get("comment"),
            )
            logger.info(
                "MCP build_merge_version: plaza={} sources={} conflicts={}",
                result["plaza_id"], len(result["source_skills"]), len(result["conflicts"]),
            )
            result["message"] = _localized(
                actor,
                "合并临时包已构建：可 get_skill_file(merge_token=...) 试用，publish_merge_version 发布/丢弃",
                "Merge package built: trial via get_skill_file(merge_token=...), then publish_merge_version",
            )
            return {"success": True, **result}

    async def _publish_merge_version(self, params: dict, context: Any) -> dict:
        from platform_mcp.skills.merge_service import publish_merge_version

        actor = _build_actor(context)
        action = str(params["action"])
        async with _session_scope() as session:
            result = await publish_merge_version(
                session,
                merge_token=str(params["merge_token"]),
                action=action,  # type: ignore[arg-type]
                actor=actor,
                resolutions=params.get("resolutions"),
                target_version=params.get("target_version"),
                comment=params.get("comment"),
            )
            logger.info(
                "MCP publish_merge_version: token={} action={} → {}",
                params["merge_token"], action, result.get("status"),
            )
            if action == "discard":
                result["message"] = _localized(actor, "合并已丢弃", "Merge discarded")
            else:
                result["message"] = _localized(
                    actor,
                    f"合并已发布为 v{result.get('new_version')}（持有者标记 {result.get('holders_marked', 0)} 个副本）",
                    f"Merge published as v{result.get('new_version')} "
                    f"({result.get('holders_marked', 0)} holder copies marked)",
                )
            return {"success": True, **result}

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
