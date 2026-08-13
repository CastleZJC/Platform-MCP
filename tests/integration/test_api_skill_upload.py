"""Skill 上传全链路集成测试"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import zipfile

import pytest


class TestSkillUploadAPI:
    """POST /skills/upload 全链路测试"""

    @pytest.mark.asyncio
    async def test_upload_invalid_format_rejected(self, admin_client):
        """上传非 .zip/.7z 文件应返回 400"""
        resp = await admin_client.post(
            "/api/v1/skills/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        assert "格式" in resp.json().get("detail", "") or "zip" in resp.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_review_skill_approve(self, admin_client, mock_db):
        """审核 approve 应成功"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "test-skill"
        mock_skill.skill_name = "Test Skill"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "approve"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_review_skill_reject(self, admin_client, mock_db):
        """审核 reject 应成功"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "test-skill"
        mock_skill.skill_name = "Test Skill"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "reject"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_review_invalid_action(self, admin_client, mock_db):
        """审核非法 action 应返回 400"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "test-skill"
        mock_skill.status = 2
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "invalid"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_review_nonexistent_skill(self, admin_client, mock_db):
        """审核不存在的 skill 应返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.post("/api/v1/skills/9999/review", json={"action": "approve"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 10002

    @pytest.mark.asyncio
    async def test_get_audit_report(self, admin_client, mock_db):
        """GET /skills/{id}/audit-report 应返回审计数据"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "test-skill"
        mock_skill.audit_status = "passed"
        mock_skill.audit_result = {"total_rules": 14, "critical_count": 0, "passed": True}
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        resp = await admin_client.get("/api/v1/skills/1/audit-report")
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert "audit_status" in data

    @pytest.mark.asyncio
    async def test_get_audit_report_nonexistent(self, admin_client, mock_db):
        """获取不存在 skill 的审计报告应返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.get("/api/v1/skills/9999/audit-report")
        assert resp.status_code == 200
        assert resp.json()["code"] == 10002