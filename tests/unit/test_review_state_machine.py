"""单元测试 — 可复用审核状态机（V3.0 M2，架构 §19.5.3 / 计划 F-26、F-27）

覆盖：8 状态枚举、合法转移全路径、非法转移拦截、可见性矩阵（F-27）、
本人 MCP 可用态、状态标签 i18n 键齐备（双语 1:1）。
"""

import pytest

from platform_mcp.i18n import RESOURCES, SUPPORTED_LOCALES
from platform_mcp.review.state_machine import (
    ADMIN_REVIEW_STATES,
    OWNER_MCP_USABLE_STATES,
    OWNER_ONLY_STATES,
    STATUS_LABEL_I18N_KEY,
    TRANSITIONS,
    InvalidTransitionError,
    ReviewAction,
    ReviewStatus,
    allowed_actions,
    allowed_targets,
    can_perform,
    owner_mcp_usable,
    transition,
    validate_transition,
    visible_in_personal_library,
)

ALL_STATES = [s.value for s in ReviewStatus]


class TestReviewStatusEnum:
    def test_恰好8个状态(self):
        assert len(ReviewStatus) == 8

    def test_8状态值域(self):
        assert set(ALL_STATES) == {
            "DRAFT",
            "PENDING_REVIEW",
            "APPROVED",
            "REJECTED",
            "SHARE_ITERATION",
            "ENABLED",
            "DISABLED",
            "WITHDRAWN",
        }

    def test_str枚举可直接比较字符串(self):
        assert ReviewStatus.DRAFT == "DRAFT"
        assert ReviewStatus.ENABLED.value == "ENABLED"

    def test_状态值不超varchar16(self):
        # pmcp_skill.status 为 varchar(16)，SHARE_ITERATION(15) 为最长
        for s in ReviewStatus:
            assert len(s.value) <= 16, f"{s.value} 超过 varchar(16)"


class TestLegalTransitions:
    """F-26：合法转移全路径。逐条断言 TRANSITIONS 表定义的转移。"""

    @pytest.mark.parametrize(
        "current,action,expected",
        [
            (ReviewStatus.DRAFT, ReviewAction.SUBMIT, ReviewStatus.PENDING_REVIEW),
            (ReviewStatus.PENDING_REVIEW, ReviewAction.APPROVE, ReviewStatus.APPROVED),
            (ReviewStatus.PENDING_REVIEW, ReviewAction.MERGE, ReviewStatus.SHARE_ITERATION),
            (ReviewStatus.PENDING_REVIEW, ReviewAction.REJECT, ReviewStatus.REJECTED),
            (ReviewStatus.PENDING_REVIEW, ReviewAction.WITHDRAW, ReviewStatus.WITHDRAWN),
            (ReviewStatus.APPROVED, ReviewAction.ACTIVATE, ReviewStatus.ENABLED),
            (ReviewStatus.REJECTED, ReviewAction.REVISE, ReviewStatus.DRAFT),
            (ReviewStatus.WITHDRAWN, ReviewAction.RESTORE, ReviewStatus.DRAFT),
            (ReviewStatus.SHARE_ITERATION, ReviewAction.RESOLVE_ITERATION, ReviewStatus.ENABLED),
            (ReviewStatus.ENABLED, ReviewAction.DISABLE, ReviewStatus.DISABLED),
            (ReviewStatus.ENABLED, ReviewAction.SUBMIT, ReviewStatus.PENDING_REVIEW),
            (ReviewStatus.DISABLED, ReviewAction.ENABLE, ReviewStatus.ENABLED),
            (ReviewStatus.DISABLED, ReviewAction.SUBMIT, ReviewStatus.PENDING_REVIEW),
            # 迭代标记（设计定稿①，2026-09-10）：系统动作，广场版本变更批量标记持有者副本
            (ReviewStatus.ENABLED, ReviewAction.MARK_ITERATION, ReviewStatus.SHARE_ITERATION),
            (ReviewStatus.DISABLED, ReviewAction.MARK_ITERATION, ReviewStatus.SHARE_ITERATION),
        ],
    )
    def test_合法转移(self, current, action, expected):
        assert transition(current, action) is expected

    def test_转移表与函数一致(self):
        for (src, act), target in TRANSITIONS.items():
            assert transition(src, act) is target

    def test_字符串入参等价枚举(self):
        assert transition("DRAFT", "submit") is ReviewStatus.PENDING_REVIEW
        assert transition("ENABLED", "disable") is ReviewStatus.DISABLED

    def test_完整分享生命周期链路(self):
        """草稿→提交→审核通过→启用→停用→重新启用→再分享 的端到端链路。"""
        s = ReviewStatus.DRAFT
        s = transition(s, ReviewAction.SUBMIT)
        assert s is ReviewStatus.PENDING_REVIEW
        s = transition(s, ReviewAction.APPROVE)
        assert s is ReviewStatus.APPROVED
        s = transition(s, ReviewAction.ACTIVATE)
        assert s is ReviewStatus.ENABLED
        s = transition(s, ReviewAction.DISABLE)
        assert s is ReviewStatus.DISABLED
        s = transition(s, ReviewAction.ENABLE)
        assert s is ReviewStatus.ENABLED
        s = transition(s, ReviewAction.SUBMIT)
        assert s is ReviewStatus.PENDING_REVIEW

    def test_拒绝后修改重提链路(self):
        s = transition(ReviewStatus.DRAFT, ReviewAction.SUBMIT)
        s = transition(s, ReviewAction.REJECT)
        assert s is ReviewStatus.REJECTED
        s = transition(s, ReviewAction.REVISE)
        assert s is ReviewStatus.DRAFT
        s = transition(s, ReviewAction.SUBMIT)
        assert s is ReviewStatus.PENDING_REVIEW

    def test_撤回后恢复链路(self):
        s = transition(ReviewStatus.DRAFT, ReviewAction.SUBMIT)
        s = transition(s, ReviewAction.WITHDRAW)
        assert s is ReviewStatus.WITHDRAWN
        s = transition(s, ReviewAction.RESTORE)
        assert s is ReviewStatus.DRAFT

    def test_分享迭代解决链路(self):
        s = transition(ReviewStatus.DRAFT, ReviewAction.SUBMIT)
        s = transition(s, ReviewAction.MERGE)
        assert s is ReviewStatus.SHARE_ITERATION
        s = transition(s, ReviewAction.RESOLVE_ITERATION)
        assert s is ReviewStatus.ENABLED


class TestIllegalTransitions:
    """F-26：非法转移被拒。"""

    @pytest.mark.parametrize(
        "current,action",
        [
            (ReviewStatus.DRAFT, ReviewAction.APPROVE),      # 草稿不能直接审核
            (ReviewStatus.DRAFT, ReviewAction.ACTIVATE),     # 草稿不能直接启用
            (ReviewStatus.DRAFT, ReviewAction.DISABLE),      # 草稿无所谓停用
            (ReviewStatus.PENDING_REVIEW, ReviewAction.ACTIVATE),  # 审核中须先 approve
            (ReviewStatus.PENDING_REVIEW, ReviewAction.SUBMIT),    # 审核中不能重复提交
            (ReviewStatus.PENDING_REVIEW, ReviewAction.ENABLE),
            (ReviewStatus.APPROVED, ReviewAction.APPROVE),   # 已通过不能再审核
            (ReviewStatus.APPROVED, ReviewAction.SUBMIT),
            (ReviewStatus.REJECTED, ReviewAction.SUBMIT),    # 已拒绝须先 revise 回草稿
            (ReviewStatus.REJECTED, ReviewAction.ACTIVATE),
            (ReviewStatus.REJECTED, ReviewAction.ENABLE),
            (ReviewStatus.SHARE_ITERATION, ReviewAction.APPROVE),
            (ReviewStatus.SHARE_ITERATION, ReviewAction.DISABLE),
            (ReviewStatus.ENABLED, ReviewAction.APPROVE),
            (ReviewStatus.ENABLED, ReviewAction.ACTIVATE),
            (ReviewStatus.ENABLED, ReviewAction.ENABLE),     # 已启用不能再启用
            (ReviewStatus.DISABLED, ReviewAction.DISABLE),   # 已停用不能再停用
            (ReviewStatus.DISABLED, ReviewAction.ACTIVATE),
            (ReviewStatus.WITHDRAWN, ReviewAction.ENABLE),   # 撤回须 restore 回草稿
            (ReviewStatus.WITHDRAWN, ReviewAction.SUBMIT),
            (ReviewStatus.WITHDRAWN, ReviewAction.ACTIVATE),
        ],
    )
    def test_非法转移抛异常(self, current, action):
        with pytest.raises(InvalidTransitionError):
            transition(current, action)

    def test_异常携带上下文(self):
        with pytest.raises(InvalidTransitionError) as ei:
            transition(ReviewStatus.DRAFT, ReviewAction.APPROVE)
        assert ei.value.current is ReviewStatus.DRAFT
        assert ei.value.action is ReviewAction.APPROVE

    def test_非法状态值抛异常(self):
        with pytest.raises(InvalidTransitionError):
            transition("NOT_A_STATE", ReviewAction.SUBMIT)

    def test_非法动作值抛异常(self):
        with pytest.raises(InvalidTransitionError):
            transition(ReviewStatus.DRAFT, "not_an_action")

    def test_can_perform_非法返回False不抛(self):
        assert can_perform(ReviewStatus.DRAFT, ReviewAction.APPROVE) is False
        assert can_perform("BAD", "submit") is False
        assert can_perform(ReviewStatus.DRAFT, "BAD") is False

    def test_can_perform_合法返回True(self):
        assert can_perform(ReviewStatus.DRAFT, ReviewAction.SUBMIT) is True
        assert can_perform("ENABLED", "disable") is True


class TestAllowedQueries:
    def test_allowed_actions_草稿(self):
        assert allowed_actions(ReviewStatus.DRAFT) == {ReviewAction.SUBMIT}

    def test_allowed_actions_审核中四路(self):
        assert allowed_actions(ReviewStatus.PENDING_REVIEW) == {
            ReviewAction.APPROVE,
            ReviewAction.MERGE,
            ReviewAction.REJECT,
            ReviewAction.WITHDRAW,
        }

    def test_allowed_actions_已启用(self):
        # MARK_ITERATION 为系统动作（批量迭代标记），非用户按钮动作
        assert allowed_actions(ReviewStatus.ENABLED) == {
            ReviewAction.DISABLE, ReviewAction.SUBMIT, ReviewAction.MARK_ITERATION,
        }

    def test_allowed_targets_审核中(self):
        assert allowed_targets(ReviewStatus.PENDING_REVIEW) == {
            ReviewStatus.APPROVED,
            ReviewStatus.SHARE_ITERATION,
            ReviewStatus.REJECTED,
            ReviewStatus.WITHDRAWN,
        }

    def test_allowed_targets_终态无出边(self):
        # APPROVED 只有 activate 一条出边；无任何出边的状态不存在（8 态均有生命周期路径）
        assert allowed_targets(ReviewStatus.APPROVED) == {ReviewStatus.ENABLED}

    def test_validate_transition_合法(self):
        assert validate_transition(ReviewStatus.DRAFT, ReviewStatus.PENDING_REVIEW) is True
        assert validate_transition("ENABLED", "DISABLED") is True

    def test_validate_transition_非法(self):
        assert validate_transition(ReviewStatus.DRAFT, ReviewStatus.ENABLED) is False
        assert validate_transition(ReviewStatus.REJECTED, ReviewStatus.ENABLED) is False

    def test_validate_transition_非法状态抛异常(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("BAD", ReviewStatus.ENABLED)

    def test_每个状态都有出边(self):
        """8 状态均在转移图作为源出现（无孤立死态）。"""
        sources = {src for (src, _act) in TRANSITIONS}
        assert sources == set(ReviewStatus)


class TestVisibilityMatrix:
    """F-27 可见性矩阵：草稿/已拒绝/撤回仅本人（admin 不可见）；审核中本人+admin；
    未分享已启用仅本人；广场已发布 admin 可见（跨用户全员发现走 plaza/M3）。"""

    @pytest.mark.parametrize("status", ["DRAFT", "REJECTED", "WITHDRAWN"])
    def test_私有态仅本人可见(self, status):
        # 本人可见
        assert visible_in_personal_library(
            status=status, share_status="unshared", role_code="user", is_owner=True
        ) is True
        # admin 不可见（F-27 明确「含 admin 不可见」）
        assert visible_in_personal_library(
            status=status, share_status="unshared", role_code="admin", is_owner=False
        ) is False
        # 其他 dev / 一般用户不可见
        assert visible_in_personal_library(
            status=status, share_status="unshared", role_code="developer", is_owner=False
        ) is False
        assert visible_in_personal_library(
            status=status, share_status="unshared", role_code="user", is_owner=False
        ) is False

    def test_审核中本人加admin可见(self):
        assert visible_in_personal_library(
            status="PENDING_REVIEW", share_status="unshared", role_code="user", is_owner=True
        ) is True
        assert visible_in_personal_library(
            status="PENDING_REVIEW", share_status="unshared", role_code="admin", is_owner=False
        ) is True
        assert visible_in_personal_library(
            status="PENDING_REVIEW", share_status="unshared", role_code="developer", is_owner=False
        ) is False

    @pytest.mark.parametrize("status", ["APPROVED", "SHARE_ITERATION"])
    def test_审核相关态admin可见(self, status):
        assert visible_in_personal_library(
            status=status, share_status="unshared", role_code="admin", is_owner=False
        ) is True
        assert visible_in_personal_library(
            status=status, share_status="unshared", role_code="developer", is_owner=False
        ) is False

    def test_未分享已启用仅本人(self):
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="user", is_owner=True
        ) is True
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="admin", is_owner=False
        ) is False
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="developer", is_owner=False
        ) is False

    def test_广场已发布admin可见_个人库层其他用户走plaza(self):
        # admin 个人库层可见已发布（监督）
        assert visible_in_personal_library(
            status="ENABLED", share_status="shared", role_code="admin", is_owner=False
        ) is True
        # 本人可见
        assert visible_in_personal_library(
            status="ENABLED", share_status="shared", role_code="user", is_owner=True
        ) is True
        # 个人库层：非本人非 admin 不经此层发现（全员发现走 plaza，M3）
        assert visible_in_personal_library(
            status="ENABLED", share_status="shared", role_code="developer", is_owner=False
        ) is False

    def test_停用态仅本人与admin不可见(self):
        assert visible_in_personal_library(
            status="DISABLED", share_status="unshared", role_code="user", is_owner=True
        ) is True
        assert visible_in_personal_library(
            status="DISABLED", share_status="unshared", role_code="admin", is_owner=False
        ) is False

    def test_内置skill仅admin可见(self):
        # 内置装饰器 Skill（database/server）：admin 管理可见，其余角色个人库不展示
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="admin", is_owner=False, is_builtin=True
        ) is True
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="developer", is_owner=False, is_builtin=True
        ) is False
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="user", is_owner=False, is_builtin=True
        ) is False

    def test_本人对内置skill非admin不可见(self):
        # 内置 Skill 无「本人」概念，is_builtin 优先于 is_owner
        assert visible_in_personal_library(
            status="ENABLED", share_status="unshared", role_code="user", is_owner=True, is_builtin=True
        ) is False

    def test_可见性常量口径(self):
        assert OWNER_ONLY_STATES == frozenset(
            {ReviewStatus.DRAFT, ReviewStatus.REJECTED, ReviewStatus.WITHDRAWN}
        )
        assert ADMIN_REVIEW_STATES == frozenset(
            {ReviewStatus.PENDING_REVIEW, ReviewStatus.APPROVED, ReviewStatus.SHARE_ITERATION}
        )


class TestOwnerMcpUsable:
    @pytest.mark.parametrize(
        "status,expected",
        [
            ("DRAFT", True),
            ("PENDING_REVIEW", True),
            ("APPROVED", True),
            ("SHARE_ITERATION", True),
            ("ENABLED", True),
            ("REJECTED", False),
            ("WITHDRAWN", False),
            ("DISABLED", False),
        ],
    )
    def test_本人MCP可用态(self, status, expected):
        assert owner_mcp_usable(status) is expected

    def test_可用态常量与函数一致(self):
        for s in ReviewStatus:
            assert owner_mcp_usable(s) == (s in OWNER_MCP_USABLE_STATES)


class TestStatusLabelI18n:
    def test_8状态全部有标签键(self):
        assert set(STATUS_LABEL_I18N_KEY.keys()) == set(ReviewStatus)

    def test_标签键在资源字典且双语齐备(self):
        for status, key in STATUS_LABEL_I18N_KEY.items():
            assert key in RESOURCES, f"{status.value} 的标签键 {key} 未在 RESOURCES"
            for locale in SUPPORTED_LOCALES:
                assert RESOURCES[key].get(locale), f"{key} 缺 {locale} 文案"

    def test_标签键命名规范(self):
        for key in STATUS_LABEL_I18N_KEY.values():
            assert key.startswith("skill.status.")
