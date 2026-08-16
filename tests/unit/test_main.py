"""main.py 单元测试 — lifespan / setup_logging / error handlers / health"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def test_setup_logging_无log_dir():
    mock_settings = MagicMock()
    mock_settings.log.level = "INFO"
    mock_settings.log.dir = None

    with patch("loguru.logger") as mock_logger:
        from platform_mcp.main import _setup_logging
        _setup_logging(mock_settings)
        mock_logger.remove.assert_called_once()
        assert mock_logger.add.call_count == 1


def test_setup_logging_有log_dir():
    mock_settings = MagicMock()
    mock_settings.log.level = "DEBUG"
    mock_settings.log.dir = "/tmp/logs"
    mock_settings.log.rotation = "10 MB"
    mock_settings.log.retention = "7 days"

    with patch("loguru.logger") as mock_logger, \
         patch("pathlib.Path") as mock_path_cls:
        mock_path_inst = MagicMock()
        mock_path_cls.return_value = mock_path_inst
        from platform_mcp.main import _setup_logging
        _setup_logging(mock_settings)
        assert mock_logger.add.call_count == 2
        mock_path_inst.mkdir.assert_called_once_with(exist_ok=True)


@pytest.mark.asyncio
async def test_health():
    from platform_mcp.main import health
    result = await health()
    assert result == {"status": "UP"}


def test_lifespan():
    with patch("platform_mcp.main.get_settings") as mock_gs, \
         patch("platform_mcp.main._setup_logging") as mock_setup:
        mock_gs.return_value = MagicMock()
        from platform_mcp.main import lifespan
        import asyncio
        app = MagicMock()
        async def run_lifespan():
            async with lifespan(app):
                pass
        asyncio.get_event_loop().run_until_complete(run_lifespan())
        mock_setup.assert_called_once()


@pytest.mark.asyncio
async def test_base_error_handler():
    from platform_mcp.common.exceptions import BaseError
    from platform_mcp.main import base_error_handler

    mock_request = MagicMock()
    mock_request.state.trace_id = "t1"
    exc = BaseError(error_code=11001, message="测试错误")

    result = await base_error_handler(mock_request, exc)
    assert result.status_code == 400
    body = json.loads(result.body)
    assert body["code"] == 11001
    assert body["message"] == "测试错误"


@pytest.mark.asyncio
async def test_generic_error_handler():
    from platform_mcp.main import generic_error_handler

    mock_request = MagicMock()
    mock_request.state.trace_id = "t2"
    exc = RuntimeError("unexpected")

    result = await generic_error_handler(mock_request, exc)
    assert result.status_code == 500
    body = json.loads(result.body)
    assert body["code"] == 15001
    assert "unexpected" in body["message"]


class TestSpaStaticFilesCacheHeaders:
    """20260816 生产事件回归：assets 无缓存头 + mtime=0 → 浏览器启发式缓存数年 → 旧 chunk 404 页面空白"""

    @pytest.fixture()
    def spa_dir(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "app-ABC123.js").write_text("console.log(1)")
        (tmp_path / "index.html").write_text("<html>spa-entry</html>")
        return tmp_path

    @staticmethod
    def _scope():
        return {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}

    @pytest.mark.asyncio
    async def test_assets响应带immutable长缓存头(self, spa_dir):
        from platform_mcp.main import _SpaStaticFiles

        app = _SpaStaticFiles(directory=str(spa_dir), html=True)
        resp = await app.get_response("assets/app-ABC123.js", self._scope())
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    @pytest.mark.asyncio
    async def test_index_html响应带no_cache头(self, spa_dir):
        from platform_mcp.main import _SpaStaticFiles

        app = _SpaStaticFiles(directory=str(spa_dir), html=True)
        resp = await app.get_response("index.html", self._scope())
        assert resp.headers["cache-control"] == "no-cache, must-revalidate"

    @pytest.mark.asyncio
    async def test_spa子路径fallback回index且no_cache(self, spa_dir):
        from platform_mcp.main import _SpaStaticFiles

        app = _SpaStaticFiles(directory=str(spa_dir), html=True)
        resp = await app.get_response("audit", self._scope())
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert resp.headers["cache-control"] == "no-cache, must-revalidate"

    @pytest.mark.asyncio
    async def test_assets缺失文件仍404不走fallback(self, spa_dir):
        from starlette.exceptions import HTTPException

        from platform_mcp.main import _SpaStaticFiles

        app = _SpaStaticFiles(directory=str(spa_dir), html=True)
        with pytest.raises(HTTPException) as ei:
            await app.get_response("assets/gone-XYZ.js", self._scope())
        assert ei.value.status_code == 404
