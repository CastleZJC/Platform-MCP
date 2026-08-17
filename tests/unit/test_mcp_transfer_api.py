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


@pytest.mark.asyncio
async def test_chunk_upload_then_merge_roundtrip(client, authed):
    # 首片不带 transfer_id，服务端生成并返回
    r1 = await client.post("/transfer/chunk?index=0", content=b"abc")
    assert r1.status_code == 200
    tid = r1.json()["transfer_id"]
    assert r1.json()["received"] == 3

    # 后续片带同一 transfer_id
    r2 = await client.post(f"/transfer/chunk?transfer_id={tid}&index=1", content=b"def")
    assert r2.status_code == 200
    assert r2.json()["transfer_id"] == tid

    # 合并
    r3 = await client.post(
        "/transfer/merge",
        json={"transfer_id": tid, "filename": "big.bin", "total_size": 6},
    )
    assert r3.status_code == 200
    assert r3.json()["size"] == 6
    staged = transfer.stage_path(tid, "big.bin")
    assert staged.read_bytes() == b"abcdef"
    assert not (transfer.get_exchange_dir() / tid / "chunks").exists()


@pytest.mark.asyncio
async def test_chunk_upload_rejects_invalid_index(client, authed):
    resp = await client.post("/transfer/chunk?index=abc", content=b"x")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_chunk_upload_rejects_missing_index(client, authed):
    resp = await client.post("/transfer/chunk", content=b"x")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_chunk_upload_rejects_invalid_transfer_id(client, authed):
    resp = await client.post("/transfer/chunk?transfer_id=not-a-uuid&index=0", content=b"x")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_merge_rejects_invalid_json(client, authed):
    resp = await client.post("/transfer/merge", content=b"not-json")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_merge_rejects_missing_total_size(client, authed):
    tid = transfer.new_transfer_id()
    resp = await client.post("/transfer/merge", json={"transfer_id": tid, "filename": "x.bin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_merge_over_500mb_rejected(client, authed):
    tid = transfer.new_transfer_id()
    resp = await client.post(
        "/transfer/merge",
        json={"transfer_id": tid, "filename": "x.bin", "total_size": 500 * 1024 * 1024 + 1},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_download_range_partial_returns_206(client, authed):
    resp = await client.post("/transfer/upload?filename=r.bin", content=b"0123456789")
    tid = resp.json()["transfer_id"]
    r2 = await client.get(
        f"/transfer/download/{tid}/r.bin", headers={"Range": "bytes=4-"}
    )
    assert r2.status_code == 206
    assert r2.content == b"456789"
    assert r2.headers["content-range"] == "bytes 4-9/10"
    assert r2.headers["accept-ranges"] == "bytes"


@pytest.mark.asyncio
async def test_download_range_bounded_returns_206(client, authed):
    resp = await client.post("/transfer/upload?filename=r.bin", content=b"0123456789")
    tid = resp.json()["transfer_id"]
    r2 = await client.get(
        f"/transfer/download/{tid}/r.bin", headers={"Range": "bytes=2-5"}
    )
    assert r2.status_code == 206
    assert r2.content == b"2345"
    assert r2.headers["content-range"] == "bytes 2-5/10"


@pytest.mark.asyncio
async def test_download_range_suffix_returns_206(client, authed):
    resp = await client.post("/transfer/upload?filename=r.bin", content=b"0123456789")
    tid = resp.json()["transfer_id"]
    r2 = await client.get(
        f"/transfer/download/{tid}/r.bin", headers={"Range": "bytes=-3"}
    )
    assert r2.status_code == 206
    assert r2.content == b"789"
    assert r2.headers["content-range"] == "bytes 7-9/10"


@pytest.mark.asyncio
async def test_download_range_out_of_bounds_returns_416(client, authed):
    resp = await client.post("/transfer/upload?filename=r.bin", content=b"0123456789")
    tid = resp.json()["transfer_id"]
    r2 = await client.get(
        f"/transfer/download/{tid}/r.bin", headers={"Range": "bytes=999-"}
    )
    assert r2.status_code == 416


@pytest.mark.asyncio
async def test_download_multipart_range_rejected_416(client, authed):
    resp = await client.post("/transfer/upload?filename=r.bin", content=b"0123456789")
    tid = resp.json()["transfer_id"]
    r2 = await client.get(
        f"/transfer/download/{tid}/r.bin", headers={"Range": "bytes=0-1,3-4"}
    )
    assert r2.status_code == 416


@pytest.mark.asyncio
async def test_download_no_range_returns_full_200(client, authed):
    resp = await client.post("/transfer/upload?filename=r.bin", content=b"0123456789")
    tid = resp.json()["transfer_id"]
    r2 = await client.get(f"/transfer/download/{tid}/r.bin")
    assert r2.status_code == 200
    assert r2.content == b"0123456789"


@pytest.mark.asyncio
async def test_upload_truncated_body_rejected_and_cleaned(client, authed):
    """BUG20260814163941 复核（2026-08-17）大文件截断根因修复：
    客户端中断 → stream 提前结束但 Content-Length 声明更大，必须 400 + 清理，
    不得返回 200 + 部分文件（生产实证 200MB 仅落 ~500KB 仍报成功）。"""
    declared = 1024 * 1024  # 声明 1MB
    resp = await client.post(
        "/transfer/upload?filename=trunc.zip",
        content=b"only-500kb" * 100,  # 实际 ~1KB < 声明
        headers={"content-length": str(declared)},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "上传不完整" in body["error"]
    assert body["declared"] == declared
    # 中转目录不得残留截断文件
    exchange = transfer.get_exchange_dir()
    leftovers = [p for p in exchange.iterdir() if p.is_dir()]
    assert leftovers == []
