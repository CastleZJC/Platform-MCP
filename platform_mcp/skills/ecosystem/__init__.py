"""Skill 生态 MCP 工具（V3.0 M2.4 + M4，架构 §19.5.3 / §19.5.7 / 计划 M2.4、M4.2、F-29~F-32、F-36）

CC 经 MCP 双通道管理个人库 Skill 生命周期：

- ``create_skill_draft``：创建草稿（自动扫广场相似推荐，F-29）；
- ``update_my_skill``：更新自己的 Skill（仅本人；广场副本独立表不受未审核更新影响，F-29）；
- ``submit_skill_for_review``：提交分享审核（重复分享二次确认覆盖，F-31）；
- ``withdraw_review``：撤回审核（仅审核中可撤回）；
- ``set_my_skill_status``：启停自己的 Skill（仅本人；ENABLED↔DISABLED，PENDING_REVIEW 停用视同
  撤回 F-32；内置装饰器与广场复制 origin=PLAZA 除外——仅 admin Web 端调整）；
- ``resolve_share_iteration``：分享迭代解决（迭代 / 保留，F-30；iterate 为 M4.3 内容级覆盖）；
- ``submit_skill_artifact``（M4）：外部大模型（glm 5.3）产物回传——中英 README / 审核报告经
  平台重放 14 条审计 + 脱敏校验后入档（``generated_by=external``，F-36）；
- ``get_skill_iteration_diff``（M4）：分享迭代差异素材（行级 diff + 语义相似度 + 性能提示，
  M4.4），供 CC 侧外部大模型生成自然语言差异描述。

状态转移、广场联动与业务审计委托 :class:`platform_mcp.review.service.SkillReviewService`
（Web/MCP 双通道共用）；本模块为 MCP 传输适配层：身份贯通（``ReviewActor``）、会话编排
（``mutate + flush`` → 统一 commit）、结果格式化（统一 ``data`` 结构）、成功消息按 ``locale`` 返回。

边界：``ToolMeta.roles`` 角色动态过滤与其余生态工具（search/suggest/readme/add/remove/list/block）
属 M3.5；create/update 的双语报告/README 版本化存档属 M2.5/M4（本模块先落审计重放与模板兜底）。
"""

from __future__ import annotations

import base64
import binascii
import re
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Any, AsyncIterator

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.common.database import get_session_factory
from platform_mcp.common.exceptions import SkillError
from platform_mcp.common.runtime_config import runtime_config
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
from platform_mcp.skills.llm import (
    GENERATED_BY_EXTERNAL,
    PERFORMANCE_HINT_EN,
    PERFORMANCE_HINT_ZH,
)
from platform_mcp.skills.llm.generation import (
    ARTIFACT_FILENAMES,
    read_package_skill_md,
    replay_validate_artifact,
)
from platform_mcp.skills.models import PmcpSkillVersion
from platform_mcp.skills.personal import rename_my_skill
from platform_mcp.skills.plaza import scan_plaza_similar
from platform_mcp.skills.versioning import (
    archive_skill_version,
    audit_result_from_summary,
    build_artifact_hint,
    generate_bilingual_readme,
    generate_bilingual_report,
    latest_version_archive,
)

_TOOL_NAMES = {
    "create_skill_draft",
    "update_my_skill",
    "submit_skill_for_review",
    "withdraw_review",
    "set_my_skill_status",
    "resolve_share_iteration",
    "submit_skill_artifact",
    "get_skill_iteration_diff",
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


async def _artifact_fields(db: AsyncSession, skill_id: int, locale: str | None) -> dict:
    """MCP 响应补足字段（批次 5.1）：最新存档 ``generated_by`` + template/model 级补足提示。"""
    latest = await latest_version_archive(db, skill_id)
    generated_by = latest.generated_by if latest else None
    return {
        "generated_by": generated_by,
        "artifact_hint": build_artifact_hint(generated_by, locale),
    }


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


def _decode_attachments(params: dict) -> list[tuple[str, bytes]] | None:
    """MCP 通道附件解码：``[{path, content_base64}]`` → ``[(包内相对路径, bytes)]``。

    与 Web 上传同一上限来源（运行时配置 ``skill.max_upload_size_mb``，热切换）；路径仅允许
    包内相对路径（绝对路径 / 盘符 / 穿越一律拒绝）。附件随 SKILL.md 一并落盘进 14 条审计
    扫描范围（平台只存档不执行，任意格式文档/脚本/图片均为惰性数据）。
    """
    raw = params.get("attachments")
    if not raw:
        return None
    cap_mb = int(runtime_config.get_sync("skill.max_upload_size_mb"))
    cap = cap_mb * 1024 * 1024
    decoded: list[tuple[str, bytes]] = []
    total = 0
    for item in raw:
        rel = str(item.get("path") or "").strip().replace("\\", "/")
        posix = PurePosixPath(rel)
        if not rel or ":" in rel or posix.is_absolute() or ".." in posix.parts or not posix.name:
            raise SkillError(f"附件路径非法：{rel}（仅允许包内相对路径，禁止穿越）")
        try:
            data = base64.b64decode(str(item.get("content_base64") or ""))
        except (binascii.Error, ValueError) as exc:
            raise SkillError(f"附件 {rel} base64 解码失败") from exc
        total += len(data)
        if total > cap:
            raise SkillError(f"附件总量超限（最大 {cap_mb}MB，skill.max_upload_size_mb 热切换）")
        decoded.append((str(posix), data))
    return decoded


def _build_tool_meta() -> list[ToolMeta]:
    return [
        ToolMeta(
            tool_name="create_skill_draft",
            display_name="创建Skill草稿",
            description=(
                "在个人库创建 Skill 草稿（status=DRAFT）：传入 skill_code/skill_name/SKILL.md 文本内容，"
                "平台落盘存档并重放 14 条合规审计（第一道审核），自动扫描广场已发布 Skill 给出"
                "相似推荐（merge 合并 / new 新增结论素材）；草稿仅本人可见与经 MCP 使用，可后续 update_my_skill "
                "迭代、submit_skill_for_review 提交分享 / Create a Skill draft in your personal library "
                "(status=DRAFT): pass skill_code/skill_name and the SKILL.md text; the platform archives it, "
                "replays the 14 compliance audit rules (first review gate), and automatically scans "
                "the published plaza for similar skills (merge/new recommendation). The draft is visible and "
                "MCP-usable only by you; iterate later via update_my_skill and share via "
                "submit_skill_for_review. Optional: README text plus attachments "
                "[{path, content_base64}] (references/scripts/images; total <= "
                "skill.max_upload_size_mb, same cap as Web upload)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_code": {"type": "string"},
                    "skill_name": {"type": "string"},
                    "skill_md": {"type": "string"},
                    "description": {"type": "string"},
                    "version": {"type": "string", "default": "0.1.0"},
                    "readme": {"type": "string", "description": "可选 README.md 原文（缺失时模板生成）"},
                    "attachments": {
                        "type": "array",
                        "description": (
                            "随包附件 references/脚本/图片等：[{path: 包内相对路径, content_base64}]，"
                            "总量 ≤ skill.max_upload_size_mb（与 Web 上传同限）"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content_base64": {"type": "string"},
                            },
                            "required": ["path", "content_base64"],
                        },
                    },
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
                "传入 skill_md 则重新落盘并重放审计（可携 readme 原文与 attachments 附件，须与 skill_md 一同传入）；"
                "可传 skill_code 重命名（批次 6.1：仅限未分享、非广场复制、非内置且稳定态——DRAFT/REJECTED/"
                "WITHDRAWN/ENABLED/DISABLED，磁盘目录同步改名，新码被占返回 10003）；"
                "已拒绝(REJECTED)/撤回(WITHDRAWN)状态更新内容后自动回到草稿"
                "(DRAFT)以便重新提交；审核中/分享迭代须先撤回或解决迭代。广场副本为独立表，未过审更新不影响广场 "
                "已发布版本 / Update a Skill in your own personal library (yours only; cannot update others'): "
                "change skill_name/description/version, and pass skill_md to re-archive and replay the audit; "
                "optionally pass skill_code to rename (unshared, non-plaza-copy, built-in-free skills in stable "
                "states only — DRAFT/REJECTED/WITHDRAWN/ENABLED/DISABLED; the disk directory is renamed in step, "
                "an occupied code returns 10003); "
                "updating a REJECTED/WITHDRAWN skill returns it to DRAFT for resubmission; skills under review or "
                "in share-iteration must be withdrawn/resolved first. The plaza copy is a separate table, so an "
                "unreviewed update never affects the published plaza version"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "skill_code": {
                        "type": "string",
                        "description": "可选新 skill_code（重命名：未分享/非广场复制/稳定态，磁盘目录同步改名）",
                    },
                    "skill_name": {"type": "string"},
                    "description": {"type": "string"},
                    "skill_md": {"type": "string"},
                    "version": {"type": "string"},
                    "readme": {"type": "string", "description": "可选 README.md 原文（须与 skill_md 一同传入）"},
                    "attachments": {
                        "type": "array",
                        "description": (
                            "随包附件（须与 skill_md 一同传入，覆盖式重新落盘）："
                            "[{path: 包内相对路径, content_base64}]，总量 ≤ skill.max_upload_size_mb"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content_base64": {"type": "string"},
                            },
                            "required": ["path", "content_base64"],
                        },
                    },
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
                "覆盖上一版本并重新通知审核组（F-31） / Submit your Skill for plaza share review "
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
                "修改并重新提交；邮件通知 admin 审核组（M5 挂接）。已启用 Skill 的停用视同撤回可经 "
                "set_my_skill_status 或 Web 启停（F-32） / Withdraw a submitted Skill still under review "
                "(PENDING_REVIEW → WITHDRAWN); afterwards "
                "modify via update_my_skill and resubmit. Notifies the admin review group by email (wired in M5). "
                "Disabling an already-submitted skill counts as withdrawal (F-32), via set_my_skill_status "
                "or the Web enable/disable"
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
            tool_name="set_my_skill_status",
            display_name="启停我的Skill",
            description=(
                "启停个人库自己的 Skill（仅本人）：status=ENABLED（DISABLED→ENABLED）或 DISABLED"
                "（ENABLED→DISABLED；PENDING_REVIEW 停用视同撤回 F-32，撤回后可恢复为草稿重新编辑提交）。"
                "内置装饰器 Skill 与广场复制（origin=PLAZA）不经此通道，仅支持 admin 在 Web 端调整；"
                "非法转移返回 10003 / Enable or disable your own personal skill (owner only): "
                "status=ENABLED (DISABLED→ENABLED) or DISABLED (ENABLED→DISABLED; disabling a "
                "PENDING_REVIEW skill counts as withdrawal, F-32). Built-in decorator skills and plaza "
                "copies (origin=PLAZA) are excluded — admin adjusts them via Web only; invalid "
                "transitions return 10003"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["ENABLED", "DISABLED"]},
                },
                "required": ["skill_id", "status"],
            },
            risk_level="LOW",
            timeout_seconds=30,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="resolve_share_iteration",
            display_name="解决分享迭代",
            description=(
                "admin 合并到广场已有 Skill 后（SHARE_ITERATION），由本人选择：choice=iterate 采纳合并"
                "（M4.3 内容级覆盖：广场快照复制回本地 + 重放审计 + 版本存档）/ choice=keep 保留本地忽略本次"
                "迭代；解决后状态=已启用 ENABLED（F-30） / After admin merges into an existing plaza skill "
                "(SHARE_ITERATION), the owner chooses: choice=iterate to accept the merge (M4.3 content-level "
                "overwrite: plaza snapshot restored to local + audit replay + version archive) or choice=keep "
                "to keep local; the status becomes ENABLED after resolution (F-30)"
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
            timeout_seconds=60,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="submit_skill_artifact",
            display_name="回传模型产物",
            description=(
                "外部大模型（如 glm 5.3）产物回传（F-36）：把 CC 侧生成/润色的中英 README 或中英审核报告"
                "文本回传平台，经 14 条审计重放校验后写入当前版本存档（generated_by=external）；"
                "🔴 严重命中拒绝（返回违规清单，修复后可重传），🟡/🟢 透传接受；仅本人可回传，"
                "content_zh/content_en 至少一项 / Submit an external-LLM artifact (e.g., glm 5.3) for "
                "replay validation and archiving (F-36): pass the CC-generated bilingual README or review "
                "report text; the platform replays the 14 audit rules and archives it into the "
                "current version record (generated_by=external). Critical hits reject with a violation list "
                "(fix and resubmit); warnings/suggestions pass through. Owner only; at least one of "
                "content_zh/content_en"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer"},
                    "artifact_type": {"type": "string", "description": "readme | report"},
                    "content_zh": {"type": "string"},
                    "content_en": {"type": "string"},
                },
                "required": ["skill_id", "artifact_type"],
            },
            risk_level="LOW",
            timeout_seconds=60,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="get_skill_iteration_diff",
            display_name="获取迭代差异素材",
            description=(
                "分享迭代差异素材（M4.3/M4.4，F-30）：返回本地 vs 广场快照 SKILL.md 的行级 unified diff、"
                "行统计与语义相似度（BGE-M3 / 降级哈希），附性能提示（本地模型性能有限，建议外部大模型）；"
                "请用外部大模型（如 glm 5.3）基于素材生成自然语言差异描述，再经 resolve_share_iteration "
                "做出选择；仅本人、仅 SHARE_ITERATION 态 / Iteration diff material (M4.3/M4.4, F-30): "
                "returns the line-level unified diff, line stats and semantic similarity between the local "
                "and plaza-snapshot SKILL.md, plus a performance hint (local model is limited; an external "
                "LLM is recommended). Turn the material into a natural-language description with an external "
                "model (e.g., glm 5.3) and then decide via resolve_share_iteration; owner only, SHARE_ITERATION "
                "state only"
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
        elif tool_name == "set_my_skill_status":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
            if params.get("status") not in ("ENABLED", "DISABLED"):
                raise SkillError("status 必须为 ENABLED 或 DISABLED")
        elif tool_name == "resolve_share_iteration":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
            if params.get("choice") not in ("iterate", "keep"):
                raise SkillError("choice 必须为 iterate 或 keep")
        elif tool_name == "submit_skill_artifact":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
            if params.get("artifact_type") not in ARTIFACT_FILENAMES:
                raise SkillError("artifact_type 必须为 readme 或 report")
            if not (params.get("content_zh") or params.get("content_en") or params.get("content_extra")):
                raise SkillError("content_zh / content_en / content_extra 至少一项非空")
            extra = params.get("content_extra")
            if extra is not None:
                if not isinstance(extra, dict) or not extra:
                    raise SkillError("content_extra 须为非空 {locale: text} 对象")
                for key, text in extra.items():
                    if (
                        not isinstance(key, str)
                        or not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", key)
                        or not isinstance(text, str)
                        or not text.strip()
                    ):
                        raise SkillError(
                            f"content_extra 条目非法：{key!r}（locale 须为语言标签、文本非空）"
                        )
                    if key.lower() in {"zh", "zh-cn", "en", "en-us"}:
                        raise SkillError(
                            f"content_extra 不接受 {key}（zh/en 走 content_zh / content_en 主列）"
                        )
        elif tool_name == "get_skill_iteration_diff":
            if params.get("skill_id") is None:
                raise SkillError("skill_id 参数必填")
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
        if tool_name == "set_my_skill_status":
            return await self._set_my_skill_status(params, context)
        if tool_name == "resolve_share_iteration":
            return await self._resolve_share_iteration(params, context)
        if tool_name == "submit_skill_artifact":
            return await self._submit_skill_artifact(params, context)
        if tool_name == "get_skill_iteration_diff":
            return await self._get_skill_iteration_diff(params, context)
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
                readme=params.get("readme"),
                attachments=_decode_attachments(params),
            )
            similar = await scan_plaza_similar(session, skill_name, description, user_id=actor.user_id)

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
            audit_snapshot = draft.audit_result.to_audit_summary()
            if draft.path_adjustments:
                audit_snapshot["path_adjustments"] = draft.path_adjustments
            record = await archive_skill_version(
                session, skill_id=skill.id, version=version, checksum=draft.source_checksum,
                readme_zh=draft.readme_zh, readme_en=draft.readme_en,
                report_zh=report_zh, report_en=report_en,
                audit_snapshot=audit_snapshot,
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
                "path_adjustments": draft.path_adjustments,
                "generated_by": record.generated_by,
                "artifact_hint": build_artifact_hint(record.generated_by, actor.locale),
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

            # 批次 6.1：可选改编码（条件矩阵/唯一性/磁盘目录改名统一在 personal.rename_my_skill）
            new_skill_code = str(params.get("skill_code") or "").strip() or None
            if new_skill_code and new_skill_code != skill.skill_code:
                await rename_my_skill(session, skill_id, new_skill_code, actor, channel="mcp")

            skill_name = str(params.get("skill_name") or skill.skill_name)
            description = params.get("description") if params.get("description") is not None else skill.description
            version = str(params.get("version") or skill.version or "0.1.0")
            skill_md = params.get("skill_md")

            draft: DraftBuildResult | None = None
            audit_summary = skill.audit_result
            audit_status = skill.audit_status
            if (params.get("attachments") or params.get("readme")) and not skill_md:
                raise SkillError("附件/README 须与 skill_md 一同传入（覆盖式重新落盘全量包）")
            if skill_md:
                draft = build_draft_content(
                    skill_code=skill.skill_code,
                    skill_name=skill_name,
                    description=description,
                    skill_md=str(skill_md),
                    version=version,
                    readme=params.get("readme"),
                    attachments=_decode_attachments(params),
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
                session, skill.skill_name, skill.description,
                exclude_skill_code=skill.skill_code, user_id=actor.user_id,
            )
            report_zh, report_en = generate_bilingual_report(
                skill_code=skill.skill_code, skill_name=skill.skill_name, description=skill.description,
                version=skill.version, audit_result=arc_audit, similar_skills=arc_similar,
            )
            arc_snapshot = arc_audit.to_audit_summary()
            if draft is not None and draft.path_adjustments:
                arc_snapshot["path_adjustments"] = draft.path_adjustments
            record = await archive_skill_version(
                session, skill_id=skill.id, version=skill.version, checksum=arc_checksum,
                readme_zh=arc_readme_zh, readme_en=arc_readme_en,
                report_zh=report_zh, report_en=report_en,
                audit_snapshot=arc_snapshot,
                operator=actor.username,
                # 内容变更（新 skill_md）重存档：旧 extra 译文已过时，显式清空；
                # 仅元数据更新（draft=None）保留既有补档。
                reset_extra=draft is not None,
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
                "generated_by": record.generated_by,
                "artifact_hint": build_artifact_hint(record.generated_by, actor.locale),
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
            return {
                **_format_review_result(
                    result,
                    _localized(
                        actor,
                        f"已提交分享审核（{result.old_status} → {result.new_status}），等待 admin 审核",
                        f"Submitted for share review ({result.old_status} → {result.new_status}); pending admin review",
                    ),
                ),
                **await _artifact_fields(session, skill_id, actor.locale),
            }

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

    async def _set_my_skill_status(self, params: dict, context: Any) -> dict:
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        enabled = str(params["status"]) == "ENABLED"
        async with _session_scope() as session:
            skill: PmcpSkill | None = await session.get(PmcpSkill, skill_id)
            if skill is None:
                raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
            if skill.register_method == "decorator":
                raise SkillReviewError(
                    "内置装饰器 Skill 仅支持 admin 在 Web 端调整", code=CODE_INVALID_STATE
                )
            if skill.origin == "PLAZA":
                raise SkillReviewError(
                    "广场复制 Skill（origin=PLAZA）仅支持 admin 在 Web 端调整", code=CODE_INVALID_STATE
                )
            service = SkillReviewService(session)
            result = await service.set_enabled(actor, skill_id, enabled)
            return _format_review_result(
                result,
                _localized(
                    actor,
                    f"Skill 已{'启用' if enabled else '停用'}（{result.old_status} → {result.new_status}）",
                    f"Skill {'enabled' if enabled else 'disabled'} "
                    f"({result.old_status} → {result.new_status})",
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
                    (
                        f"分享迭代已解决（{choice}），状态=已启用；"
                        + ("广场内容已覆盖本地并重放审计" if choice == "iterate" else "本地内容保持不变")
                    ),
                    f"Share iteration resolved ({choice}); status is now ENABLED; "
                    + (
                        "plaza content overwrote local with audit replay"
                        if choice == "iterate"
                        else "local content is unchanged"
                    ),
                ),
            )

    async def _submit_skill_artifact(self, params: dict, context: Any) -> dict:
        """外部大模型产物回传（F-36 + 批次 5.2）：重放校验 → 入档（generated_by=external）。

        🔴 严重命中拒绝（success=False + 结构化违规清单，CC 修复后可重传，不抛错保留会话空转）；
        🟡/🟢 透传接受。仅传入侧覆盖（partial：另一侧保留存档现值）。权限：owner 或 admin
        （设计定稿⑧：admin 审核当时经 CC 也可直接回传补足）。``content_extra`` 为
        ``{locale: text}`` 其他语言补档（zh/en 主列专属，重放校验同 zh/en），按 locale 合并
        写入 ``readme_extra`` / ``report_extra``（分级取值见 ``pick_localized_text``）。
        """
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        artifact_type = str(params["artifact_type"])
        content_zh = params.get("content_zh") or None
        content_en = params.get("content_en") or None
        content_extra: dict[str, str] = {
            str(k): str(v) for k, v in (params.get("content_extra") or {}).items()
        }
        async with _session_scope() as session:
            skill: PmcpSkill | None = await session.get(PmcpSkill, skill_id)
            if skill is None:
                raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
            if skill.inserted_by != actor.username and not actor.is_admin:
                raise SkillReviewError("无权回传他人 Skill 产物", code=CODE_FORBIDDEN)

            skill_md = read_package_skill_md(skill.source_path)
            all_violations: list[dict] = []
            rejected = False
            replay_items: list[tuple[str, str | None]] = [
                ("zh", content_zh), ("en", content_en),
                *sorted(content_extra.items()),
            ]
            for lang, content in replay_items:
                if not content:
                    continue
                passed, violations = replay_validate_artifact(
                    artifact_type=artifact_type, content=str(content),
                    skill_md=skill_md, skill_name=skill.skill_name,
                )
                for v in violations:
                    v["language"] = lang
                all_violations += violations
                if not passed:
                    rejected = True
            if rejected:
                await _audit_skill_action(
                    actor, skill, "submit_artifact_rejected", old_status=skill.status,
                    extra={
                        "artifact_type": artifact_type,
                        "generated_by": GENERATED_BY_EXTERNAL,
                        "extra_locales": sorted(content_extra),
                        "violations": [
                            {k: v.get(k) for k in ("rule_id", "severity", "language")}
                            for v in all_violations
                        ],
                    },
                )
                logger.info(
                    "MCP submit_skill_artifact 拒绝：code={} type={} violations={}",
                    skill.skill_code, artifact_type, len(all_violations),
                )
                return {
                    "success": False,
                    "skill_id": skill.id,
                    "skill_code": skill.skill_code,
                    "artifact_type": artifact_type,
                    "generated_by": GENERATED_BY_EXTERNAL,
                    "extra_locales": sorted(content_extra),
                    "violations": all_violations,
                    "message": _localized(
                        actor,
                        "产物重放校验未通过（存在 🔴 严重违规），请修复后重传",
                        "Artifact replay validation failed (critical violations); fix and resubmit",
                    ),
                }

            version = skill.version or "0.1.0"
            existing: PmcpSkillVersion | None = (
                await session.execute(
                    select(PmcpSkillVersion).where(
                        PmcpSkillVersion.skill_id == skill_id,
                        PmcpSkillVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
            # 传入侧覆盖，未传侧保留存档现值（首次无存档行时按模板重建兜底值）
            if existing is not None:
                base_readme_zh, base_readme_en = existing.readme_zh, existing.readme_en
                base_report_zh, base_report_en = existing.report_zh, existing.report_en
                audit_snapshot, checksum = existing.audit_snapshot, existing.checksum
            else:
                base_readme_zh, base_readme_en = generate_bilingual_readme(
                    skill.skill_name, skill.description, skill.source_path or "", version
                )
                audit = audit_result_from_summary(skill.audit_result, skill.skill_name)
                base_report_zh, base_report_en = generate_bilingual_report(
                    skill_code=skill.skill_code, skill_name=skill.skill_name,
                    description=skill.description, version=version, audit_result=audit,
                )
                audit_snapshot, checksum = skill.audit_result, skill.source_checksum
            if artifact_type == "readme":
                readme_zh, readme_en = content_zh or base_readme_zh, content_en or base_readme_en
                report_zh, report_en = base_report_zh, base_report_en
            else:
                readme_zh, readme_en = base_readme_zh, base_readme_en
                report_zh, report_en = content_zh or base_report_zh, content_en or base_report_en
            # content_extra 合并写入对应类型的补档列（另一类型 extra 不触碰 = 保留存档现值）
            readme_extra_new: dict[str, str] | None = None
            report_extra_new: dict[str, str] | None = None
            if content_extra:
                if artifact_type == "readme":
                    base_extra = (existing.readme_extra if existing else None) or {}
                    readme_extra_new = {**base_extra, **content_extra}
                else:
                    base_extra = (existing.report_extra if existing else None) or {}
                    report_extra_new = {**base_extra, **content_extra}
            await archive_skill_version(
                session, skill_id=skill_id, version=version, checksum=checksum,
                readme_zh=readme_zh, readme_en=readme_en,
                report_zh=report_zh, report_en=report_en,
                audit_snapshot=audit_snapshot, operator=actor.username,
                generated_by=GENERATED_BY_EXTERNAL,
                readme_extra=readme_extra_new, report_extra=report_extra_new,
            )
            languages = [lang for lang, c in (("zh", content_zh), ("en", content_en)) if c] \
                + sorted(content_extra)
            await _audit_skill_action(
                actor, skill, "submit_artifact", old_status=skill.status,
                extra={
                    "artifact_type": artifact_type,
                    "generated_by": GENERATED_BY_EXTERNAL,
                    "languages": languages,
                    "violations": [
                        {k: v.get(k) for k in ("rule_id", "severity", "language")}
                        for v in all_violations
                    ],
                },
            )
            logger.info(
                "MCP submit_skill_artifact 入档：code={} type={} langs={}",
                skill.skill_code, artifact_type, languages,
            )
            return {
                "success": True,
                "skill_id": skill.id,
                "skill_code": skill.skill_code,
                "artifact_type": artifact_type,
                "version": version,
                "generated_by": GENERATED_BY_EXTERNAL,
                "extra_locales": sorted(content_extra),
                "violations": all_violations,
                "message": _localized(
                    actor,
                    "外部模型产物已通过重放校验并入档（generated_by=external）",
                    "External-model artifact passed replay validation and was archived (generated_by=external)",
                ),
            }

    async def _get_skill_iteration_diff(self, params: dict, context: Any) -> dict:
        """分享迭代差异素材（M4.3/M4.4）：行级 diff + 语义相似度 + 性能/外部模型提示。"""
        actor = _build_actor(context)
        skill_id = int(params["skill_id"])
        async with _session_scope() as session:
            service = SkillReviewService(session)
            material = await service.build_iteration_diff_material(actor, skill_id)
            return {
                **material,
                "performance_hint": _localized(actor, PERFORMANCE_HINT_ZH, PERFORMANCE_HINT_EN),
                "external_hint": _localized(
                    actor,
                    "请用外部大模型（如 glm 5.3）基于以上差异素材生成自然语言差异描述，"
                    "再经 resolve_share_iteration 做出选择（iterate=广场内容覆盖本地 / keep=保留本地）",
                    "Turn the material above into a natural-language diff description with an external "
                    "large model (e.g., glm 5.3), then decide via resolve_share_iteration "
                    "(iterate=plaza overwrites local / keep=keep local)",
                ),
                "message": _localized(
                    actor,
                    "差异素材已返回（行级 diff + 语义相似度）",
                    "Diff material returned (line-level diff + semantic similarity)",
                ),
            }
