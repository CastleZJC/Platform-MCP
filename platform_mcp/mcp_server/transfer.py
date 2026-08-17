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

from pathlib import Path
from typing import Iterator

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.skills.server import transfer as _transfer

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 对齐 SFTP 500MB 上限


async def upload(request: Request) -> JSONResponse:
    _transfer.cleanup_expired_transfers()
    filename = request.query_params.get("filename", "")
    if not _transfer.is_safe_filename(filename):
        return JSONResponse({"error": "非法 filename 参数"}, status_code=400)

    declared: int | None = None
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

    # BUG20260814163941 复核（2026-08-17）大文件截断根因：客户端中断时 ASGI stream
    # 正常结束（不抛异常），此前返回 200 + 部分文件 → SFTP 推给目标服务器的是截断文件。
    # 生产实证：200MB 中转落盘仅 ~500KB 且整链路"成功"。必须校验收到的字节数与
    # Content-Length 一致，不一致按失败处理并清理，杜绝截断文件被当作成功中转。
    if declared is not None and size != declared:
        _transfer.cleanup_transfer(transfer_id)
        return JSONResponse(
            {
                "error": (
                    f"上传不完整：收到 {size} 字节，Content-Length 声明 {declared} 字节"
                    "（传输中断），请重试"
                ),
                "received": size,
                "declared": declared,
            },
            status_code=400,
        )

    return JSONResponse({
        "transfer_id": transfer_id,
        "filename": filename,
        "staged_path": str(target),
        "size": size,
    })


async def info(request: Request) -> JSONResponse:
    return JSONResponse({"exchange_dir": str(_transfer.get_exchange_dir())})


def _parse_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """解析单段 Range 头（bytes=start-end / bytes=start- / bytes=-suffix），返回 (start, end) 闭区间。

    断点续传下载（BUG20260814163941 HTTP 下载腿）：客户端持 partial 后重试时
    发 `Range: bytes=<已收字节数>-`，服务端只回传剩余部分，避免整文件重传。
    多段范围（逗号分隔）不支持，返回 None。
    """
    if not range_header.startswith("bytes=") or "," in range_header:
        return None
    spec = range_header[len("bytes="):].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            n = int(end_s)
            if n <= 0:
                return None
            start = max(0, file_size - n)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s != "" else file_size - 1
    except ValueError:
        return None
    if start < 0 or start >= file_size or end < start:
        return None
    return start, min(end, file_size - 1)


def _iter_file_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    """从 start 偏移流式读取恰好 length 字节，1MB 块，避免整文件载入内存。"""
    block = 1024 * 1024
    remaining = length
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(block, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)


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

    file_size = target.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        parsed = _parse_range(range_header, file_size)
        if parsed is None:
            return JSONResponse(
                {"error": "非法 Range 头，仅支持单段 bytes=start-end"},
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start, end = parsed
        length = end - start + 1
        return StreamingResponse(
            _iter_file_range(target, start, length),
            status_code=206,
            media_type="application/octet-stream",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )

    return FileResponse(target, filename=target.name)


async def upload_chunk(request: Request) -> JSONResponse:
    """分片上传端点：POST /transfer/chunk?transfer_id=&index=

    大文件断点续传（工作站↔MCP 链路网络不稳）：客户端将大文件切成多片，
    逐片上传（片级失败仅重传该片），全部传完后调用 /transfer/merge 合并。
    首次上传不带 transfer_id，服务端生成并返回；后续片带同一 transfer_id。
    """
    _transfer.cleanup_expired_transfers()
    transfer_id = request.query_params.get("transfer_id", "")
    if transfer_id:
        if not _transfer.is_valid_transfer_id(transfer_id):
            return JSONResponse({"error": "非法 transfer_id"}, status_code=400)
    else:
        transfer_id = _transfer.new_transfer_id()

    index_raw = request.query_params.get("index")
    if index_raw is None:
        return JSONResponse({"error": "缺少 index 参数"}, status_code=400)
    try:
        index = int(index_raw)
    except ValueError:
        return JSONResponse({"error": "非法 index 参数"}, status_code=400)

    try:
        target = _transfer.chunk_path(transfer_id, index)
    except PathSecurityError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with open(target, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    f.close()
                    return JSONResponse({"error": "分片超过 500MB 限制"}, status_code=413)
                f.write(chunk)
    except OSError:
        return JSONResponse({"error": "分片写入失败"}, status_code=500)

    return JSONResponse({
        "transfer_id": transfer_id,
        "index": index,
        "received": size,
    })


async def merge(request: Request) -> JSONResponse:
    """合并端点：POST /transfer/merge，body {transfer_id, filename, total_size}

    按 index 升序拼接分片成最终中转文件，校验总大小与 total_size 一致；
    合并失败保留分片目录，客户端可补传缺失片后重试 merge。
    """
    _transfer.cleanup_expired_transfers()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "非法 JSON body"}, status_code=400)

    transfer_id = body.get("transfer_id", "")
    filename = body.get("filename", "")
    total_size = body.get("total_size")
    if not isinstance(total_size, int) or total_size < 0:
        return JSONResponse({"error": "非法 total_size"}, status_code=400)
    if total_size > _MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "文件超过 500MB 限制"}, status_code=413)

    try:
        target = _transfer.merge_chunks(transfer_id, filename, total_size)
    except PathSecurityError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return JSONResponse({
        "transfer_id": transfer_id,
        "filename": filename,
        "staged_path": str(target),
        "size": total_size,
    })


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
        Route("/transfer/chunk", upload_chunk, methods=["POST"]),
        Route("/transfer/merge", merge, methods=["POST"]),
        Route("/transfer/info", info, methods=["GET"]),
        Route("/transfer/download/{transfer_id}/{filename}", download, methods=["GET"]),
        Route("/transfer/{transfer_id}", delete_transfer, methods=["DELETE"]),
    ]
