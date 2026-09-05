"""M5 单元测试 — 连续登录失败锁定（F-37 user_mgmt 捕捉点功能前提）

策略：5 次失败锁 15 分钟；锁定期内静默拒绝（计数不增）；成功登录清零；
第 5 次失败触发 user_mgmt 邮件（outbox 落库）。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.auth import service as auth_service


def _user(failed_attempts=0, locked_until=None, email="u@x.com"):
    u = MagicMock()
    u.id = 1
    u.username = "dev01"
    u.nickname = "开发者"
    u.email = email
    u.locale = "zh-CN"
    u.status = 1
    u.password = "$2b$12$hashed"
    u.failed_attempts = failed_attempts
    u.locked_until = locked_until
    return u


def _session_with(user, role_code="developer"):
    """authenticate_user 的会话 mock：第 1 次查用户，第 2 次查角色（成功路径）。"""
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    role_result = MagicMock()
    role_result.scalar_one_or_none.return_value = role_code
    session.execute = AsyncMock(side_effect=[user_result, role_result])
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    maker = MagicMock(return_value=_Ctx())
    db = MagicMock()
    db.get_session_factory = MagicMock(return_value=maker)
    return db, session


class TestLoginLockout:
    @pytest.mark.asyncio
    async def test_unknown_user_returns_none(self):
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(return_value=session_result)

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                return False

        db = MagicMock()
        db.get_session_factory = MagicMock(
            return_value=MagicMock(return_value=_Ctx()))
        with patch.object(auth_service, "_db", db):
            assert await auth_service.authenticate_user("ghost", "x") is None

    @pytest.mark.asyncio
    async def test_first_failure_increments_counter(self):
        user = _user(failed_attempts=0)
        db, session = _session_with(user)
        with patch.object(auth_service, "_db", db), \
                patch.object(auth_service, "verify_password", MagicMock(return_value=False)), \
                patch.object(auth_service, "_notify_lockout", AsyncMock()) as notify:
            result = await auth_service.authenticate_user("dev01", "wrong")
        assert result is None
        assert user.failed_attempts == 1
        assert user.locked_until is None
        notify.assert_not_awaited()  # 未达 5 次不触发邮件

    @pytest.mark.asyncio
    async def test_fifth_failure_locks_and_notifies(self):
        """第 5 次失败：锁定 15 分钟、计数清零、触发 user_mgmt 邮件"""
        user = _user(failed_attempts=4)
        db, session = _session_with(user)
        notify = AsyncMock()
        with patch.object(auth_service, "_db", db), \
                patch.object(auth_service, "verify_password", MagicMock(return_value=False)), \
                patch.object(auth_service, "_notify_lockout", notify):
            result = await auth_service.authenticate_user("dev01", "wrong")
        assert result is None
        assert user.locked_until is not None
        # 锁定时长 ≈ 15 分钟
        delta = user.locked_until - datetime.now(timezone.utc)
        assert timedelta(minutes=14) < delta <= timedelta(minutes=16)
        assert user.failed_attempts == 0  # 锁定即清零：解锁后重新累计
        notify.assert_awaited_once()
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_locked_period_rejects_silently(self):
        """锁定期内：静默拒绝，不验密码、不增计数（防刷解锁窗口）"""
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        user = _user(failed_attempts=0, locked_until=locked_until)
        db, session = _session_with(user)
        verify = MagicMock(return_value=True)  # 即使密码正确也拒绝
        with patch.object(auth_service, "_db", db), \
                patch.object(auth_service, "verify_password", verify):
            result = await auth_service.authenticate_user("dev01", "right-password")
        assert result is None
        verify.assert_not_called()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lock_expired_allows_login(self):
        """锁定到期后：正常登录（走密码校验）并清零"""
        locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        user = _user(failed_attempts=0, locked_until=locked_until)
        db, session = _session_with(user, role_code="admin")
        with patch.object(auth_service, "_db", db), \
                patch.object(auth_service, "verify_password", MagicMock(return_value=True)):
            result = await auth_service.authenticate_user("dev01", "right")
        assert result == {
            "id": 1, "username": "dev01", "nickname": "开发者",
            "email": "u@x.com", "locale": "zh-CN", "role_code": "admin", "status": 1,
        }
        assert user.failed_attempts == 0
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        user = _user(failed_attempts=3)
        db, session = _session_with(user)
        with patch.object(auth_service, "_db", db), \
                patch.object(auth_service, "verify_password", MagicMock(return_value=True)):
            result = await auth_service.authenticate_user("dev01", "right")
        assert result is not None
        assert user.failed_attempts == 0
        assert user.locked_until is None


class TestLockoutNotify:
    @pytest.mark.asyncio
    async def test_notify_lockout_dispatches_user_mgmt(self):
        """锁定邮件：user_mgmt 组 ∪ 本人（outbox 落库不发送，F-37）"""
        session = AsyncMock()
        result = MagicMock()
        # select(PmcpUser.id, PmcpUser.email).first() → Row 属性访问
        result.first.return_value = MagicMock(id=1, email="u@x.com")
        session.execute = AsyncMock(return_value=result)

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                return False

        db = MagicMock()
        db.get_session_factory = MagicMock(return_value=MagicMock(return_value=_Ctx()))
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        with patch.object(auth_service, "_db", db), \
                patch("platform_mcp.notify.service.dispatch_notification",
                      AsyncMock(return_value=1)) as dispatch:
            await auth_service._notify_lockout("dev01", locked_until)
        dispatch.assert_awaited_once()
        args, kwargs = dispatch.call_args
        assert args[0] == "user_mgmt"
        assert kwargs["source"] == "lockout"
        assert kwargs["extra_recipients"] == [(1, "u@x.com")]
        assert "锁定" in args[1]["action"]
