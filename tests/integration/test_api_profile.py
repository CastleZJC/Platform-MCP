"""5.1.6 API 集成测试 — 个人设置"""

from unittest.mock import MagicMock, patch

import pytest


class TestProfileAPI:
    @pytest.mark.asyncio
    async def test_get_profile(self, admin_client, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.nickname = "管理员"
        mock_user.status = 1
        mock_user.inserted_at = None
        mock_db.get = AsyncMock(return_value=mock_user) if False else mock_db.get
        # The conftest mock_db is already injected; need to return user from db.get
        from unittest.mock import AsyncMock as AM
        mock_db.get = AM(return_value=mock_user)
        resp = await admin_client.get("/api/v1/profile")
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == "admin"

    @pytest.mark.asyncio
    async def test_update_profile(self, admin_client, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.nickname = "管理员"
        from unittest.mock import AsyncMock as AM
        mock_db.get = AM(return_value=mock_user)
        resp = await admin_client.put("/api/v1/profile", json={"nickname": "新昵称"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # update 操作 data 可能为 None，只需断言 code=0 表示成功

    @pytest.mark.asyncio
    async def test_change_password_wrong_old(self, admin_client, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.password = "$2b$12$hashed"
        from unittest.mock import AsyncMock as AM
        mock_db.get = AM(return_value=mock_user)
        with patch("platform_mcp.api.profile.verify_password", return_value=False):
            resp = await admin_client.post("/api/v1/profile/change-password",
                json={"old_password": "wrong", "new_password": "new123"})
        assert resp.json()["code"] == 11004

    @pytest.mark.asyncio
    async def test_update_profile_locale(self, admin_client, mock_db):
        """V3.0 M1：个人语言偏好可更新（重新登录后生效）。"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.locale = "zh-CN"
        from unittest.mock import AsyncMock as AM
        mock_db.get = AM(return_value=mock_user)
        resp = await admin_client.put("/api/v1/profile", json={"locale": "en-US"})
        body = resp.json()
        assert body["code"] == 0
        assert mock_user.locale == "en-US"

    @pytest.mark.asyncio
    async def test_update_profile_invalid_locale_422(self, admin_client):
        """非法 locale 被 Pydantic field_validator 拦截（422）。"""
        resp = await admin_client.put("/api/v1/profile", json={"locale": "fr-FR"})
        assert resp.status_code == 422
