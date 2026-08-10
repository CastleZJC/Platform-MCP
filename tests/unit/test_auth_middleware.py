"""权限中间件单元测试 — get_current_user / require_role"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from platform_mcp.common.exceptions import AuthError


def test_get_current_user_有效session():
    from platform_mcp.auth.middleware import get_current_user
    mock_request = MagicMock()
    mock_request.cookies = {"session_id": "valid_sid"}
    mock_info = MagicMock()
    mock_info.user_id = 1
    mock_info.username = "admin"
    mock_info.nickname = "管理员"
    mock_info.role_code = "admin"

    with patch("platform_mcp.auth.middleware.session_manager") as mock_sm:
        mock_sm.get.return_value = mock_info
        result = get_current_user(mock_request)
        assert result["id"] == 1
        assert result["username"] == "admin"
        assert result["role_code"] == "admin"


def test_get_current_user_无cookie报AuthError():
    from platform_mcp.auth.middleware import get_current_user
    mock_request = MagicMock()
    mock_request.cookies = {}

    with pytest.raises(AuthError, match="未登录"):
        get_current_user(mock_request)


def test_get_current_user_无效session报AuthError():
    from platform_mcp.auth.middleware import get_current_user
    mock_request = MagicMock()
    mock_request.cookies = {"session_id": "expired"}

    with patch("platform_mcp.auth.middleware.session_manager") as mock_sm:
        mock_sm.get.return_value = None
        with pytest.raises(AuthError, match="Session 已过期"):
            get_current_user(mock_request)


def test_require_role_角色匹配通过():
    from platform_mcp.auth.middleware import require_role
    checker = require_role("admin", "developer")
    user = {"id": 1, "username": "dev01", "nickname": "开发", "role_code": "developer"}
    result = checker(current_user=user)
    assert result["role_code"] == "developer"


def test_require_role_角色不匹配报AuthError():
    from platform_mcp.auth.middleware import require_role
    checker = require_role("admin")
    user = {"id": 2, "username": "dev01", "nickname": "开发", "role_code": "developer"}
    with pytest.raises(AuthError, match="权限不足"):
        checker(current_user=user)
