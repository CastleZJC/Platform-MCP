"""mcp_server.transfer HTTP 端点测试 — BUG20260814163941（BUG-1/4/5）

覆盖：API Key 认证（401/200）、上传/下载/删除闭环、
路径穿越拒绝、非法参数 400、超限 413。
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from starlette.applications import Starlette

from platform_mcp.mcp_server import _AuthMiddleware
from platform_mcp.mcp_server.transfer import build_transfer_routes
from platform_mcp.skills.server import transfer


@pytest.fixture
def app(tmp_path):
    transfer.reset_exchange_dir_cache()
    with patch("platform_mcp.config.get_settings") as gs:
        gs.return_value.datasource.sftp_exchange_dir = str(tmp_path / "exchange")
        application = Starlette(routes=build_transfer_routes())
        application.add_middleware(_AuthMiddleware)
        yield application
    transfer.reset_exchange_dir_cache()


@pytest.fixture
def client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"PLATFORM_MCP_API_KEY": "pmcp_test_key"},
    )


@pytest.fixture
def authed(app):
    with patch(
        "platform_mcp.mcp_server._validate_api_key_async",
        return_value={"user_id": 1, "username": "admin", "role_code": "admin"},
    ):
        yield


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(client):
    resp = await client.post(
        "/transfer/upload?filename=x.zip", content=b"x", headers={"PLATFORM_MCP_API_KEY": ""}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401(client):
    with patch("platform_mcp.mcp_server._validate_api_key_async", return_value=None):
        resp = await client.post("/transfer/upload?filename=x.zip", content=b"x")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_then_download_roundtrip(client, authed):
    resp = await client.post("/transfer/upload?filename=pkg.zip", content=b"hello-sftp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "pkg.zip"
    assert body["size"] == 10
    staged = transfer.stage_path(body["transfer_id"], "pkg.zip")
    assert staged.read_bytes() == b"hello-sftp"

    resp2 = await client.get(f"/transfer/download/{body['transfer_id']}/pkg.zip")
    assert resp2.status_code == 200
    assert resp2.content == b"hello-sftp"


@pytest.mark.asyncio
async def test_upload_rejects_traversal_filename(client, authed):
    resp = await client.post("/transfer/upload?filename=..%2Fescape.zip", content=b"x")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_missing_filename(client, authed):
    resp = await client.post("/transfer/upload", content=b"x")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_download_rejects_invalid_transfer_id(client, authed):
    resp = await client.get("/transfer/download/not-a-uuid/x.zip")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_download_missing_file_returns_404(client, authed):
    tid = transfer.new_transfer_id()
    resp = await client.get(f"/transfer/download/{tid}/x.zip")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_cleans_transfer_dir(client, authed):
    resp = await client.post("/transfer/upload?filename=y.zip", content=b"y")
    tid = resp.json()["transfer_id"]
    resp2 = await client.delete(f"/transfer/{tid}")
    assert resp2.status_code == 200
    assert resp2.json()["cleaned"] is True
    assert not (transfer.get_exchange_dir() / tid).exists()
    # 重复删除 → 404
    resp3 = await client.delete(f"/transfer/{tid}")
    assert resp3.status_code == 404


@pytest.mark.asyncio
async def test_delete_rejects_invalid_transfer_id(client, authed):
    resp = await client.delete("/transfer/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_info_returns_exchange_dir(client, authed):
    resp = await client.get("/transfer/info")
    assert resp.status_code == 200
    assert "exchange_dir" in resp.json()


@pytest.mark.asyncio
async def test_upload_over_500mb_declared_rejected(client, authed):
    resp = await client.post(
        "/transfer/upload?filename=big.zip",
        content=b"x",
        headers={"content-length": str(500 * 1024 * 1024 + 1)},
    )
    assert resp.status_code == 413
