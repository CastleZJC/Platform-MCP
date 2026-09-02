"""系统配置管理 API — CRUD for pmcp_system_config + 运行时配置注册表（V3.0 M1，架构 §19.5.2）

已知键：类型校验（validate_value，非法 16004）+ 敏感键强制二次确认（confirm_sensitive，缺失 16005）；
写操作后失效运行时配置缓存（30s 快照即时拉新）。
/registry 必须声明在 /{config_id} 之前（int 路径参数会先命中字符串路由返回 422）。
"""

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
from platform_mcp.common.runtime_config import KNOWN_KEYS, runtime_config, validate_value
from platform_mcp.i18n import get_text

router = APIRouter(prefix="/system-config", tags=["系统配置"])

_SENSITIVE_MASK = "******"


class SystemConfigCreateRequest(BaseModel):
    config_key: str
    config_value: str | None = None
    config_type: str = "string"
    description: str | None = None
    confirm_sensitive: bool = False


class SystemConfigUpdateRequest(BaseModel):
    config_value: str | None = None
    config_type: str | None = None
    description: str | None = None
    status: int | None = None
    confirm_sensitive: bool = False


def _validate_known_key(key: str, raw: str | None, confirm_sensitive: bool) -> str | None:
    """已知键校验：值类型 + 敏感键二次确认。返回错误 message（None=通过）。"""
    spec = KNOWN_KEYS.get(key)
    if spec is None:
        return None
    if raw is None:
        raw = ""
    try:
        validate_value(key, raw)
    except ValueError as e:
        return str(e)
    if spec.sensitive and not confirm_sensitive:
        return f"键 {key} 为安全敏感配置，需二次确认（confirm_sensitive=true）"
    return None


@router.get("/registry")
async def get_registry(db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)):
    """运行时配置注册表：已知键的元信息 + 当前生效值（敏感键已配置值掩码）+ 数据库行 id（未配置为 None）。"""
    await runtime_config.refresh()
    locale = _admin.get("locale")
    rows = (await db.execute(select(PmcpSystemConfig))).scalars().all()
    key_to_id = {r.config_key: r.id for r in rows}
    items = []
    for key, spec in KNOWN_KEYS.items():
        configured_raw = runtime_config.raw_configured(key)
        configured = configured_raw is not None
        if spec.sensitive and configured:
            current_value: object = _SENSITIVE_MASK
        else:
            current_value = runtime_config.get_sync(key)
        items.append(
            {
                "key": key,
                "id": key_to_id.get(key),
                "value_type": spec.value_type,
                "effect": spec.effect,
                "effect_label": get_text(f"config.effect.{spec.effect}", locale),
                "sensitive": spec.sensitive,
                "description": get_text(spec.desc_key, locale),
                "configured": configured,
                "current_value": current_value,
            }
        )
    return ResponseBase(data=items)


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
    """创建系统配置（已知键类型校验 + 敏感键二次确认）"""
    start = time.monotonic()
    existing = await db.execute(select(PmcpSystemConfig).where(PmcpSystemConfig.config_key == body.config_key))
    if existing.scalar_one_or_none():
        return ResponseBase(code=16001, message="配置键已存在")
    error = _validate_known_key(body.config_key, body.config_value, body.confirm_sensitive)
    if error:
        return ResponseBase(code=16004, message=error)
    config = PmcpSystemConfig(
        **body.model_dump(exclude={"confirm_sensitive"}), inserted_by=_admin["username"]
    )
    db.add(config)
    await db.commit()
    runtime_config.invalidate()
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
    """更新系统配置（已知键类型校验 + 敏感键二次确认）"""
    start = time.monotonic()
    config = await db.get(PmcpSystemConfig, config_id)
    if not config:
        return ResponseBase(code=16002, message="配置不存在")
    new_value = body.config_value if body.config_value is not None else config.config_value
    error = _validate_known_key(config.config_key, new_value, body.confirm_sensitive)
    if error:
        return ResponseBase(code=16004, message=error)
    changes = []
    for k, v in body.model_dump(exclude_unset=True, exclude={"confirm_sensitive"}).items():
        setattr(config, k, v)
        changes.append(f"{k}={v}")
    await db.commit()
    runtime_config.invalidate()
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
    runtime_config.invalidate()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=str(config_id),
        request_summary=f"删除系统配置: {config_key}", result_status="success",
        extra_data={"config_id": config_id, "config_key": config_key}, duration_ms=duration_ms,
    )
    return ResponseBase(message="系统配置删除成功")