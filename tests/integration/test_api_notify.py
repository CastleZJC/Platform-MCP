"""M5 集成测试 — 邮件提醒管理 API（/notify，admin only，仅 Web 无 MCP 工具）

覆盖（F-37/F-38，计划 5.4）：
- 组列表形状（成员明细/未发送数/参数说明）；
- 组更新：启停 / 模板编辑（13001 未知组 / 13002 非法 enabled）；
- 成员管理：非 admin 拒绝 13004 / admin 无邮箱入组提示 / 不在组 13006；
- outbox 记录分页筛选；
- 测试发送：邮箱格式校验 13007 / 正常落 outbox + flush；
- 权限：非 admin 11001。
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _group_mock(notify_type="skill_review", enabled=1):
    g = MagicMock()
    g.id = 7
    g.notify_type = notify_type
    g.group_name = "Skill 审核组"
    g.subject_template = "【{{env}}】{{user}}"
    g.body_template = "{{resource}} {{time}}"
    g.param_descriptions = {"user": "操作人", "resource": "资源"}
    g.enabled = enabled
    g.updated_at = datetime(2026, 9, 5, 12, 0, 0)
    return g


def _user_mock(user_id=1, username="admin", email="admin@x.com"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.email = email
    return u


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_value(v):
    r = MagicMock()
    r.scalar.return_value = v
    return r


def _rows_result(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


_AUDIT = "platform_mcp.api.notify.write_audit_log"


class TestNotifyGroupsList:
    @pytest.mark.asyncio
    async def test_list_empty(self, admin_client):
        resp = await admin_client.get("/api/v1/notify/groups")
        assert resp.json()["code"] == 0
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_list_shape_with_group(self, admin_client, mock_db):
        group = _group_mock()
        member_row = MagicMock(id=11, user_id=1, username="admin",
                               nickname="管理员", email="admin@x.com")
        # execute 序列：groups 查询 → pending count → members 明细
        mock_db.execute = AsyncMock(side_effect=[
            _rows_result_with_scalars([group]),
            _scalar_value(2),  # unsent_count
            _rows_result([member_row]),
        ])
        resp = await admin_client.get("/api/v1/notify/groups")
        items = resp.json()["data"]
        assert len(items) == 1
        item = items[0]
        assert item["notify_type"] == "skill_review"
        assert item["group_name"] == "Skill 审核组"
        assert item["enabled"] == 1
        assert item["unsent_count"] == 2
        assert item["param_descriptions"] == {"user": "操作人", "resource": "资源"}
        assert item["updated_at"] == "2026-09-05T12:00:00"
        member = item["members"][0]
        assert member["username"] == "admin"
        assert member["has_email"] is True

    @pytest.mark.asyncio
    async def test_developer_forbidden(self, dev_client):
        resp = await dev_client.get("/api/v1/notify/groups")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001


def _rows_result_with_scalars(rows):
    """list_groups 用 scalars().all()；members/count 用 all()/scalar()。"""
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    r.all.return_value = []
    r.scalar.return_value = 0
    return r


class TestNotifyGroupUpdate:
    @pytest.mark.asyncio
    async def test_update_unknown_group(self, admin_client):
        with patch(_AUDIT, new_callable=AsyncMock):
            resp = await admin_client.put("/api/v1/notify/groups/not_a_type",
                                          json={"enabled": 0})
        assert resp.json()["code"] == 13001

    @pytest.mark.asyncio
    async def test_update_invalid_enabled(self, admin_client, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(_group_mock()))
        with patch(_AUDIT, new_callable=AsyncMock):
            resp = await admin_client.put("/api/v1/notify/groups/skill_review",
                                          json={"enabled": 2})
        assert resp.json()["code"] == 13002

    @pytest.mark.asyncio
    async def test_update_template_and_enabled(self, admin_client, mock_db):
        """启停 + 模板编辑（F-39 模板可编辑 / F-37 停用静默由 dispatch 侧保障）"""
        group = _group_mock()
        mock_db.execute = AsyncMock(return_value=_scalar_result(group))
        with patch(_AUDIT, new_callable=AsyncMock) as audit:
            resp = await admin_client.put("/api/v1/notify/groups/skill_review", json={
                "enabled": 0,
                "group_name": "审核通知",
                "subject_template": "新主题 {{user}}",
                "body_template": "新正文 {{resource}}",
            })
        assert resp.json()["code"] == 0
        assert group.enabled == 0
        assert group.group_name == "审核通知"
        assert group.subject_template == "新主题 {{user}}"
        assert group.body_template == "新正文 {{resource}}"
        mock_db.commit.assert_awaited()
        audit.assert_awaited_once()  # 管理动作留审计


class TestNotifyMembers:
    @pytest.mark.asyncio
    async def test_add_member_unknown_group(self, admin_client):
        resp = await admin_client.post("/api/v1/notify/groups/not_a_type/members",
                                       json={"user_id": 1})
        assert resp.json()["code"] == 13001

    @pytest.mark.asyncio
    async def test_add_member_user_absent(self, admin_client, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(_group_mock()))
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.post("/api/v1/notify/groups/skill_review/members",
                                       json={"user_id": 99})
        assert resp.json()["code"] == 13003

    @pytest.mark.asyncio
    async def test_add_member_non_admin_rejected(self, admin_client, mock_db):
        """仅 admin 角色可入组（F-37 验收项）"""
        # execute 序列：组 → 角色(developer)
        mock_db.execute = AsyncMock(side_effect=[
            _scalar_result(_group_mock()),
            _scalar_result("developer"),
        ])
        mock_db.get = AsyncMock(return_value=_user_mock(2, "dev01"))
        with patch(_AUDIT, new_callable=AsyncMock):
            resp = await admin_client.post("/api/v1/notify/groups/skill_review/members",
                                           json={"user_id": 2})
        assert resp.json()["code"] == 13004

    @pytest.mark.asyncio
    async def test_add_member_admin_without_email_hint(self, admin_client, mock_db):
        """无邮箱 admin 可入组，响应携带提示（F-37 无邮箱提示）"""
        # execute 序列：组 → 角色(admin) → existing(None)
        mock_db.execute = AsyncMock(side_effect=[
            _scalar_result(_group_mock()),
            _scalar_result("admin"),
            _scalar_result(None),
        ])
        mock_db.get = AsyncMock(return_value=_user_mock(2, "admin2", email=None))
        with patch(_AUDIT, new_callable=AsyncMock):
            resp = await admin_client.post("/api/v1/notify/groups/skill_review/members",
                                           json={"user_id": 2})
        body = resp.json()
        assert body["code"] == 0
        assert "未配置邮箱" in body["message"]
        mock_db.add.assert_called()  # 成员行入组

    @pytest.mark.asyncio
    async def test_add_member_admin_with_email(self, admin_client, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            _scalar_result(_group_mock()),
            _scalar_result("admin"),
            _scalar_result(None),
        ])
        mock_db.get = AsyncMock(return_value=_user_mock(2, "admin2", email="a2@x.com"))
        with patch(_AUDIT, new_callable=AsyncMock):
            resp = await admin_client.post("/api/v1/notify/groups/skill_review/members",
                                           json={"user_id": 2})
        assert resp.json()["code"] == 0
        assert "未配置邮箱" not in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_remove_member_not_in_group(self, admin_client, mock_db):
        # execute 序列：组 → member(None) → username(None)
        mock_db.execute = AsyncMock(side_effect=[
            _scalar_result(_group_mock()),
            _scalar_result(None),
            _scalar_result(None),
        ])
        resp = await admin_client.delete("/api/v1/notify/groups/skill_review/members/2")
        assert resp.json()["code"] == 13006


class TestNotifyOutbox:
    @pytest.mark.asyncio
    async def test_outbox_list_empty(self, admin_client, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            _scalar_value(0),                      # count
            _rows_result_with_scalars([]),         # rows
        ])
        resp = await admin_client.get("/api/v1/notify/outbox")
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_outbox_filter_params(self, admin_client, mock_db):
        """状态/类型筛选参数透传（F-38 可审计查询）"""
        mock_db.execute = AsyncMock(side_effect=[
            _scalar_value(1),
            _rows_result_with_scalars([]),
        ])
        resp = await admin_client.get("/api/v1/notify/outbox",
                                      params={"status": "failed", "notify_type": "user_mgmt"})
        assert resp.json()["code"] == 0


class TestNotifyTestSend:
    @pytest.mark.asyncio
    async def test_invalid_recipient(self, admin_client):
        resp = await admin_client.post("/api/v1/notify/test", json={"recipient": "not-an-email"})
        assert resp.json()["code"] == 13007

    @pytest.mark.asyncio
    async def test_test_send_ok(self, admin_client, mock_db):
        """测试发送：落 outbox(source=test) + 立即 flush（R-13 连通性验证）"""
        with patch(_AUDIT, new_callable=AsyncMock), \
                patch("platform_mcp.notify.sender.flush_outbox",
                      AsyncMock(return_value={"sent": 1, "failed": 0, "pending": 0})) as flush:
            resp = await admin_client.post("/api/v1/notify/test", json={"recipient": "a@x.com"})
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["sent"] == 1
        flush.assert_awaited_once()
        added = mock_db.add.call_args[0][0]
        assert added.source == "test"
        assert added.recipient == "a@x.com"

    @pytest.mark.asyncio
    async def test_test_send_smtp_unconfigured(self, admin_client, mock_db):
        """SMTP 未配置：入 outbox 待发，链路正常（R-13 前置依赖提示）"""
        with patch(_AUDIT, new_callable=AsyncMock), \
                patch("platform_mcp.notify.sender.flush_outbox",
                      AsyncMock(return_value={"sent": 0, "failed": 0, "pending": 1})):
            resp = await admin_client.post("/api/v1/notify/test", json={"recipient": "a@x.com"})
        body = resp.json()
        assert body["code"] == 0
        assert "smtp.*" in body["message"]

    @pytest.mark.asyncio
    async def test_developer_forbidden(self, dev_client):
        resp = await dev_client.post("/api/v1/notify/test", json={"recipient": "a@x.com"})
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001
