"""5.1.6 API 集成测试 — Skill 管理（P1-2 深化断言）"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSkillsAPI:
    @pytest.mark.asyncio
    async def test_list_skills(self, admin_client):
        with patch("platform_mcp.api.skills.registry") as mock_reg:
            mock_reg.list_all_tools.return_value = []
            resp = await admin_client.get("/api/v1/skills")
        assert resp.status_code == 200
        body = resp.json()
        # 深化断言：响应体标准格式 + 分页字段
        assert body["code"] == 0
        assert "items" in body["data"]
        assert "total" in body["data"]
        assert "page" in body["data"]
        assert "page_size" in body["data"]

    @pytest.mark.asyncio
    async def test_create_skill_admin_phase2_disabled(self, admin_client):
        resp = await admin_client.post("/api/v1/skills", json={
            "skill_code": "test_skill", "skill_name": "测试Skill",
        })
        assert resp.status_code == 501
        body = resp.json()
        assert "detail" in body
        assert "二期" in body["detail"]

    @pytest.mark.asyncio
    async def test_create_skill_developer_phase2_disabled(self, dev_client):
        resp = await dev_client.post("/api/v1/skills", json={
            "skill_code": "test_skill2", "skill_name": "测试Skill2",
        })
        assert resp.status_code == 501

    @pytest.mark.asyncio
    async def test_list_skills_带search过滤(self, admin_client):
        with patch("platform_mcp.api.skills.registry") as mock_reg:
            mock_reg.list_all_tools.return_value = []
            resp = await admin_client.get("/api/v1/skills", params={"search": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_create_skill_phase2_disabled_no_dup_check(self, admin_client):
        resp = await admin_client.post("/api/v1/skills", json={
            "skill_code": "dup_skill", "skill_name": "重复Skill2",
        })
        assert resp.status_code == 501

    @pytest.mark.asyncio
    async def test_review_skill_approve(self, admin_client, mock_db):
        # mock db.get 返回真实 skill 让业务进入审核逻辑
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = 2  # PENDING_REVIEW
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "approve"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "审核" in body["message"]

    @pytest.mark.asyncio
    async def test_review_skill_reject(self, admin_client, mock_db):
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "reject"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_update_skill_status_不存在(self, admin_client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.put("/api/v1/skills/9999/status", json={"status": "ENABLED"})
        assert resp.status_code == 200
        body = resp.json()
        # 不存在的 skill 返回 code=10002
        assert body["code"] == 10002

    @pytest.mark.asyncio
    async def test_review_skill_不存在(self, admin_client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.post("/api/v1/skills/9999/review", json={"action": "approve"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 10002
