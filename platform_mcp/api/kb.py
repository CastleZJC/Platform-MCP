"""知识库 API 占位（V3.0 M6 骨架，架构 §19.6 / 计划 6.2；F-41）

三期功能，V3.0 仅交付骨架：全部端点返回 HTTP 501（沿用二期前占位惯例），
统一响应体（5 字段 code/message/data/trace_id/timestamp）+ code=15002（系统
错误段，「未实现」状态）。
三期实现时替换为真实业务（RAG 检索 / GRAPH 查询 / 文档导入 / 分享送审——
审核流挂接 platform_mcp/review/）。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from platform_mcp.common.response import ResponseBase

router = APIRouter(prefix="/kb", tags=["知识库"])

_KB_NOT_IMPLEMENTED_MESSAGE = "知识库为三期规划，V3.0 仅交付骨架（五表 ORM + RAG/GRAPH 抽象 + 7 切片枚举），本端点未实现"


def _not_implemented(action: str) -> JSONResponse:
    """501 占位统一出口：HTTP 501 + 统一 5 字段响应体（code=15002，系统错误段未实现状态）。"""
    body = ResponseBase[None](code=15002, message=f"{_KB_NOT_IMPLEMENTED_MESSAGE}：{action}")
    return JSONResponse(status_code=501, content=body.model_dump())


@router.get("")
async def list_kbs() -> JSONResponse:
    """知识库列表（三期实现：personal/shared 过滤 + 分页）。"""
    return _not_implemented("列表")


@router.post("")
async def create_kb() -> JSONResponse:
    """创建知识库（三期实现：personal/shared + owner 归属）。"""
    return _not_implemented("创建")


@router.get("/{kb_id}")
async def get_kb(kb_id: int) -> JSONResponse:
    """知识库详情（三期实现：元数据 + 状态 + 文档统计）。"""
    return _not_implemented("详情")


@router.post("/{kb_id}/docs")
async def upload_doc(kb_id: int) -> JSONResponse:
    """导入文档（三期实现：切片入库 Indexer + GRAPH 抽取）。"""
    return _not_implemented("文档导入")


@router.get("/{kb_id}/search")
async def search_kb(kb_id: int) -> JSONResponse:
    """RAG 语义检索（三期实现：Retriever topK 切片 + 可选图扩展）。"""
    return _not_implemented("语义检索")


@router.get("/{kb_id}/graph")
async def kb_graph(kb_id: int) -> JSONResponse:
    """GRAPH 邻接查询（三期实现：GraphStore.neighbors 子图）。"""
    return _not_implemented("图谱查询")


@router.post("/{kb_id}/share")
async def share_kb(kb_id: int) -> JSONResponse:
    """分享送审（三期实现：挂接 platform_mcp/review/ 审核流）。"""
    return _not_implemented("分享送审")
