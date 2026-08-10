"""5.1.6 API 集成测试 — 审计日志"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAuditAPI:
    @pytest.mark.asyncio
    async def test_admin_list_logs(self, admin_client):
        with patch("platform_mcp.api.audit.query_logs", return_value=([], 0)):
            resp = await admin_client.get("/api/v1/audit/logs")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_developer_list_logs_restricted(self, dev_client):
        with patch("platform_mcp.api.audit.query_logs", return_value=([], 0)) as mock_ql:
            resp = await dev_client.get("/api/v1/audit/logs")
        assert resp.status_code == 200
        # Verify that operator filter is applied (3rd positional arg)
        args = mock_ql.call_args[0]
        assert args[3] == "dev01"

    @pytest.mark.asyncio
    async def test_stats(self, admin_client):
        stats_data = {"total_operations": 100, "mcp_calls": 60, "sql_executions": 50, "high_risk_blocks": 5}
        with patch("platform_mcp.api.audit.get_stats", return_value=stats_data):
            resp = await admin_client.get("/api/v1/audit/stats")
        assert resp.status_code == 200
        assert resp.json()["data"]["total_operations"] == 100

    @pytest.mark.asyncio
    async def test_get_log_不存在_返回15001(self, admin_client):
        resp = await admin_client.get("/api/v1/audit/logs/99999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 15001

    @pytest.mark.asyncio
    async def test_get_log_存在_返回详情(self, admin_client, mock_db):
        mock_log = MagicMock()
        mock_log.id = 1
        mock_log.trace_id = "t1"
        mock_log.operator = "admin"
        mock_log.skill_name = "database"
        mock_log.tool_name = "execute_sql_text"
        mock_log.resource_type = "datasource"
        mock_log.resource_id = "ds1"
        mock_log.risk_level = "LOW"
        mock_log.result_status = "SUCCESS"
        mock_log.duration_ms = 100
        mock_log.error_message = None
        mock_log.extra_data = None
        mock_log.inserted_at = None
        mock_db.get = AsyncMock(return_value=mock_log)

        resp = await admin_client.get("/api/v1/audit/logs/1")
        assert resp.status_code == 200
        assert resp.json()["data"]["operator"] == "admin"
