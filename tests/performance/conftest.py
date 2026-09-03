"""Performance test 专用 conftest — 隔离写真实 DB 的副作用（沿用 integration P0-0 先例）

根因同 integration/conftest.py：write_audit_log 经全局 async_session_factory() 绕过
测试的 get_db override 直写真实 DB。性能测试 50 并发下触发 asyncpg
`cannot perform operation: another operation is in progress`，且 settings-dev 的
database.echo=true 使每条 SQL 全文同步回显控制台，P95 被日志 I/O 污染。

修复策略：mock write_audit_log，使性能用例度量"接口层并发处理时延"这一本来目标
（登录链路的 DB INSERT 时延属于 DB 基准，不在本目录度量范围）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
async def _mock_audit_log_for_performance():
    audit_modules = ["auth", "api_keys", "crypto", "users", "skills", "datasources", "servers", "profile", "groups", "system_config"]
    audit_patches = [
        patch(f"platform_mcp.api.{m}.write_audit_log", new_callable=AsyncMock)
        for m in audit_modules
    ]
    for p in audit_patches:
        p.start()
    try:
        yield
    finally:
        for p in audit_patches:
            p.stop()
