"""系统配置管理 API — CRUD for pmcp_system_config"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.models import PmcpSystemConfig
from platform_mcp.common.response import PageResult, ResponseBase

router = APIRouter(prefix="/system-config", tags=["系统配置"])


class SystemConfigCreateRequest(BaseModel):
    config_key: str
    config_value: str | None = None
    config_type: str = "string"
    description: str | None = None


class SystemConfigUpdateRequest(BaseModel):
    config_value: str | None = None
    config_type: str | None = None
    description: str | None = None
    status: int | None = None


@router.get("")
async def list_system_configs(
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """列出系统配置（admin only）"""
    query = select(PmcpSystemConfig)
    count_query = select(func.count()).select_from(PmcpSystemConfig)
    if search:
        clause = PmcpSystemConfig.config_key.ilike(f"%{search}%")
        query, count_query = query.where(clause), count_query.where(clause)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpSystemConfig.id)
    configs = (await db.execute(query)).scalars().all()
    items = [
        {
            "id": c.id,
            "config_key": c.config_key,
            "config_value": c.config_value,
            "config_type": c.config_type,
            "description": c.description,
            "status": c.status,
            "created_at": c.inserted_at.isoformat() if c.inserted_at else None,
        }
        for c in configs
    ]
    return ResponseBase(data=PageResult.create(items=items, total=total, page=page, page_size=page_size))


@router.post("")
async def create_system_config(
    body: SystemConfigCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """创建系统配置"""
    start = time.monotonic()
    existing = await db.execute(select(PmcpSystemConfig).where(PmcpSystemConfig.config_key == body.config_key))
    if existing.scalar_one_or_none():
        return ResponseBase(code=16001, message="配置键已存在")
    config = PmcpSystemConfig(**body.model_dump(), inserted_by=_admin["username"])
    db.add(config)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(config.id),
        request_summary=f"创建系统配置: {config.config_key}", result_status="success",
        extra_data={"config_key": config.config_key, "config_type": config.config_type}, duration_ms=duration_ms,
    )
    return ResponseBase(data={"id": config.id, "config_key": config.config_key}, message="系统配置创建成功")


@router.get("/{config_id}")
async def get_system_config(
    config_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """获取单个系统配置"""
    config = await db.get(PmcpSystemConfig, config_id)
    if not config:
        return ResponseBase(code=16002, message="配置不存在")
    return ResponseBase(data={
        "id": config.id, "config_key": config.config_key, "config_value": config.config_value,
        "config_type": config.config_type, "description": config.description, "status": config.status,
    })


@router.put("/{config_id}")
async def update_system_config(
    config_id: int, body: SystemConfigUpdateRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """更新系统配置"""
    start = time.monotonic()
    config = await db.get(PmcpSystemConfig, config_id)
    if not config:
        return ResponseBase(code=16002, message="配置不存在")
    changes = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(config, k, v)
        changes.append(f"{k}={v}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(config_id),
        request_summary=f"更新系统配置: {config.config_key}, 变更: {', '.join(changes)}",
        result_status="success", extra_data={"config_id": config_id, "changes": changes}, duration_ms=duration_ms,
    )
    return ResponseBase(message="系统配置更新成功")


@router.delete("/{config_id}")
async def delete_system_config(
    config_id: int, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """删除系统配置"""
    start = time.monotonic()
    config = await db.get(PmcpSystemConfig, config_id)
    if not config:
        return ResponseBase(code=16002, message="配置不存在")
    config_key = config.config_key
    await db.delete(config)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(config_id),
        request_summary=f"删除系统配置: {config_key}", result_status="success",
        extra_data={"config_id": config_id, "config_key": config_key}, duration_ms=duration_ms,
    )
    return ResponseBase(message="系统配置删除成功")