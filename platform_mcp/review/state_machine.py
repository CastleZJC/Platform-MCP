"""可复用审核状态机（V3.0 M2，架构 §19.5.3 / 计划 M2.2、M2.3）

8 状态生命周期 + 合法转移校验 + 个人库可见性矩阵。设计上与具体资源解耦：
状态/动作/转移/可见性均为纯逻辑，Skill（M2）与三期 KB（M6 挂接）复用同一语义，
不依赖 ORM 与数据库会话，便于穷举单测（F-26：8 状态转移合法路径全用例，非法转移被拒）。

状态口径来源：
- 开发计划 M2.2「草稿/审核中/已通过/已拒绝/分享迭代/已启用/停用/撤回」8 状态
- 架构 §19.5.3 状态机图与可见性矩阵、F-27 可见性验收
"""

from __future__ import annotations

from enum import Enum


class ReviewStatus(str, Enum):
    """审核生命周期 8 状态（对应 ``pmcp_skill.status`` varchar 值域，迁移 005/006）。"""

    DRAFT = "DRAFT"                      # 草稿：初始创建，仅本人经 MCP 可用
    PENDING_REVIEW = "PENDING_REVIEW"    # 审核中：已提交分享，待 admin 审核
    APPROVED = "APPROVED"                # 已通过：admin 审核通过（新增入广场结论）
    REJECTED = "REJECTED"                # 已拒绝：admin 拒绝（填原因 + 邮件）
    SHARE_ITERATION = "SHARE_ITERATION"  # 分享迭代：admin 合并到广场已有 Skill 且 origin=PLAZA
    ENABLED = "ENABLED"                  # 已启用：个人侧正式启用（可 MCP 使用）
    DISABLED = "DISABLED"                # 停用：已过审 Skill 被创建人停用
    WITHDRAWN = "WITHDRAWN"              # 撤回：已提交未过审被本人撤回（停用视同撤回）


class ReviewAction(str, Enum):
    """驱动状态转移的审核动作（事件）。服务层调用 :func:`transition` 时传入。"""

    SUBMIT = "submit"                        # 提交分享：DRAFT/ENABLED/DISABLED → PENDING_REVIEW
    APPROVE = "approve"                      # admin 新增入广场：PENDING_REVIEW → APPROVED
    MERGE = "merge"                          # admin 合并到广场已有：PENDING_REVIEW → SHARE_ITERATION
    REJECT = "reject"                        # admin 拒绝：PENDING_REVIEW → REJECTED
    WITHDRAW = "withdraw"                    # 撤回 / 停用视同撤回：PENDING_REVIEW → WITHDRAWN
    ACTIVATE = "activate"                    # 启用（广场副本已发布）：APPROVED → ENABLED
    REVISE = "revise"                        # 修改后重编辑：REJECTED → DRAFT
    RESTORE = "restore"                      # 恢复：WITHDRAWN → DRAFT
    RESOLVE_ITERATION = "resolve_iteration"  # 迭代 / 保留：SHARE_ITERATION → ENABLED
    DISABLE = "disable"                      # 停用：ENABLED → DISABLED
    ENABLE = "enable"                        # 重新启用：DISABLED → ENABLED


class InvalidTransitionError(ValueError):
    """非法状态转移。携带当前状态与动作/目标，便于上层转成统一响应与审计。"""

    def __init__(
        self,
        current: ReviewStatus | str,
        action: ReviewAction | str | None = None,
        target: ReviewStatus | str | None = None,
    ) -> None:
        # 原样保存（current 可能是非法字符串，不可强转 ReviewStatus，否则构造异常时二次抛错）
        self.current = current
        self.action = action
        self.target = target
        cur_val = current.value if isinstance(current, ReviewStatus) else current
        if action is not None:
            act_val = action.value if isinstance(action, ReviewAction) else action
            detail = f"状态 {cur_val} 不允许动作 {act_val}"
        elif target is not None:
            tgt_val = target.value if isinstance(target, ReviewStatus) else target
            detail = f"状态 {cur_val} 不可转移到 {tgt_val}"
        else:
            detail = f"状态 {cur_val} 无可用转移"
        super().__init__(detail)


# (当前状态, 动作) → 目标状态。单一事实来源，:func:`allowed_targets` / :func:`validate_transition`
# 均从此派生，避免多处维护漂移。
TRANSITIONS: dict[tuple[ReviewStatus, ReviewAction], ReviewStatus] = {
    (ReviewStatus.DRAFT, ReviewAction.SUBMIT): ReviewStatus.PENDING_REVIEW,
    (ReviewStatus.PENDING_REVIEW, ReviewAction.APPROVE): ReviewStatus.APPROVED,
    (ReviewStatus.PENDING_REVIEW, ReviewAction.MERGE): ReviewStatus.SHARE_ITERATION,
    (ReviewStatus.PENDING_REVIEW, ReviewAction.REJECT): ReviewStatus.REJECTED,
    (ReviewStatus.PENDING_REVIEW, ReviewAction.WITHDRAW): ReviewStatus.WITHDRAWN,
    (ReviewStatus.APPROVED, ReviewAction.ACTIVATE): ReviewStatus.ENABLED,
    (ReviewStatus.REJECTED, ReviewAction.REVISE): ReviewStatus.DRAFT,
    (ReviewStatus.WITHDRAWN, ReviewAction.RESTORE): ReviewStatus.DRAFT,
    (ReviewStatus.SHARE_ITERATION, ReviewAction.RESOLVE_ITERATION): ReviewStatus.ENABLED,
    (ReviewStatus.ENABLED, ReviewAction.DISABLE): ReviewStatus.DISABLED,
    (ReviewStatus.ENABLED, ReviewAction.SUBMIT): ReviewStatus.PENDING_REVIEW,
    (ReviewStatus.DISABLED, ReviewAction.ENABLE): ReviewStatus.ENABLED,
    (ReviewStatus.DISABLED, ReviewAction.SUBMIT): ReviewStatus.PENDING_REVIEW,
}


def _coerce_status(status: ReviewStatus | str) -> ReviewStatus:
    """把字符串/枚举统一成 :class:`ReviewStatus`；非法值抛 :class:`InvalidTransitionError`。"""
    if isinstance(status, ReviewStatus):
        return status
    try:
        return ReviewStatus(status)
    except ValueError as exc:  # 非法状态值
        raise InvalidTransitionError(status) from exc


def _coerce_action(action: ReviewAction | str) -> ReviewAction:
    if isinstance(action, ReviewAction):
        return action
    try:
        return ReviewAction(action)
    except ValueError as exc:
        raise InvalidTransitionError(ReviewStatus.DRAFT, action=action) from exc


def transition(current: ReviewStatus | str, action: ReviewAction | str) -> ReviewStatus:
    """对 ``current`` 执行 ``action``，返回目标状态；非法组合抛 :class:`InvalidTransitionError`。"""
    cur = _coerce_status(current)
    act = _coerce_action(action)
    target = TRANSITIONS.get((cur, act))
    if target is None:
        raise InvalidTransitionError(cur, action=act)
    return target


def allowed_actions(status: ReviewStatus | str) -> set[ReviewAction]:
    """某状态下全部合法动作（供前端按钮可用性与 MCP 工具前置校验）。"""
    cur = _coerce_status(status)
    return {act for (src, act) in TRANSITIONS if src == cur}


def allowed_targets(status: ReviewStatus | str) -> set[ReviewStatus]:
    """某状态下全部合法目标状态（F-26 转移用例断言用）。"""
    cur = _coerce_status(status)
    return {target for (src, _act), target in TRANSITIONS.items() if src == cur}


def validate_transition(current: ReviewStatus | str, target: ReviewStatus | str) -> bool:
    """``current`` → ``target`` 是否为合法转移（不关心具体动作）。"""
    cur = _coerce_status(current)
    tgt = _coerce_status(target)
    return tgt in allowed_targets(cur)


def can_perform(status: ReviewStatus | str, action: ReviewAction | str) -> bool:
    """``status`` 下 ``action`` 是否合法（不抛异常的探测版）。"""
    try:
        cur = _coerce_status(status)
        act = _coerce_action(action)
    except InvalidTransitionError:
        return False
    return (cur, act) in TRANSITIONS


# ==== 可见性矩阵（架构 §19.5.3 / F-27）====
# 个人库查询层可见性；广场已发布的跨用户发现走 pmcp_skill_plaza（M3）。

#: 仅上传者本人可见（含 admin 不可见）—— F-27「草稿/已拒绝/撤回仅本人可见」
OWNER_ONLY_STATES: frozenset[ReviewStatus] = frozenset(
    {ReviewStatus.DRAFT, ReviewStatus.REJECTED, ReviewStatus.WITHDRAWN}
)

#: admin 因审核/迭代监督可见的状态 —— F-27「审核中本人 + admin」
ADMIN_REVIEW_STATES: frozenset[ReviewStatus] = frozenset(
    {ReviewStatus.PENDING_REVIEW, ReviewStatus.APPROVED, ReviewStatus.SHARE_ITERATION}
)

#: 本人可经 MCP 使用的状态（未过审仅本人可用；已拒绝/撤回/停用不可用）
#: —— 架构 §19.5.3「DRAFT/审核中 均可被本人经 MCP 使用」
OWNER_MCP_USABLE_STATES: frozenset[ReviewStatus] = frozenset(
    {
        ReviewStatus.DRAFT,
        ReviewStatus.PENDING_REVIEW,
        ReviewStatus.APPROVED,
        ReviewStatus.SHARE_ITERATION,
        ReviewStatus.ENABLED,
    }
)

#: 状态 → i18n 资源键（``platform_mcp.i18n`` 双语标签，前端/API 复用）
STATUS_LABEL_I18N_KEY: dict[ReviewStatus, str] = {
    ReviewStatus.DRAFT: "skill.status.draft",
    ReviewStatus.PENDING_REVIEW: "skill.status.pending_review",
    ReviewStatus.APPROVED: "skill.status.approved",
    ReviewStatus.REJECTED: "skill.status.rejected",
    ReviewStatus.SHARE_ITERATION: "skill.status.share_iteration",
    ReviewStatus.ENABLED: "skill.status.enabled",
    ReviewStatus.DISABLED: "skill.status.disabled",
    ReviewStatus.WITHDRAWN: "skill.status.withdrawn",
}


def visible_in_personal_library(
    *,
    status: ReviewStatus | str,
    share_status: str | None,
    role_code: str | None,
    is_owner: bool,
    is_builtin: bool = False,
) -> bool:
    """个人库（SkillPage / list_my_skills）查询层可见性判定（F-27）。

    参数:
        status: ``pmcp_skill.status`` 当前状态。
        share_status: ``unshared`` / ``shared``（是否已入广场）。
        role_code: 观察者角色（``admin`` / ``developer`` / ``user``）。
        is_owner: 观察者是否为该 Skill 上传者本人。
        is_builtin: 是否内置装饰器 Skill（database/server，§19.5.7 仅 Web admin 管理）。

    返回:
        观察者是否可在个人库看到该 Skill。跨用户广场发现不在此层（走 plaza，M3）。
    """
    cur = _coerce_status(status)
    # 内置装饰器 Skill：仅 admin 可在 Web 管理（启停），其余角色个人库不展示
    if is_builtin:
        return role_code == "admin"
    # 本人：全状态可见（含草稿/已拒绝/撤回）
    if is_owner:
        return True
    # admin：仅审核相关态 + 广场已发布态可见（草稿/已拒绝/撤回/未分享已启用/停用 不可见）
    if role_code == "admin":
        if cur in ADMIN_REVIEW_STATES:
            return True
        return cur == ReviewStatus.ENABLED and share_status == "shared"
    # 其他角色：看不到他人个人库 Skill
    return False


def owner_mcp_usable(status: ReviewStatus | str) -> bool:
    """本人是否可经 MCP 使用该 Skill（未过审仅本人可用；拒绝/撤回/停用不可用）。"""
    return _coerce_status(status) in OWNER_MCP_USABLE_STATES
