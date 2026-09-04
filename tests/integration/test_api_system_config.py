"""5.1.6 API 集成测试 — 系统配置（注册表 + 按键 upsert，V3.0）

覆盖：/registry 形状（已配置/掩码/生效标签/label/hint，无行 id）、按键 upsert
（已知键类型校验 16004、未知键拒绝 16004、未落库键创建行、
已有行更新、凭证键留空保留原值）、按键重置 DELETE、POST 已移除（405）、
不存在（16002）、非 admin 拒绝。
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


def _existing_row(config_key: str = "session.timeout_minutes", config_value: str = "30"):
    """已有配置行 mock（PUT 更新分支 / DELETE by key 用）。"""
    row = MagicMock()
    row.id = 5
    row.config_key = config_key
    row.config_value = config_value
    return row


def _row_result(row):
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


class TestSystemConfigRegistry:
    @pytest.mark.asyncio
    async def test_registry_shape(self, admin_client, mock_db):
        rc = _registry_rc({"session.timeout_minutes": 45})
        with patch("platform_mcp.api.system_config.runtime_config", rc):
            resp = await admin_client.get("/api/v1/system-config/registry")
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) == len(KNOWN_KEYS) == 12
        by_key = {i["key"]: i for i in items}
        entry = by_key["session.timeout_minutes"]
        assert entry["configured"] is True
        assert entry["current_value"] == 45
        assert entry["effect"] == "relogin"
        assert entry["effect_label"] == "重新登录后生效"
        assert entry["sensitive"] is False
        assert entry["label"] == "Web 会话超时"
        assert entry["hint"] == "范围 1-1440，单位分钟"
        assert "id" not in entry  # 以 config_key 为自然键，无行 id
        smtp = by_key["smtp.host"]
        assert smtp["configured"] is False
        assert smtp["sensitive"] is False  # 非凭证连接参数，无掩码/留空语义

    @pytest.mark.asyncio
    async def test_registry_sensitive_masked(self, admin_client, mock_db):
        rc = _registry_rc({"smtp.password": "s3cret-placeholder"})
        with patch("platform_mcp.api.system_config.runtime_config", rc):
            resp = await admin_client.get("/api/v1/system-config/registry")
        by_key = {i["key"]: i for i in resp.json()["data"]}
        assert by_key["smtp.password"]["configured"] is True
        assert by_key["smtp.password"]["current_value"] == "******"


class TestSystemConfigUpsertByKey:
    """PUT /{config_key} 按键 upsert：校验先于查行；未落库键创建行、已有行更新。"""

    @pytest.mark.asyncio
    async def test_put_bad_int_rejected(self, admin_client):
        resp = await admin_client.put("/api/v1/system-config/session.timeout_minutes",
                                      json={"config_value": "abc"})
        assert resp.json()["code"] == 16004

    @pytest.mark.asyncio
    async def test_put_unknown_key_rejected(self, admin_client):
        """注册表外未知键 16004（键随版本发布，Web 端仅支持设置已知键）"""
        resp = await admin_client.put("/api/v1/system-config/custom.anything",
                                      json={"config_value": "ok"})
        assert resp.json()["code"] == 16004

    @pytest.mark.asyncio
    async def test_put_unconfigured_key_creates_row(self, admin_client, mock_db):
        """未落库凭证键 → 创建行（配置值永有当前值，无独立 POST 端点）"""
        resp = await admin_client.put("/api/v1/system-config/smtp.password",
                                      json={"config_value": "s3cret"})
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "系统配置落库成功"
        assert mock_db.add.called  # 新建分支入 session

    @pytest.mark.asyncio
    async def test_put_existing_key_updates_row(self, admin_client, mock_db):
        config = _existing_row("smtp.password", "old")
        mock_db.execute = AsyncMock(return_value=_row_result(config))
        resp = await admin_client.put("/api/v1/system-config/smtp.password",
                                      json={"config_value": "new"})
        assert resp.json()["code"] == 0
        assert resp.json()["message"] == "系统配置更新成功"
        assert config.config_value == "new"
        assert not mock_db.add.called  # 覆盖既有行，未新增

    @pytest.mark.asyncio
    async def test_put_sensitive_blank_keeps_original(self, admin_client, mock_db):
        """凭证键留空（null）= 保留原值（更新分支不覆盖）"""
        config = _existing_row("smtp.password", "old")
        mock_db.execute = AsyncMock(return_value=_row_result(config))
        resp = await admin_client.put("/api/v1/system-config/smtp.password",
                                      json={"config_value": None})
        assert resp.json()["code"] == 0
        assert config.config_value == "old"

    @pytest.mark.asyncio
    async def test_post_removed_405(self, admin_client):
        """独立创建端点已移除（按键 upsert 承接，无"首次落库"前置）"""
        resp = await admin_client.post("/api/v1/system-config", json={
            "config_key": "session.timeout_minutes", "config_value": "45"})
        assert resp.status_code == 405


class TestSystemConfigDeleteByKey:
    @pytest.mark.asyncio
    async def test_delete_ok(self, admin_client, mock_db):
        config = _existing_row("smtp.host")
        mock_db.execute = AsyncMock(return_value=_row_result(config))
        mock_db.delete = AsyncMock()
        resp = await admin_client.delete("/api/v1/system-config/smtp.host")
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_not_found(self, admin_client):
        resp = await admin_client.delete("/api/v1/system-config/absent.key")
        assert resp.json()["code"] == 16002


class TestSystemConfigMisc:
    @pytest.mark.asyncio
    async def test_list_ok(self, admin_client):
        resp = await admin_client.get("/api/v1/system-config")
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_developer_forbidden(self, dev_client):
        resp = await dev_client.get("/api/v1/system-config/registry")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001
