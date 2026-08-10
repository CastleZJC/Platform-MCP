"""5.1.6 API 集成测试 — MCP 接入指南"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.mcp_server.skill.protocol import ToolMeta


class TestGuideAPI:
    @pytest.mark.asyncio
    async def test_get_config(self, admin_client):
        resp = await admin_client.get("/api/v1/guide/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "dev" in data["data"]
        assert "prod" in data["data"]
        assert data["data"]["dev"]["mcpServers"]["Platform-MCP"]["command"] == "python"
        assert data["data"]["prod"]["mcpServers"]["Platform-MCP"]["type"] == "http"

    @pytest.mark.asyncio
    async def test_get_tools(self, admin_client, mock_db):
        # 修正：mock_db 需要返回非空 skill 列表才能进入循环
        from unittest.mock import MagicMock
        from platform_mcp.skills.database import DatabaseSkill

        mock_skill = MagicMock()
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.description = "SQL"
        mock_skill.register_method = "decorator"
        mock_skill.status = 1

        # mock execute 返回有 1 个 skill
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [mock_skill]
        mock_db.execute = AsyncMock(return_value=result_mock)

        with patch.object(DatabaseSkill, "list_tools") as mock_list:
            mock_list.return_value = [
                ToolMeta(tool_name="execute_sql_text", display_name="执行SQL", description="desc", risk_level="LOW"),
            ]
            resp = await admin_client.get("/api/v1/guide/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]) >= 1
