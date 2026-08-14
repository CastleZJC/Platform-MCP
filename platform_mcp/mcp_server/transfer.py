"""MCP 服务器文件中转 HTTP 端点 — 打通工作站 ↔ MCP 服务器链路（BUG20260814163941 BUG-1/4）

挂在 streamable-http 模式的 ASGI 应用上（mcp_server/__init__.py main()），
与 /mcp/ 共端口、共 _AuthMiddleware（PLATFORM_MCP_API_KEY Header 认证）。

端点：
  POST   /transfer/upload?filename=<name>          raw body 写入中转目录，返回 transfer_id + staged_path
  GET    /transfer/info                             返回中转目录绝对路径（下载编排前查询）
  GET    /transfer/download/{transfer_id}/{filename} 流式取回中转文件
  DELETE /transfer/{transfer_id}                    显式清理任务目录

读写范围强制限定在 sftp_exchange 中转目录内（skills/server/transfer.py 校验）。
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.skills.server import transfer as _transfer

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 对齐 SFTP 500MB 上限


async def upload(request: Request) -> JSONResponse:
    _transfer.cleanup_expired_transfers()
    filename = request.query_params.get("filename", "")
    if not _transfer.is_safe_filename(filename):
        return JSONResponse({"error": "非法 filename 参数"}, status_code=400)

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            return JSONResponse({"error": "非法 content-length"}, status_code=400)
        if declared > _MAX_UPLOAD_BYTES:
            return JSONResponse({"error": "文件超过 500MB 限制"}, status_code=413)

    transfer_id = _transfer.new_transfer_id()
    try:
        target = _transfer.stage_path(transfer_id, filename)
    except PathSecurityError:
        return JSONResponse({"error": "中转路径校验失败"}, status_code=400)

    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with open(target, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    f.close()
                    _transfer.cleanup_transfer(transfer_id)
                    return JSONResponse({"error": "文件超过 500MB 限制"}, status_code=413)
                f.write(chunk)
    except OSError:
        _transfer.cleanup_transfer(transfer_id)
        return JSONResponse({"error": "中转文件写入失败"}, status_code=500)

    return JSONResponse({
        "transfer_id": transfer_id,
        "filename": filename,
        "staged_path": str(target),
        "size": size,
    })


async def info(request: Request) -> JSONResponse:
    return JSONResponse({"exchange_dir": str(_transfer.get_exchange_dir())})


async def download(request: Request) -> Response:
    _transfer.cleanup_expired_transfers()
    try:
        target = _transfer.stage_path(
            request.path_params["transfer_id"], request.path_params["filename"]
        )
    except PathSecurityError:
        return JSONResponse({"error": "非法中转路径"}, status_code=400)
    if not target.is_file():
        return JSONResponse({"error": "中转文件不存在或已清理"}, status_code=404)
    return FileResponse(target, filename=target.name)


async def delete_transfer(request: Request) -> JSONResponse:
    transfer_id = request.path_params["transfer_id"]
    if not _transfer.is_valid_transfer_id(transfer_id):
        return JSONResponse({"error": "非法 transfer_id"}, status_code=400)
    if not _transfer.cleanup_transfer(transfer_id):
        return JSONResponse({"error": "中转目录不存在或已清理"}, status_code=404)
    return JSONResponse({"transfer_id": transfer_id, "cleaned": True})


def build_transfer_routes() -> list[Route]:
    """供 mcp_server/__init__.py main() 挂载到 streamable-http ASGI 应用。"""
    return [
        Route("/transfer/upload", upload, methods=["POST"]),
        Route("/transfer/info", info, methods=["GET"]),
        Route("/transfer/download/{transfer_id}/{filename}", download, methods=["GET"]),
        Route("/transfer/{transfer_id}", delete_transfer, methods=["DELETE"]),
    ]
