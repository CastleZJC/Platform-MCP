"""5.1.6 API 集成测试 — 系统配置（注册表 + CRUD 校验，V3.0 M1）

覆盖：/registry 形状（id/已配置/掩码/生效标签）、已知键类型校验（16004）、
敏感键二次确认（16004）、重复创建（16001）、不存在（16002）、非 admin 拒绝。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.common.runtime_config import KNOWN_KEYS


def _registry_rc(raw_map: dict):
    """构造 /registry 用的 runtime_config mock（raw_configured/get_sync 按表取值）。"""
    rc = MagicMock()
    rc.refresh = AsyncMock()
    rc.raw_configured = MagicMock(side_effect=lambda k: raw_map.get(k))
    rc.get_sync = MagicMock(side_effect=lambda k: raw_map.get(k))
    return rc


class TestSystemConfigRegistry:
    @pytest.mark.asyncio
    async def test_registry_shape(self, admin_client, mock_db):
        row = MagicMock()
        row.config_key = "session.timeout_minutes"
        row.id = 7
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=result)
        rc = _registry_rc({"session.timeout_minutes": 45})
        with patch("platform_mcp.api.system_config.runtime_config", rc):
            resp = await admin_client.get("/api/v1/system-config/registry")
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) == len(KNOWN_KEYS) == 14
        by_key = {i["key"]: i for i in items}
        entry = by_key["session.timeout_minutes"]
        assert entry["id"] == 7
        assert entry["configured"] is True
        assert entry["current_value"] == 45
        assert entry["effect"] == "relogin"
        assert entry["effect_label"] == "重新登录后生效"
        assert entry["sensitive"] is False
        smtp = by_key["smtp.host"]
        assert smtp["id"] is None
        assert smtp["configured"] is False
        assert smtp["sensitive"] is True

    @pytest.mark.asyncio
    async def test_registry_sensitive_masked(self, admin_client, mock_db):
        row = MagicMock()
        row.config_key = "smtp.password"
        row.id = 3
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=result)
        rc = _registry_rc({"smtp.password": "s3cret-placeholder"})
        with patch("platform_mcp.api.system_config.runtime_config", rc):
            resp = await admin_client.get("/api/v1/system-config/registry")
        by_key = {i["key"]: i for i in resp.json()["data"]}
        assert by_key["smtp.password"]["configured"] is True
        assert by_key["smtp.password"]["current_value"] == "******"


class TestSystemConfigValidation:
    @pytest.mark.asyncio
    async def test_create_bad_int_rejected(self, admin_client):
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "session.timeout_minutes", "config_value": "abc", "config_type": "int"})
        assert resp.json()["code"] == 16004

    @pytest.mark.asyncio
    async def test_create_sensitive_without_confirm_rejected(self, admin_client):
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "smtp.password", "config_value": "s3cret"})
        assert resp.json()["code"] == 16004

    @pytest.mark.asyncio
    async def test_create_sensitive_with_confirm_ok(self, admin_client):
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "smtp.password", "config_value": "s3cret", "confirm_sensitive": True})
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["config_key"] == "smtp.password"

    @pytest.mark.asyncio
    async def test_create_unknown_key_passthrough(self, admin_client):
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "custom.anything", "config_value": "ok"})
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_create_duplicate_rejected(self, admin_client, mock_db):
        result = MagicMock()
        result.scalar_one_or_none.return_value = MagicMock(id=1)
        mock_db.execute = AsyncMock(return_value=result)
        resp = await admin_client.post("/api/v1/system-config", json={"config_key": "custom.anything"})
        assert resp.json()["code"] == 16001

    @pytest.mark.asyncio
    async def test_update_not_found(self, admin_client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.put("/api/v1/system-config/999", json={"config_value": "x"})
        assert resp.json()["code"] == 16002

    @pytest.mark.asyncio
    async def test_update_bad_int_rejected(self, admin_client, mock_db):
        config = MagicMock(id=6, config_key="session.timeout_minutes", config_value="30")
        mock_db.get = AsyncMock(return_value=config)
        resp = await admin_client.put("/api/v1/system-config/6", json={"config_value": "xyz"})
        assert resp.json()["code"] == 16004

    @pytest.mark.asyncio
    async def test_update_sensitive_without_confirm_rejected(self, admin_client, mock_db):
        config = MagicMock(id=5, config_key="smtp.password", config_value="old")
        mock_db.get = AsyncMock(return_value=config)
        resp = await admin_client.put("/api/v1/system-config/5", json={"config_value": "new"})
        assert resp.json()["code"] == 16004

    @pytest.mark.asyncio
    async def test_update_sensitive_with_confirm_ok(self, admin_client, mock_db):
        config = MagicMock(id=5, config_key="smtp.password", config_value="old")
        mock_db.get = AsyncMock(return_value=config)
        resp = await admin_client.put("/api/v1/system-config/5",
                                      json={"config_value": "new", "confirm_sensitive": True})
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_ok(self, admin_client, mock_db):
        config = MagicMock(id=5, config_key="smtp.host")
        mock_db.get = AsyncMock(return_value=config)
        mock_db.delete = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/5")
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_not_found(self, admin_client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.delete("/api/v1/system-config/999")
        assert resp.json()["code"] == 16002

    @pytest.mark.asyncio
    async def test_list_ok(self, admin_client):
        resp = await admin_client.get("/api/v1/system-config")
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_developer_forbidden(self, dev_client):
        resp = await dev_client.get("/api/v1/system-config/registry")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001
