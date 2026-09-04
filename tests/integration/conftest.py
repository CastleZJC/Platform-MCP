"""Integration test 专用 conftest — 自动 patch 写真实 DB 的副作用"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
async def _mock_audit_log_for_integration():
    """P0-0 修复：自动 patch 所有业务模块的 write_audit_log 引用

    根因：write_audit_log 通过全局 async_session_factory() 绕过 mock_db 写真实 DB。
    Integration test 并发执行时，asyncpg 同一 connection 不允许并发操作，
    触发 `cannot perform operation: another operation is in progress`。

    修复策略：integration test 全局 mock write_audit_log，避免触真实 DB。
    需要验证审计调用的测试，可在测试内单独 patch 并断言 mock 调用。
    """
    audit_modules = ["auth", "api_keys", "crypto", "users", "skills", "datasources", "servers", "profile", "groups", "system_config"]
    audit_patches = [
        patch(f"platform_mcp.api.{m}.write_audit_log", new_callable=AsyncMock)
        for m in audit_modules
    ]
    # V3.0 M2.6：Web skill 审核端点委托 review.service（状态机 + 广场副本 + resource_type="skill" 审计），
    # 其 write_audit_log 亦经独立 session 触真实 DB，需一并 mock。
    audit_patches.append(
        patch("platform_mcp.review.service.write_audit_log", new_callable=AsyncMock)
    )
    for p in audit_patches:
        p.start()
    try:
        yield
    finally:
        for p in audit_patches:
            p.stop()
