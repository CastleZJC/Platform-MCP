"""Oracle 超时可中断执行（BUG20260824 次级2）— 用例

契约：thick 模式执行线程不可取消 → 超时后 conn.break_()（OOB，线程安全）打断
在飞调用 → 回收线程 → 连接关闭（服务端会话终止）；超时结果附 source_session
（sid/serial）供审计追踪。修复前：超时即放弃，服务端会话继续执行已超时语句，
拖垮共享目标库（新连接 ORA-12170 持续数十分钟）。
"""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.skills.database.executor import SQLExecutor


class _BlockingCursor:
    """模拟 thick 模式阻塞在驱动调用：直到 break_ 触发事件才抛"被打断"错误。"""

    def __init__(self, release: threading.Event):
        self._release = release
        self.description = None
        self.rowcount = 0
        self.interrupted = False

    def execute(self, sql):
        if "heavy" not in sql:  # 普通语句直通，仅 heavy 语句阻塞在飞
            return
        if not self._release.wait(timeout=30):
            raise RuntimeError("not interrupted within 30s")
        self.interrupted = True
        raise RuntimeError("DPI-1081: connection interrupted by break")

    def close(self):
        pass


class _FakeOracleConn:
    def __init__(self):
        self._release = threading.Event()
        self.session_id = 123
        self.serial_num = 456
        self.broken = False
        self.closed = False
        self.cursor_instance = _BlockingCursor(self._release)

    def cursor(self):
        return self.cursor_instance

    def break_(self):
        self.broken = True
        self._release.set()

    def close(self):
        self.closed = True

    def commit(self):
        pass

    def rollback(self):
        pass


def _oracle_params() -> ConnectionParams:
    return ConnectionParams(
        db_type="oracle", host="10.0.0.1", port=1521,
        username="u", password="p", datasource_code="ds_timeout",
    )


@pytest.mark.asyncio
async def test_超时后break打断在飞调用并按超时上报():
    executor = SQLExecutor()
    conn = _FakeOracleConn()
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(side_effect=lambda exc_t, exc, tb: conn.close())

    with patch("platform_mcp.skills.database.executor.get_connection", return_value=conn_ctx):
        result = await executor.execute_query(_oracle_params(), "SELECT heavy FROM big", timeout=1)

    assert result.success is False
    assert "SQL 执行超时" in (result.error_message or "")
    assert conn.broken is True                      # OOB break 已发出
    assert conn.cursor_instance.interrupted is True # 执行线程已被打断并退出（回收）
    assert conn.closed is True                      # 连接关闭（服务端会话终止路径）
    assert result.source_session == {"type": "oracle", "sid": 123, "serial": 456}


@pytest.mark.asyncio
async def test_超时结果经execute_statements失败即停():
    executor = SQLExecutor()
    conn = _FakeOracleConn()
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(side_effect=lambda exc_t, exc, tb: conn.close())

    with patch("platform_mcp.skills.database.executor.get_connection", return_value=conn_ctx):
        results = await executor.execute_statements(
            ["SELECT 1 FROM dual", "SELECT heavy FROM big"], _oracle_params(), timeout=1
        )

    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is False
    assert conn.broken is True
