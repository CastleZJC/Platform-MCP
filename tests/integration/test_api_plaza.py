"""API 集成测试 — Skill 广场公共池（V3.0 M3.1/M3.3，架构 §19.5.3 / 需求 1.1.4 / F-23/F-33/F-34）

覆盖 GET /plaza（列表 + 角色可见性 + 黑名单）、GET /plaza/search（语义搜索）、GET /plaza/{id}（详情 + 可见性校验）、
GET /plaza/{id}/readme（双语 README + 可见性校验）。
用按 SQL 文本分派的 execute side_effect 替代真实 DB，一般用户（role_code=user）不见涉库/涉服务器项为核心验收（需求 1.1.4）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.skills.models import PmcpSkillBlacklist, PmcpSkillPlaza


def _plaza(pid, code, name="N", desc="d", flags=None, status="PUBLISHED", uploader_id=None):
    return PmcpSkillPlaza(
        id=pid, skill_code=code, skill_name=name, description=desc,
        involve_flags=flags, status=status, version="1.0", uploader_id=uploader_id,
    )


def _install_db(mock_db, plazas, *, blocked=(), users=(), embeddings=(), get_result=None):
    """按 SQL 文本分派 mock_db.execute，并配置 mock_db.get（详情/复制/移除端点）。"""

    async def _exec(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        if "pg_extension" in sql:
            result.first.return_value = None  # 本地/测试无 pgvector → 降级 JSONB
        elif "pmcp_skill_blacklist" in sql:
            result.scalars.return_value.all.return_value = list(blocked)
        elif "pmcp_user" in sql:
            result.scalars.return_value.all.return_value = list(users)
        elif "pmcp_skill_plaza.embedding" in sql and "pmcp_skill_plaza.skill_code" not in sql:
            result.all.return_value = list(embeddings)
        elif "pmcp_skill_plaza" in sql:
            result.scalars.return_value.all.return_value = list(plazas)
        else:
            result.scalars.return_value.all.return_value = []
        return result

    mock_db.execute = AsyncMock(side_effect=_exec)
    mock_db.get = AsyncMock(return_value=get_result)


class TestPlazaList:
    @pytest.mark.asyncio
    async def test_列表返回分页结构(self, admin_client, mock_db):
        _install_db(mock_db, [_plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")])
        resp = await admin_client.get("/api/v1/plaza")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "items" in body["data"] and "total" in body["data"]
        assert body["data"]["total"] == 1

    @pytest.mark.asyncio
    async def test_一般用户不见涉库项(self, user_client, mock_db):
        """需求 1.1.4：带涉库标记的广场 Skill 对一般用户 Web 端不可见（F-23）"""
        _install_db(mock_db, [
            _plaza(1, "plain", "普通工具", "无涉库"),
            _plaza(2, "db-tool", "数据库工具", "直连 DML", flags=["database"]),
            _plaza(3, "srv-tool", "服务器工具", "网络监听", flags=["server"]),
        ])
        resp = await user_client.get("/api/v1/plaza")
        codes = [it["skill_code"] for it in resp.json()["data"]["items"]]
        assert codes == ["plain"]

    @pytest.mark.asyncio
    async def test_admin可见涉库项(self, admin_client, mock_db):
        _install_db(mock_db, [
            _plaza(1, "plain", "普通工具"),
            _plaza(2, "db-tool", "数据库工具", flags=["database"]),
        ])
        resp = await admin_client.get("/api/v1/plaza")
        codes = {it["skill_code"] for it in resp.json()["data"]["items"]}
        assert codes == {"plain", "db-tool"}

    @pytest.mark.asyncio
    async def test_developer可见涉库项(self, dev_client, mock_db):
        _install_db(mock_db, [
            _plaza(1, "plain", "普通工具"),
            _plaza(2, "db-tool", "数据库工具", flags=["database"]),
        ])
        resp = await dev_client.get("/api/v1/plaza")
        assert len(resp.json()["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_黑名单屏蔽项被排除(self, user_client, mock_db):
        """F-34：用户已屏蔽的广场 Skill 不出现在列表"""
        _install_db(mock_db, [_plaza(1, "a"), _plaza(2, "b"), _plaza(3, "c")], blocked=[2])
        resp = await user_client.get("/api/v1/plaza")
        codes = {it["skill_code"] for it in resp.json()["data"]["items"]}
        assert codes == {"a", "c"}

    @pytest.mark.asyncio
    async def test_关键词搜索命中(self, admin_client, mock_db):
        _install_db(mock_db, [
            _plaza(1, "oracle-backup", "Oracle 备份"),
            _plaza(2, "ssh-tool", "SSH 服务器"),
        ])
        resp = await admin_client.get("/api/v1/plaza", params={"search": "oracle"})
        codes = [it["skill_code"] for it in resp.json()["data"]["items"]]
        assert codes == ["oracle-backup"]

    @pytest.mark.asyncio
    async def test_列表含涉库标记字段(self, admin_client, mock_db):
        _install_db(mock_db, [_plaza(1, "db-tool", "数据库工具", flags=["database"])])
        resp = await admin_client.get("/api/v1/plaza")
        item = resp.json()["data"]["items"][0]
        assert item["involve_flags"] == ["database"]

    @pytest.mark.asyncio
    async def test_admin列表附带已停用项(self, admin_client, mock_db):
        """admin 管理口径：include_disabled 附带 DISABLED 项供停用现状展示"""
        _install_db(mock_db, [
            _plaza(1, "plain", "普通工具"),
            _plaza(2, "old-tool", "已停用工具", status="DISABLED"),
        ])
        resp = await admin_client.get("/api/v1/plaza")
        codes = {it["skill_code"] for it in resp.json()["data"]["items"]}
        assert codes == {"plain", "old-tool"}

    @pytest.mark.asyncio
    async def test_非admin列表不含已停用项(self, dev_client, mock_db):
        _install_db(mock_db, [
            _plaza(1, "plain", "普通工具"),
            _plaza(2, "old-tool", "已停用工具", status="DISABLED"),
        ])
        resp = await dev_client.get("/api/v1/plaza")
        codes = {it["skill_code"] for it in resp.json()["data"]["items"]}
        assert codes == {"plain"}


class TestPlazaSearch:
    @pytest.mark.asyncio
    async def test_语义搜索返回结构(self, admin_client, mock_db):
        _install_db(mock_db, [_plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")])
        resp = await admin_client.get("/api/v1/plaza/search", params={"q": "Oracle 备份"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["query"] == "Oracle 备份"
        assert "items" in body["data"]

    @pytest.mark.asyncio
    async def test_一般用户搜索不含涉库(self, user_client, mock_db):
        _install_db(mock_db, [
            _plaza(1, "oracle-backup", "Oracle 备份", "备份 恢复"),
            _plaza(2, "db-admin", "数据库管理", "直连 DML", flags=["database"]),
        ])
        resp = await user_client.get("/api/v1/plaza/search", params={"q": "数据库管理"})
        codes = {it["skill_code"] for it in resp.json()["data"]["items"]}
        assert "db-admin" not in codes

    @pytest.mark.asyncio
    async def test_搜索结果含similarity(self, admin_client, mock_db):
        _install_db(mock_db, [_plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")])
        resp = await admin_client.get("/api/v1/plaza/search", params={"q": "Oracle 备份"})
        items = resp.json()["data"]["items"]
        assert items and "similarity" in items[0]


class TestPlazaDetail:
    @pytest.mark.asyncio
    async def test_详情不存在返回10002(self, admin_client, mock_db):
        _install_db(mock_db, [], get_result=None)
        resp = await admin_client.get("/api/v1/plaza/999")
        assert resp.json()["code"] == 10002

    @pytest.mark.asyncio
    async def test_详情正常返回(self, admin_client, mock_db):
        plaza = _plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")
        _install_db(mock_db, [plaza], get_result=plaza)
        resp = await admin_client.get("/api/v1/plaza/1")
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["skill_code"] == "oracle-backup"
        assert body["data"]["blocked"] is False

    @pytest.mark.asyncio
    async def test_一般用户查看涉库详情被拒(self, user_client, mock_db):
        """需求 1.1.4：一般用户直接访问涉库广场 Skill 详情返回 10004"""
        plaza = _plaza(2, "db-tool", "数据库工具", flags=["database"])
        _install_db(mock_db, [plaza], get_result=plaza)
        resp = await user_client.get("/api/v1/plaza/2")
        assert resp.json()["code"] == 10004

    @pytest.mark.asyncio
    async def test_详情标记黑名单状态(self, user_client, mock_db):
        plaza = _plaza(1, "plain", "普通工具")
        _install_db(mock_db, [plaza], blocked=[1], get_result=plaza)
        resp = await user_client.get("/api/v1/plaza/1")
        assert resp.json()["data"]["blocked"] is True


class TestPlazaReadme:
    """GET /plaza/{id}/readme —— 双语 README（镜像 MCP get_skill_readme plaza 路径）"""

    @pytest.mark.asyncio
    async def test_readme返回双语正文(self, admin_client, mock_db):
        plaza = _plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")
        _install_db(mock_db, [plaza], get_result=plaza)
        with patch(
            "platform_mcp.api.plaza.generate_bilingual_readme",
            return_value=("中文README", "English README"),
        ) as gen:
            resp = await admin_client.get("/api/v1/plaza/1/readme")
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["skill_code"] == "oracle-backup"
        assert body["data"]["readme_zh"] == "中文README"
        assert body["data"]["readme_en"] == "English README"
        gen.assert_called_once()

    @pytest.mark.asyncio
    async def test_readme不存在返回10002(self, admin_client, mock_db):
        _install_db(mock_db, [], get_result=None)
        resp = await admin_client.get("/api/v1/plaza/999/readme")
        assert resp.json()["code"] == 10002

    @pytest.mark.asyncio
    async def test_一般用户读涉库readme被拒(self, user_client, mock_db):
        """需求 1.1.4：一般用户读涉库广场 Skill README 返回 10004（不触发正文生成）"""
        plaza = _plaza(2, "db-tool", "数据库工具", flags=["database"])
        _install_db(mock_db, [plaza], get_result=plaza)
        with patch("platform_mcp.api.plaza.generate_bilingual_readme") as gen:
            resp = await user_client.get("/api/v1/plaza/2/readme")
        assert resp.json()["code"] == 10004
        gen.assert_not_called()

    @pytest.mark.asyncio
    async def test_developer可读涉库readme(self, dev_client, mock_db):
        plaza = _plaza(2, "db-tool", "数据库工具", flags=["database"])
        _install_db(mock_db, [plaza], get_result=plaza)
        with patch(
            "platform_mcp.api.plaza.generate_bilingual_readme",
            return_value=("中文", "English"),
        ):
            resp = await dev_client.get("/api/v1/plaza/2/readme")
        assert resp.json()["code"] == 0


class TestPlazaCopy:
    """POST /plaza/{id}/copy —— "添加至我的"/复制到个人库（add_skill_to_my，架构 §19.5.7）"""

    @pytest.mark.asyncio
    async def test_复制到个人库成功(self, dev_client, mock_db):
        plaza = _plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")
        _install_db(mock_db, [plaza], get_result=plaza)
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await dev_client.post("/api/v1/plaza/1/copy")
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["skill_code"] == "oracle-backup"
        assert body["data"]["origin"] == "PLAZA"
        assert body["data"]["plaza_id"] == 1
        assert body["data"]["status"] == "ENABLED"

    @pytest.mark.asyncio
    async def test_一般用户复制涉库项被拒(self, user_client, mock_db):
        """需求 1.1.4：涉库广场 Skill 对一般用户不可见，复制返回 10004"""
        plaza = _plaza(2, "db-tool", "数据库工具", flags=["database"])
        _install_db(mock_db, [plaza], get_result=plaza)
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await user_client.post("/api/v1/plaza/2/copy")
        assert resp.json()["code"] == 10004

    @pytest.mark.asyncio
    async def test_复制不存在广场项返回10002(self, dev_client, mock_db):
        _install_db(mock_db, [], get_result=None)
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await dev_client.post("/api/v1/plaza/999/copy")
        assert resp.json()["code"] == 10002


class TestPlazaBlock:
    """POST /plaza/block、/plaza/unblock、GET /plaza/blocked —— 黑名单（F-34）"""

    @pytest.mark.asyncio
    async def test_屏蔽广场项成功(self, user_client, mock_db):
        _install_db(mock_db, [])
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await user_client.post("/api/v1/plaza/block", json={"plaza_id": 5, "reason": "不需要"})
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["plaza_id"] == 5

    @pytest.mark.asyncio
    async def test_屏蔽个人项成功(self, user_client, mock_db):
        _install_db(mock_db, [])
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await user_client.post("/api/v1/plaza/block", json={"skill_id": 7})
        assert resp.json()["data"]["skill_id"] == 7

    @pytest.mark.asyncio
    async def test_屏蔽二选一同时给出返回10003(self, user_client, mock_db):
        _install_db(mock_db, [])
        resp = await user_client.post("/api/v1/plaza/block", json={"plaza_id": 5, "skill_id": 7})
        assert resp.json()["code"] == 10003

    @pytest.mark.asyncio
    async def test_屏蔽二选一同时为空返回10003(self, user_client, mock_db):
        _install_db(mock_db, [])
        resp = await user_client.post("/api/v1/plaza/block", json={})
        assert resp.json()["code"] == 10003

    @pytest.mark.asyncio
    async def test_撤销屏蔽成功(self, user_client, mock_db):
        _install_db(mock_db, [])
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await user_client.post("/api/v1/plaza/unblock", json={"plaza_id": 5})
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_黑名单清单返回双类型(self, user_client, mock_db):
        entries = [
            PmcpSkillBlacklist(id=1, user_id=3, target_plaza_id=5),
            PmcpSkillBlacklist(id=2, user_id=3, target_skill_id=7),
        ]
        plaza = _plaza(5, "oracle-backup", "Oracle 备份")
        _install_db(mock_db, [plaza], blocked=entries)
        resp = await user_client.get("/api/v1/plaza/blocked")
        body = resp.json()
        assert body["code"] == 0
        types = {it["target_type"] for it in body["data"]["items"]}
        assert types == {"plaza", "skill"}


class TestPlazaDisable:
    """POST /plaza/{id}/disable —— 停用广场 Skill（仅 admin，幂等，停用后双端不可见）"""

    @pytest.mark.asyncio
    async def test_admin停用成功(self, admin_client, mock_db):
        plaza = _plaza(1, "oracle-backup", "Oracle 备份", "数据库备份")
        _install_db(mock_db, [plaza], get_result=plaza)
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await admin_client.post("/api/v1/plaza/1/disable")
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["plaza_id"] == 1
        assert body["data"]["status"] == "DISABLED"
        assert plaza.status == "DISABLED"

    @pytest.mark.asyncio
    async def test_非admin停用被拒11001(self, dev_client, mock_db):
        """require_admin：developer 角色无权停用（AuthError → 400 + 11001）"""
        _install_db(mock_db, [])
        resp = await dev_client.post("/api/v1/plaza/1/disable")
        assert resp.status_code == 400
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_停用不存在返回10002(self, admin_client, mock_db):
        _install_db(mock_db, [], get_result=None)
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await admin_client.post("/api/v1/plaza/999/disable")
        assert resp.json()["code"] == 10002
