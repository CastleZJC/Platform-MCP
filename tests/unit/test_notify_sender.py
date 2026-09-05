"""M5 单元测试 — SMTP 发送器与 outbox flush（F-38，R-13）

覆盖：
- get_smtp_config：smtp.* 运行时配置读取（未配置 host → None；port int 归一）；
- flush_outbox：SMTP 未配置保持 pending（R-13 堆积待发不报错）、发送成功回写
  sent+sent_at、单条失败 retry_count+1+error_message 留痕（失败可审计可重试）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.notify import sender


def _smtp_rc(values: dict):
    """runtime_config 单例 mock：get(key) 按表取值。"""
    rc = MagicMock()
    rc.get = AsyncMock(side_effect=lambda k: values.get(k))
    return rc


def _rows_session(rows):
    """flush_outbox 的 get_session_factory()() 两层调用 mock；未配置分支用 .all()，
    取件分支用 .scalars().all()，两者均返回 rows。"""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    maker = MagicMock(return_value=_Ctx())
    factory = MagicMock(return_value=maker)
    return factory, session


def _outbox_row(id_=1, retry=0, recipient="a@x.com"):
    row = MagicMock()
    row.id = id_
    row.recipient = recipient
    row.subject = "s"
    row.body = "b"
    row.status = "pending"
    row.retry_count = retry
    row.error_message = None
    row.sent_at = None
    return row


class TestGetSmtpConfig:
    @pytest.mark.asyncio
    async def test_unconfigured_host_returns_none(self):
        """SMTP host 未配置 → None（生产前置依赖 R-13，未配置不发送）"""
        with patch("platform_mcp.common.runtime_config.runtime_config",
                   _smtp_rc({"smtp.host": None})):
            assert await sender.get_smtp_config() is None

    @pytest.mark.asyncio
    async def test_blank_host_returns_none(self):
        with patch("platform_mcp.common.runtime_config.runtime_config",
                   _smtp_rc({"smtp.host": "  "})):
            assert await sender.get_smtp_config() is None

    @pytest.mark.asyncio
    async def test_full_config_read_with_port_int(self):
        values = {"smtp.host": "smtp.x.com", "smtp.port": "587",
                  "smtp.user": "u", "smtp.password": "p", "smtp.from": "no@x.com"}
        with patch("platform_mcp.common.runtime_config.runtime_config", _smtp_rc(values)):
            cfg = await sender.get_smtp_config()
        assert cfg == {"host": "smtp.x.com", "port": 587, "user": "u",
                       "password": "p", "from": "no@x.com"}

    @pytest.mark.asyncio
    async def test_defaults_port_25_when_missing(self):
        values = {"smtp.host": "smtp.x.com"}
        with patch("platform_mcp.common.runtime_config.runtime_config", _smtp_rc(values)):
            cfg = await sender.get_smtp_config()
        assert cfg["port"] == 25
        assert cfg["from"] == ""


class TestFlushOutbox:
    @pytest.mark.asyncio
    async def test_smtp_unconfigured_keeps_pending(self):
        """SMTP 未配置：不取件不报错，仅统计积压（保持 pending 堆积待发，R-13）"""
        factory, session = _rows_session([(1,), (2,), (3,)])
        with patch("platform_mcp.common.database.get_session_factory", factory), \
                patch.object(sender, "get_smtp_config", AsyncMock(return_value=None)):
            result = await sender.flush_outbox()
        assert result == {"sent": 0, "failed": 0, "pending": 3}
        session.commit.assert_not_awaited()  # 未动件

    @pytest.mark.asyncio
    async def test_send_success_marks_sent(self):
        row = _outbox_row()
        factory, session = _rows_session([row])
        smtp = {"host": "h", "port": 25, "user": "", "password": "", "from": ""}
        with patch("platform_mcp.common.database.get_session_factory", factory), \
                patch.object(sender, "get_smtp_config", AsyncMock(return_value=smtp)), \
                patch.object(sender, "send_via_smtp", AsyncMock()) as mock_send:
            result = await sender.flush_outbox()
        assert result == {"sent": 1, "failed": 0, "pending": 0}
        assert row.status == "sent"
        assert row.sent_at is not None
        assert row.error_message is None
        mock_send.assert_awaited_once_with("a@x.com", "s", "b", smtp)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_failure_marks_failed_with_retry(self):
        """单条失败：failed + retry_count+1 + error_message 留痕（F-38 可重试可审计）"""
        row = _outbox_row(retry=2)
        factory, session = _rows_session([row])
        smtp = {"host": "h", "port": 25, "user": "", "password": "", "from": ""}
        with patch("platform_mcp.common.database.get_session_factory", factory), \
                patch.object(sender, "get_smtp_config", AsyncMock(return_value=smtp)), \
                patch.object(sender, "send_via_smtp",
                             AsyncMock(side_effect=RuntimeError("connect refused"))):
            result = await sender.flush_outbox()
        assert result == {"sent": 0, "failed": 1, "pending": 0}
        assert row.status == "failed"
        assert row.retry_count == 3
        assert "connect refused" in row.error_message
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_failure_continues_batch(self):
        """批量中单条失败不中断本轮其余条目（失败可审计，其余照发）"""
        bad_row = _outbox_row(1, recipient="bad@x.com")
        ok_row = _outbox_row(2, recipient="ok@x.com")
        factory, session = _rows_session([bad_row, ok_row])
        smtp = {"host": "h", "port": 25, "user": "", "password": "", "from": ""}

        async def _flaky(recipient, subject, body, cfg):
            if recipient == "bad@x.com":
                raise RuntimeError("timeout")

        with patch("platform_mcp.common.database.get_session_factory", factory), \
                patch.object(sender, "get_smtp_config", AsyncMock(return_value=smtp)), \
                patch.object(sender, "send_via_smtp", side_effect=_flaky):
            result = await sender.flush_outbox()
        assert result == {"sent": 1, "failed": 1, "pending": 0}
        assert bad_row.status == "failed"
        assert bad_row.retry_count == 1
        assert "timeout" in bad_row.error_message
        assert ok_row.status == "sent"  # 首条失败不阻断后续
        session.commit.assert_awaited_once()
