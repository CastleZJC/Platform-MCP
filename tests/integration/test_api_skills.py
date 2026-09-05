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

    @staticmethod
    def _mk_skill(sid, code, status, share, owner, reg="upload"):
        s = MagicMock()
        s.id = sid
        s.skill_code = code
        s.skill_name = code
        s.status = status
        s.share_status = share
        s.inserted_by = owner
        s.register_method = reg
        s.tool_count = 0
        s.description = None
        s.version = None
        s.source_format = None
        s.audit_status = None
        s.readme_generated = False
        s.inserted_at = None
        s.plaza_id = None
        s.origin = "ORIGINAL"
        s.review_comment = None
        return s

    @staticmethod
    def _dispatch_execute(rows):
        """按 SQL 文本分派：黑名单查询（F-34）返回空，个人库查询返回 rows。

        list_skills 新增 load_blocked_skill_ids 查询（pmcp_skill_blacklist），单一 result mock 会
        把 skill 行误当黑名单标量（int(MagicMock)==1）；此处隔离两类查询保持用例语义纯净。
        """
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows

        async def _exec(stmt, params=None):
            return empty if "pmcp_skill_blacklist" in str(stmt) else result

        return AsyncMock(side_effect=_exec)

    @pytest.mark.asyncio
    async def test_list_skills_admin_visibility_matrix(self, admin_client, mock_db):
        """F-27：admin 个人库仅见审核态 + 广场已发布态；不见他人草稿/已拒绝/未分享已启用"""
        from unittest.mock import patch
        rows = [
            self._mk_skill(1, "draft_other", "DRAFT", "unshared", "dev01"),
            self._mk_skill(2, "pending_other", "PENDING_REVIEW", "unshared", "dev01"),
            self._mk_skill(3, "enabled_shared", "ENABLED", "shared", "dev01"),
            self._mk_skill(4, "enabled_private", "ENABLED", "unshared", "dev01"),
            self._mk_skill(5, "rejected_other", "REJECTED", "unshared", "dev01"),
        ]
        mock_db.execute = self._dispatch_execute(rows)
        with patch("platform_mcp.api.skills.get_skill_instance", return_value=None):
            resp = await admin_client.get("/api/v1/skills")
        codes = [it["skill_code"] for it in resp.json()["data"]["items"]]
        assert "pending_other" in codes        # 审核态 admin 可见
        assert "enabled_shared" in codes       # 广场已发布 admin 可见
        assert "draft_other" not in codes      # 他人草稿 admin 不可见
        assert "rejected_other" not in codes   # 他人已拒绝 admin 不可见
        assert "enabled_private" not in codes  # 未分享已启用 admin 不可见

    @pytest.mark.asyncio
    async def test_list_skills_owner_sees_own_all_states(self, dev_client, mock_db):
        """F-27：本人可见自己全部状态（含草稿/已拒绝/撤回）；不见他人 Skill"""
        from unittest.mock import patch
        rows = [
            self._mk_skill(1, "own_draft", "DRAFT", "unshared", "dev01"),
            self._mk_skill(2, "own_rejected", "REJECTED", "unshared", "dev01"),
            self._mk_skill(3, "own_withdrawn", "WITHDRAWN", "unshared", "dev01"),
            self._mk_skill(4, "other_pending", "PENDING_REVIEW", "unshared", "dev02"),
        ]
        mock_db.execute = self._dispatch_execute(rows)
        with patch("platform_mcp.api.skills.get_skill_instance", return_value=None):
            resp = await dev_client.get("/api/v1/skills")
        codes = [it["skill_code"] for it in resp.json()["data"]["items"]]
        assert "own_draft" in codes
        assert "own_rejected" in codes
        assert "own_withdrawn" in codes
        assert "other_pending" not in codes  # developer 看不到他人个人库 Skill

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
        """审核 approve（委托 SkillReviewService：PENDING_REVIEW → APPROVED → ENABLED + 入广场）"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = "PENDING_REVIEW"
        mock_skill.share_status = "private"
        mock_skill.plaza_id = None
        mock_skill.review_comment = None
        mock_skill.inserted_by = "admin"
        mock_skill.origin = "SELF"
        mock_db.get = AsyncMock(return_value=mock_skill)
        # execute 沿用 conftest mock_db 默认（scalar_one_or_none=None / scalars().all()=[]）：
        # 广场副本查询返回 None → 新建 PmcpSkillPlaza（flush 被 mock，plaza_id=None）
        resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "approve"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["new_status"] == "ENABLED"
        assert body["data"]["share_status"] == "shared"

    @pytest.mark.asyncio
    async def test_review_skill_reject(self, admin_client, mock_db):
        """审核 reject（委托 SkillReviewService：PENDING_REVIEW → REJECTED，拒绝原因 owner 可见）"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = "PENDING_REVIEW"
        mock_skill.share_status = "private"
        mock_skill.plaza_id = None
        mock_skill.review_comment = None
        mock_skill.inserted_by = "admin"
        mock_skill.origin = "SELF"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await admin_client.post(
            "/api/v1/skills/1/review", json={"action": "reject", "comment": "缺少说明"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["new_status"] == "REJECTED"
        assert body["data"]["review_comment"] == "缺少说明"

    @pytest.mark.asyncio
    async def test_review_skill_merge(self, admin_client, mock_db):
        """审核 merge（origin=PLAZA）：PENDING_REVIEW → SHARE_ITERATION（F-30 合并到广场已有）"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = "PENDING_REVIEW"
        mock_skill.share_status = "shared"
        mock_skill.plaza_id = None
        mock_skill.review_comment = None
        mock_skill.inserted_by = "admin"
        mock_skill.origin = "PLAZA"
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_plaza = MagicMock()
        mock_plaza.id = 5
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_plaza
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.post(
            "/api/v1/skills/1/review", json={"action": "merge", "comment": "合并到广场版本"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["new_status"] == "SHARE_ITERATION"

    @pytest.mark.asyncio
    async def test_review_skill_approve_audits_as_skill(self, admin_client, mock_db):
        """F-40：approve 委托 review.service 后审计 resource_type='skill'、action='review_approve'"""
        from unittest.mock import patch

        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.skill_name = "Database"
        mock_skill.status = "PENDING_REVIEW"
        mock_skill.share_status = "private"
        mock_skill.plaza_id = None
        mock_skill.review_comment = None
        mock_skill.inserted_by = "admin"
        mock_skill.origin = "SELF"
        mock_db.get = AsyncMock(return_value=mock_skill)
        with patch(
            "platform_mcp.review.service.write_audit_log", new_callable=AsyncMock
        ) as audit_mock:
            resp = await admin_client.post("/api/v1/skills/1/review", json={"action": "approve"})
        assert resp.status_code == 200
        assert audit_mock.await_count >= 1
        kwargs = audit_mock.await_args.kwargs
        assert kwargs["resource_type"] == "skill"
        assert kwargs["extra_data"]["action"] == "review_approve"

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

    # ==================== M2.7 Web owner 通道 + 版本存档查询（F-28/F-31/F-32/F-30/F-43）====================

    @pytest.mark.asyncio
    async def test_list_skill_versions(self, admin_client, mock_db):
        """F-28：版本存档查询返回按版本存档的双语 README / 审核报告（versions[0] 最新）"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.version = "0.2.0"
        mock_db.get = AsyncMock(return_value=mock_skill)
        mock_version = MagicMock()
        mock_version.version = "0.2.0"
        mock_version.checksum = "abc123"
        mock_version.generated_by = "template"
        mock_version.readme_zh = "# 说明"
        mock_version.readme_en = "# README"
        mock_version.report_zh = "审核报告"
        mock_version.report_en = "audit report"
        mock_version.audit_snapshot = {"critical_count": 0}
        mock_version.inserted_at = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_version]
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await admin_client.get("/api/v1/skills/1/versions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["current_version"] == "0.2.0"
        assert len(body["data"]["versions"]) == 1
        assert body["data"]["versions"][0]["readme_zh"] == "# 说明"
        assert body["data"]["versions"][0]["generated_by"] == "template"

    @pytest.mark.asyncio
    async def test_list_skill_versions_nonexistent(self, admin_client, mock_db):
        """版本存档查询不存在 Skill 应返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await admin_client.get("/api/v1/skills/9999/versions")
        assert resp.status_code == 200
        assert resp.json()["code"] == 10002

    @pytest.mark.asyncio
    async def test_submit_skill_for_review(self, dev_client, mock_db):
        """F-43：owner 提交分享审核（委托 review.service）DRAFT → PENDING_REVIEW"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.status = "DRAFT"
        mock_skill.share_status = "private"
        mock_skill.plaza_id = None
        mock_skill.review_comment = None
        mock_skill.inserted_by = "dev01"
        mock_skill.version = "0.1.0"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await dev_client.post("/api/v1/skills/1/submit", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["new_status"] == "PENDING_REVIEW"

    @pytest.mark.asyncio
    async def test_submit_skill_reshare_needs_confirm(self, dev_client, mock_db):
        """F-31：已分享 Skill 未带 confirm_reshare 重提 → code=10005 二次确认"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.status = "ENABLED"
        mock_skill.share_status = "shared"
        mock_skill.plaza_id = 7
        mock_skill.review_comment = None
        mock_skill.inserted_by = "dev01"
        mock_skill.version = "0.1.0"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await dev_client.post("/api/v1/skills/1/submit", json={})
        assert resp.status_code == 200
        assert resp.json()["code"] == 10005

    @pytest.mark.asyncio
    async def test_withdraw_skill_review(self, dev_client, mock_db):
        """F-32：owner 撤回审核（委托 review.service）PENDING_REVIEW → WITHDRAWN"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.status = "PENDING_REVIEW"
        mock_skill.share_status = "private"
        mock_skill.plaza_id = None
        mock_skill.review_comment = None
        mock_skill.inserted_by = "dev01"
        mock_skill.version = "0.1.0"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await dev_client.post("/api/v1/skills/1/withdraw")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["new_status"] == "WITHDRAWN"

    @pytest.mark.asyncio
    async def test_resolve_share_iteration(self, dev_client, mock_db):
        """F-30：owner 解决分享迭代（委托 review.service）SHARE_ITERATION → ENABLED"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.status = "SHARE_ITERATION"
        mock_skill.share_status = "shared"
        mock_skill.plaza_id = 7
        mock_skill.review_comment = None
        mock_skill.inserted_by = "dev01"
        mock_skill.version = "0.1.0"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await dev_client.post("/api/v1/skills/1/resolve-iteration", json={"choice": "iterate"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["new_status"] == "ENABLED"

    @pytest.mark.asyncio
    async def test_resolve_share_iteration_invalid_choice(self, dev_client, mock_db):
        """解决分享迭代非法 choice 应返回 400"""
        resp = await dev_client.post("/api/v1/skills/1/resolve-iteration", json={"choice": "bad"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_remove_my_skill_success(self, dev_client, mock_db):
        """remove_my_skill（Web DELETE，架构 §19.5.7 / F-29）：本人可移除自己上传的 Skill"""
        from unittest.mock import patch
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "demo"
        mock_skill.inserted_by = "dev01"
        mock_skill.register_method = "upload"
        mock_skill.origin = "ORIGINAL"
        mock_db.get = AsyncMock(return_value=mock_skill)
        with patch("platform_mcp.skills.plaza_service.write_audit_log", new=AsyncMock()):
            resp = await dev_client.delete("/api/v1/skills/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_remove_my_skill_not_owner_forbidden(self, dev_client, mock_db):
        """非本人移除他人 Skill 返回 10004（F-29）"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "demo"
        mock_skill.inserted_by = "dev02"
        mock_skill.register_method = "upload"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await dev_client.delete("/api/v1/skills/1")
        assert resp.json()["code"] == 10004

    @pytest.mark.asyncio
    async def test_remove_builtin_skill_rejected(self, dev_client, mock_db):
        """内置装饰器 Skill（database/server）不可移除，返回 10003"""
        mock_skill = MagicMock()
        mock_skill.id = 1
        mock_skill.skill_code = "database"
        mock_skill.inserted_by = "dev01"
        mock_skill.register_method = "decorator"
        mock_db.get = AsyncMock(return_value=mock_skill)
        resp = await dev_client.delete("/api/v1/skills/1")
        assert resp.json()["code"] == 10003

    @pytest.mark.asyncio
    async def test_remove_skill_not_found(self, dev_client, mock_db):
        """移除不存在的 Skill 返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await dev_client.delete("/api/v1/skills/999")
        assert resp.json()["code"] == 10002

    # ==================== M4 分享迭代差异查询 + 后台升级任务（F-30 / F-35 / VNF-01）====================

    @staticmethod
    def _mk_iteration_skill(inserted_by="dev01", status="SHARE_ITERATION"):
        s = MagicMock()
        s.id = 1
        s.skill_code = "demo-skill"
        s.skill_name = "Demo"
        s.status = status
        s.share_status = "shared"
        s.plaza_id = 7
        s.origin = "PLAZA"
        s.inserted_by = inserted_by
        s.version = "0.1.0"
        s.source_path = "Z:/nope"
        return s

    @pytest.mark.asyncio
    async def test_get_iteration_diff_owner(self, dev_client, mock_db):
        """M4.3：owner 查询分享迭代差异（本地 vs 广场快照，模板兜底口径）"""
        mock_db.get = AsyncMock(return_value=self._mk_iteration_skill())
        mock_plaza = MagicMock()
        mock_plaza.id = 7
        mock_plaza.skill_code = "demo-skill"
        mock_plaza.source_path = "Z:/nope-plaza"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_plaza
        mock_db.execute = AsyncMock(return_value=mock_result)
        resp = await dev_client.get("/api/v1/skills/1/iteration-diff")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        # 模板兜底口径（测试环境无本地权重）：留痕 + 双语描述 + 无性能提示
        assert data["generated_by"] == "template"
        assert data["description_zh"] and data["description_en"]
        assert data["performance_hint_zh"] is None
        assert "unified_diff" in data and "similarity" in data

    @pytest.mark.asyncio
    async def test_get_iteration_diff_wrong_state(self, dev_client, mock_db):
        """非 SHARE_ITERATION 态查询差异返回 10003"""
        mock_db.get = AsyncMock(return_value=self._mk_iteration_skill(status="ENABLED"))
        resp = await dev_client.get("/api/v1/skills/1/iteration-diff")
        assert resp.json()["code"] == 10003

    @pytest.mark.asyncio
    async def test_get_iteration_diff_not_owner_forbidden(self, user_client, mock_db):
        """非 owner 非 admin 查询差异返回 10004"""
        mock_db.get = AsyncMock(return_value=self._mk_iteration_skill(inserted_by="dev01"))
        resp = await user_client.get("/api/v1/skills/1/iteration-diff")
        assert resp.json()["code"] == 10004

    @pytest.mark.asyncio
    async def test_get_iteration_diff_not_found(self, dev_client, mock_db):
        """查询不存在 Skill 的差异返回 10002"""
        mock_db.get = AsyncMock(return_value=None)
        resp = await dev_client.get("/api/v1/skills/999/iteration-diff")
        assert resp.json()["code"] == 10002

    @pytest.mark.asyncio
    async def test_upload_schedules_background_upgrade(self, dev_client, mock_db):
        """M4.2：上传成功后 BackgroundTasks 挂接存档升级任务（响应后执行，不阻塞主链路）"""
        from unittest.mock import patch

        upload_result = MagicMock()
        upload_result.skill_id = 12
        upload_result.skill_code = "demo-skill"
        upload_result.skill_name = "Demo"
        upload_result.description = None
        upload_result.version = "0.1.0"
        upload_result.audit_result.critical_count = 0
        upload_result.audit_result.warning_count = 0
        upload_result.audit_result.to_audit_summary.return_value = {"total_rules": 14}
        upload_result.sanitization_passed = True
        upload_result.readme_generated = True
        upload_result.source_format = "zip"
        upload_result.is_update = False

        upgrade = AsyncMock(return_value=False)
        with patch("platform_mcp.api.skills.process_skill_upload",
                   new=AsyncMock(return_value=upload_result)), \
                patch("platform_mcp.api.skills.write_audit_log", new=AsyncMock()), \
                patch("platform_mcp.skills.llm.tasks.upgrade_version_artifacts", upgrade):
            resp = await dev_client.post(
                "/api/v1/skills/upload",
                files={"file": ("demo.zip", b"fake-zip", "application/zip")},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        # 响应返回后后台任务已执行（ASGITransport 等待 app 完成），参数口径：skill_id + version + operator
        upgrade.assert_awaited_once()
        assert upgrade.await_args.args == (12, "0.1.0")
        assert upgrade.await_args.kwargs == {"operator": "dev01"}