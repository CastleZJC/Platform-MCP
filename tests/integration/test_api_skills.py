"""5.1.6 API 集成测试 — Skill 管理（二期更新：上传 + 审核）"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestSkillsAPI:
    @pytest.mark.asyncio
    async def test_list_skills(self, admin_client, mock_db):
        """列出 Skills 应返回分页数据"""
        from unittest.mock import patch
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        with patch("platform_mcp.api.skills.get_skill_instance", return_value=None):
            resp = await admin_client.get("/api/v1/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "items" in body["data"]
        assert "total" in body["data"]

    @pytest.mark.asyncio
    async def test_list_skills_with_search(self, admin_client, mock_db):
        """带搜索参数列出 Skills"""
        from unittest.mock import patch
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        with patch("platform_mcp.api.skills.get_skill_instance", return_value=None):
            resp = await admin_client.get("/api/v1/skills", params={"search": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_upload_invalid_format_rejected(self, admin_client):
        """上传非 .zip/.7z 文件应返回 400"""
        resp = await admin_client.post(
            "/api/v1/skills/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "格式" in detail or "zip" in detail.lower() or "7z" in detail.lower()

    @pytest.mark.asyncio
    async def test_review_skill_approve(self, admin_client, mock_db):
        """审核 approve 应成功"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = 2  # PENDING_REVIEW
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        mock_db.commit = AsyncMock()
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "approve"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_review_skill_reject(self, admin_client, mock_db):
        """审核 reject 应成功"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "reject"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_review_skill_invalid_action(self, admin_client, mock_db):
        """审核非法 action 应返回 400"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "invalid"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_skill_status_nonexistent(self, admin_client, mock_db):
        """更新不存在 Skill 的状态应返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        resp = await admin_client.put("/api/v1/skills/9999/status", json={"status": "ENABLED"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 10002

    @pytest.mark.asyncio
    async def test_review_skill_nonexistent(self, admin_client, mock_db):
        """审核不存在的 Skill 应返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        resp = await admin_client.post("/api/v1/skills/9999/review", json={"action": "approve"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 10002

    @pytest.mark.asyncio
    async def test_get_audit_report_nonexistent(self, admin_client, mock_db):
        """获取不存在 Skill 的审计报告应返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        resp = await admin_client.get("/api/v1/skills/9999/audit-report")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 10002