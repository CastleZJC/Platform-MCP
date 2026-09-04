"""可复用审核服务（V3.0 M2，架构 §19.5.3 / 计划 M2.3）

抽取 Skill 审核域的业务编排，状态转移委托 :mod:`platform_mcp.review.state_machine`
（单一事实来源），本服务负责：

- 权限与归属校验（owner 本人 / admin 审核）；
- 广场副本 upsert（approve 新增入广场 / merge 合并迭代说明 → ``pmcp_skill_plaza``）；
- ``status`` / ``share_status`` / ``plaza_id`` / ``origin`` / ``review_comment`` 联动写入；
- 审计留痕（``resource_type="skill"``，操作明细可区分，F-40）；
- 重复分享二次确认（F-31 ``confirm_reshare``）。

覆盖动作（与 §19.5.3 状态机图一一对应）：
提交分享 / admin 审核（approve 新增入广场 / merge 合并 / reject 拒绝）/ 撤回（停用视同撤回，F-32）/
分享迭代解决（迭代 / 保留，F-30）/ 修改重编辑 / 恢复 / 启停。

设计解耦：三期 KB（M6）可复用同一编排骨架（状态机 + 归属校验 + 共享联动 + 审计）。
事务边界：服务层 ``mutate + flush``，**不 commit**（与 ``process_skill_upload`` 一致，由 ``get_db`` 统一提交）；
审计经 ``write_audit_log`` 独立 session 内部 commit，不受业务事务回滚影响。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.models import PmcpUser
from platform_mcp.common.exceptions import SkillError
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.state_machine import (
    InvalidTransitionError,
    ReviewAction,
    ReviewStatus,
    owner_mcp_usable,
    transition,
    visible_in_personal_library,
)
from platform_mcp.skills.models import PmcpSkillPlaza
from platform_mcp.skills.plaza import derive_involve_flags, index_plaza_embedding

# ==== 错误码（沿用 1000x Skill 域，见 common/exceptions.SkillError 与 api 既有约定）====
CODE_NOT_FOUND = 10002        # Skill 不存在
CODE_INVALID_STATE = 10003    # 非法状态转移 / 前置条件不满足
CODE_FORBIDDEN = 10004        # 权限不足（非本人 / 非 admin）
CODE_RESHARE_CONFIRM = 10005  # 重复分享需二次确认（F-31）


class SkillReviewError(SkillError):
    """审核域业务错误。

    继承 :class:`SkillError`（→ :class:`BaseError`），融入 ``main.py`` 全局异常处理；
    ``error_code`` 沿用 1000x Skill 域，API/MCP 双通道均可捕获后转统一响应。
    """

    def __init__(self, message: str, code: int = 10001) -> None:
        super().__init__(message, error_code=code)


@dataclass
class ReviewActor:
    """审核动作发起者身份快照（与传输层解耦，Web dict / MCP context 均可构造）。"""

    username: str
    role_code: str
    user_id: int | None = None
    locale: str | None = None
    trace_id: str | None = None

    @classmethod
    def from_user_dict(cls, user: dict, trace_id: str | None = None) -> ReviewActor:
        """由 ``get_current_user`` / MCP 身份 dict 构造（键见 auth.middleware.get_current_user）。"""
        return cls(
            username=user["username"],
            role_code=user.get("role_code") or "developer",
            user_id=user.get("id"),
            locale=user.get("locale"),
            trace_id=trace_id,
        )

    @property
    def is_admin(self) -> bool:
        return self.role_code == "admin"


@dataclass
class ReviewResult:
    """审核动作结果（供 API/MCP 层格式化为统一响应，含 owner 可见的 review_comment）。"""

    skill_id: int
    skill_code: str
    action: str
    old_status: str
    new_status: str
    share_status: str
    plaza_id: int | None = None
    review_comment: str | None = None


class SkillReviewService:
    """Skill 审核域服务。以 ``AsyncSession`` 构造，方法内 ``mutate + flush`` 不 commit。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ==================== 提交 / 撤回 ====================

    async def submit_for_review(
        self,
        actor: ReviewActor,
        skill_id: int,
        *,
        confirm_reshare: bool = False,
    ) -> ReviewResult:
        """提交分享审核（owner）：DRAFT/ENABLED/DISABLED → PENDING_REVIEW。

        F-31 重复分享：已入广场或已在审核管线中时，未带 ``confirm_reshare`` 抛 10005 要求二次确认；
        确认后覆盖上一版本（审核中为覆盖式重提，状态不变；其余走 SUBMIT 转移）。
        """
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        cur = ReviewStatus(skill.status)

        already_shared = skill.share_status == "shared" or cur in {
            ReviewStatus.PENDING_REVIEW,
            ReviewStatus.APPROVED,
            ReviewStatus.SHARE_ITERATION,
        }
        if already_shared and not confirm_reshare:
            raise SkillReviewError(
                "该 Skill 已分享/正在审核中，需二次确认后覆盖上一版本并重新通知审核组",
                code=CODE_RESHARE_CONFIRM,
            )

        if cur == ReviewStatus.PENDING_REVIEW:
            # 覆盖式重提：状态不变，仅刷新留痕并（M5）重新通知审核组
            old = skill.status
            action_label = "reshare"
        else:
            old = self._apply(skill, ReviewAction.SUBMIT)
            action_label = "submit"

        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, action_label, old_status=old)
        return self._result(skill, action_label, old)

    async def withdraw(self, actor: ReviewActor, skill_id: int) -> ReviewResult:
        """撤回审核（owner）：PENDING_REVIEW → WITHDRAWN（F-32 邮件通知 admin 审核组，M5 挂接）。"""
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        if ReviewStatus(skill.status) != ReviewStatus.PENDING_REVIEW:
            raise SkillReviewError("仅审核中的 Skill 可撤回", code=CODE_INVALID_STATE)
        old = self._apply(skill, ReviewAction.WITHDRAW)
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, "withdraw", old_status=old)
        return self._result(skill, "withdraw", old)

    # ==================== admin 审核 ====================

    async def review(
        self,
        actor: ReviewActor,
        skill_id: int,
        action: Literal["approve", "merge", "reject"],
        *,
        comment: str | None = None,
        iteration_note: str | None = None,
    ) -> ReviewResult:
        """admin 广场审核（仅 PENDING_REVIEW 可审核，对应 Web 审核弹窗 / MCP ``review_skill``）。

        - ``approve``：新增入广场 —— PENDING_REVIEW → APPROVED → ENABLED（链式），upsert 广场副本，
          ``share_status='shared'``（§19.5.3「个人侧已启用，广场副本=已发布」）。
        - ``merge``：合并到广场已有 Skill —— 要求 ``origin=PLAZA``，PENDING_REVIEW → SHARE_ITERATION，
          写广场 ``iteration_note``（F-30 迭代说明）。
        - ``reject``：拒绝 —— PENDING_REVIEW → REJECTED，``review_comment`` 存拒绝原因（owner 可见，F-11）。
        """
        self._require_admin(actor)
        skill = await self._get_skill(skill_id)
        if ReviewStatus(skill.status) != ReviewStatus.PENDING_REVIEW:
            raise SkillReviewError("仅审核中的 Skill 可执行广场审核", code=CODE_INVALID_STATE)

        old = skill.status
        if action == "approve":
            self._apply(skill, ReviewAction.APPROVE)      # → APPROVED（里程碑态）
            plaza = await self._publish_to_plaza(skill, actor)
            self._apply(skill, ReviewAction.ACTIVATE)     # → ENABLED（广场副本已发布）
            skill.share_status = "shared"
            skill.review_comment = comment
            audit_action = "review_approve"
            extra: dict = {"plaza_skill_code": plaza.skill_code}
        elif action == "merge":
            if skill.origin != "PLAZA":
                raise SkillReviewError(
                    "合并仅适用于源自广场的 Skill（origin=PLAZA）；原创 Skill 请用 approve 新增入广场",
                    code=CODE_INVALID_STATE,
                )
            self._apply(skill, ReviewAction.MERGE)        # → SHARE_ITERATION
            note = iteration_note or comment
            await self._set_plaza_iteration_note(skill, actor, note)
            skill.review_comment = note
            audit_action = "review_merge"
            extra = {"iteration_note": note}
        elif action == "reject":
            self._apply(skill, ReviewAction.REJECT)       # → REJECTED
            skill.review_comment = comment
            audit_action = "review_reject"
            extra = {"reason": comment}
        else:  # pragma: no cover - Literal 已约束，防御性兜底
            raise SkillReviewError("action 必须为 approve/merge/reject", code=CODE_INVALID_STATE)

        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, audit_action, old_status=old, extra=extra)
        return self._result(skill, audit_action, old)

    # ==================== 分享迭代 / 修改 / 恢复 ====================

    async def resolve_share_iteration(
        self,
        actor: ReviewActor,
        skill_id: int,
        choice: Literal["iterate", "keep"],
    ) -> ReviewResult:
        """解决分享迭代（owner）：SHARE_ITERATION → ENABLED（F-30，选择后状态=已启用）。

        ``iterate``=采纳合并（覆盖本地，内容级 diff/合并由 M4 挂接）；``keep``=保留本地（忽略本次迭代）。
        M2.3 落地状态转移 + 选择留痕；内容级覆盖为 M4 hook。
        """
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        if ReviewStatus(skill.status) != ReviewStatus.SHARE_ITERATION:
            raise SkillReviewError("仅分享迭代中的 Skill 可解决迭代", code=CODE_INVALID_STATE)
        if choice not in ("iterate", "keep"):  # pragma: no cover - Literal 已约束
            raise SkillReviewError("choice 必须为 iterate 或 keep", code=CODE_INVALID_STATE)
        old = self._apply(skill, ReviewAction.RESOLVE_ITERATION)
        skill.updated_by = actor.username
        await self._db.flush()
        audit_action = f"resolve_iteration_{choice}"
        await self._audit(actor, skill, audit_action, old_status=old, extra={"choice": choice})
        return self._result(skill, audit_action, old)

    async def revise(self, actor: ReviewActor, skill_id: int) -> ReviewResult:
        """修改后重编辑（owner）：REJECTED → DRAFT（保留上次拒绝原因供参考，重提审时覆盖）。"""
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        old = self._apply(skill, ReviewAction.REVISE)
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, "revise", old_status=old)
        return self._result(skill, "revise", old)

    async def restore(self, actor: ReviewActor, skill_id: int) -> ReviewResult:
        """恢复（owner）：WITHDRAWN → DRAFT。"""
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        old = self._apply(skill, ReviewAction.RESTORE)
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, "restore", old_status=old)
        return self._result(skill, "restore", old)

    # ==================== 启停（含 F-32 停用视同撤回）====================

    async def set_enabled(self, actor: ReviewActor, skill_id: int, enabled: bool) -> ReviewResult:
        """创建人启停已过审 Skill（owner）。

        - ``enabled=False``：ENABLED → DISABLED；**若处于 PENDING_REVIEW（已提交未过审）则视同撤回**
          → WITHDRAWN（F-32）。
        - ``enabled=True``：DISABLED → ENABLED。
        """
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        cur = ReviewStatus(skill.status)
        if not enabled:
            if cur == ReviewStatus.PENDING_REVIEW:
                old = self._apply(skill, ReviewAction.WITHDRAW)  # 停用视同撤回
                action_label = "withdraw_via_disable"
            else:
                old = self._apply(skill, ReviewAction.DISABLE)
                action_label = "disable"
        else:
            old = self._apply(skill, ReviewAction.ENABLE)
            action_label = "enable"
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, action_label, old_status=old)
        return self._result(skill, action_label, old)

    # ==================== 可见性 / 可用性查询（F-27，供 API/MCP 复用）====================

    def is_visible_to(self, actor: ReviewActor, skill: PmcpSkill) -> bool:
        """个人库查询层可见性（委托状态机可见性矩阵，F-27）。"""
        return visible_in_personal_library(
            status=skill.status,
            share_status=skill.share_status,
            role_code=actor.role_code,
            is_owner=skill.inserted_by == actor.username,
            is_builtin=skill.register_method == "decorator",
        )

    def owner_can_use_mcp(self, skill: PmcpSkill) -> bool:
        """本人是否可经 MCP 使用该 Skill（未过审仅本人可用；拒绝/撤回/停用不可用）。"""
        return owner_mcp_usable(skill.status)

    # ==================== 私有 helper ====================

    async def _get_skill(self, skill_id: int) -> PmcpSkill:
        skill: PmcpSkill | None = await self._db.get(PmcpSkill, skill_id)
        if skill is None:
            raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
        return skill

    def _require_owner(self, skill: PmcpSkill, actor: ReviewActor) -> None:
        if skill.inserted_by != actor.username:
            raise SkillReviewError("无权操作他人 Skill", code=CODE_FORBIDDEN)

    def _require_admin(self, actor: ReviewActor) -> None:
        if not actor.is_admin:
            raise SkillReviewError("仅 admin 可执行广场审核", code=CODE_FORBIDDEN)

    def _apply(self, skill: PmcpSkill, action: ReviewAction) -> str:
        """对 skill 执行状态机动作并写回 ``status``，返回旧状态字符串。

        非法转移由状态机抛 :class:`InvalidTransitionError`，此处转 :class:`SkillReviewError`(10003)。
        """
        old = skill.status
        try:
            target = transition(old, action)
        except InvalidTransitionError as exc:
            raise SkillReviewError(f"非法状态转移：{exc}", code=CODE_INVALID_STATE) from exc
        skill.status = target.value
        return old

    async def _resolve_user_id(self, username: str | None) -> int | None:
        """username → user_id（广场 uploader_id 用）；无对应用户返回 None。"""
        if not username:
            return None
        user_id: int | None = (
            await self._db.execute(select(PmcpUser.id).where(PmcpUser.username == username))
        ).scalar_one_or_none()
        return user_id

    async def _publish_to_plaza(self, skill: PmcpSkill, actor: ReviewActor) -> PmcpSkillPlaza:
        """按 ``skill_code`` upsert 广场副本（approve 新增入广场 / F-31 覆盖上一版本），回写 ``plaza_id``。"""
        plaza: PmcpSkillPlaza | None = (
            await self._db.execute(
                select(PmcpSkillPlaza).where(PmcpSkillPlaza.skill_code == skill.skill_code)
            )
        ).scalar_one_or_none()
        uploader_id = await self._resolve_user_id(skill.inserted_by)
        # 涉库/涉服务器标记由 audit_result 的 R2-xx / R3-xx 命中派生（架构 §19.5.3 / F-23），
        # 带标记的广场副本对一般用户在 Web 与 MCP 双端均不可见（可见性由广场检索/工具层按角色过滤）。
        involve_flags = derive_involve_flags(skill.audit_result)
        if plaza is None:
            plaza = PmcpSkillPlaza(
                skill_code=skill.skill_code,
                skill_name=skill.skill_name,
                description=skill.description,
                version=skill.version,
                uploader_id=uploader_id,
                involve_flags=involve_flags,
                source_path=skill.source_path,
                source_checksum=skill.source_checksum,
                status="PUBLISHED",
                inserted_by=actor.username,
            )
            self._db.add(plaza)
            await self._db.flush()  # 取得 plaza.id
        else:
            plaza.skill_name = skill.skill_name
            plaza.description = skill.description
            plaza.version = skill.version
            plaza.uploader_id = uploader_id
            plaza.involve_flags = involve_flags
            plaza.source_path = skill.source_path
            plaza.source_checksum = skill.source_checksum
            plaza.status = "PUBLISHED"
            plaza.updated_by = actor.username
            await self._db.flush()
        skill.plaza_id = plaza.id
        # 广场语义向量：发布/覆盖入广场时计算名称+描述向量（BGE-M3 / 降级哈希，架构 §19.5.6 / F-33）。
        await index_plaza_embedding(self._db, plaza.id, plaza.skill_name, plaza.description)
        return plaza

    async def _set_plaza_iteration_note(
        self, skill: PmcpSkill, actor: ReviewActor, note: str | None
    ) -> None:
        """merge：写广场副本 ``iteration_note``（优先 skill.plaza_id，回退按 skill_code 查）。"""
        plaza: PmcpSkillPlaza | None = None
        if skill.plaza_id is not None:
            plaza = await self._db.get(PmcpSkillPlaza, skill.plaza_id)
        if plaza is None:
            plaza = (
                await self._db.execute(
                    select(PmcpSkillPlaza).where(PmcpSkillPlaza.skill_code == skill.skill_code)
                )
            ).scalar_one_or_none()
        if plaza is None:
            raise SkillReviewError("合并目标广场副本不存在", code=CODE_INVALID_STATE)
        plaza.iteration_note = note
        plaza.updated_by = actor.username
        await self._db.flush()

    def _result(self, skill: PmcpSkill, action: str, old_status: str) -> ReviewResult:
        return ReviewResult(
            skill_id=skill.id,
            skill_code=skill.skill_code,
            action=action,
            old_status=old_status,
            new_status=skill.status,
            share_status=skill.share_status,
            plaza_id=skill.plaza_id,
            review_comment=skill.review_comment,
        )

    async def _audit(
        self,
        actor: ReviewActor,
        skill: PmcpSkill,
        action: str,
        *,
        old_status: str,
        result_status: str = "success",
        error_message: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """审计留痕（``resource_type="skill"``，F-40 操作明细可区分）。

        注：skill_review 邮件（提审/通过/合并/拒绝/撤回）由 M5 在各流程点显式触发（§19.5.5），
        本服务仅落审计；审计与邮件同为 owner/admin 可见决策留痕，review_comment 为 owner 侧持久化。
        """
        detail: dict = {
            "skill_code": skill.skill_code,
            "action": action,
            "old_status": old_status,
            "new_status": skill.status,
            "share_status": skill.share_status,
            "plaza_id": skill.plaza_id,
        }
        if extra:
            detail.update(extra)
        await write_audit_log(
            trace_id=actor.trace_id,
            operator=actor.username,
            skill_name=skill.skill_code,
            resource_type="skill",
            resource_id=str(skill.id),
            request_summary=f"Skill 审核流：{skill.skill_code} — {action}",
            result_status=result_status,
            error_message=error_message,
            extra_data=detail,
        )
