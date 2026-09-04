"""系统配置管理 API — CRUD for pmcp_system_config + 运行时配置注册表（V3.0 M1，架构 §19.5.2）

已知键：类型校验（validate_value，非法 16004）+ 敏感键强制二次确认（confirm_sensitive，缺失 16005）；
写操作后失效运行时配置缓存（30s 快照即时拉新）。
按配置键（注册表自然键）读写：PUT /{config_key} 为 upsert（已有行更新 / 未落库键创建行），
DELETE /{config_key} 重置回注册表默认值；无独立创建端点（配置值永有当前生效值，不存在“首次落库”前置）。
/registry 必须声明在 /{config_key} 之前（避免被键路由先匹配）。
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


class SystemConfigUpdateRequest(BaseModel):
    """按键设置值：敏感键留空（null）= 保留原值；键元数据随注册表发布不可改。"""

    config_value: str | None = None
    confirm_sensitive: bool = False


def _validate_known_key(key: str, raw: str | None, confirm_sensitive: bool) -> str | None:
    """已知键校验：值类型 + 敏感键二次确认；注册表外未知键拒绝。返回错误 message（None=通过）。"""
    spec = KNOWN_KEYS.get(key)
    if spec is None:
        return f"未知配置键 {key}：注册表键随版本发布，Web 端仅支持设置已知键"
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
    """运行时配置注册表：已知键元信息 + 当前生效值（敏感键已配置值掩码）。以 config_key 为自然键，无行 id。"""
    await runtime_config.refresh()
    locale = _admin.get("locale")
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
                "label": get_text(spec.label_key, locale) if spec.label_key else key,
                "hint": get_text(spec.hint_key, locale) if spec.hint_key else None,
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


@router.put("/{config_key}")
async def upsert_system_config(
    config_key: str, body: SystemConfigUpdateRequest,
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """按配置键设置值（upsert）：已有行更新 / 未落库键创建行。

    键元数据（类型/描述/生效语义）随注册表发布，Web 端不可改；
    敏感键留空（config_value=null）= 保留原值（仅已有行时有效）。
    """
    start = time.monotonic()
    error = _validate_known_key(config_key, body.config_value, body.confirm_sensitive)
    if error:
        return ResponseBase(code=16004, message=error)
    spec = KNOWN_KEYS[config_key]
    existing = (await db.execute(
        select(PmcpSystemConfig).where(PmcpSystemConfig.config_key == config_key)
    )).scalar_one_or_none()
    if existing is not None:
        action = "更新"
        if body.config_value is not None:
            existing.config_value = body.config_value
    else:
        action = "落库"
        existing = PmcpSystemConfig(
            config_key=config_key,
            config_value=body.config_value or "",
            config_type=spec.value_type,
            description=get_text(spec.desc_key, _admin.get("locale")),
            inserted_by=_admin["username"],
        )
        db.add(existing)
    await db.commit()
    runtime_config.invalidate()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=config_key,
        request_summary=f"{action}系统配置: {config_key}",
        result_status="success",
        extra_data={"config_key": config_key,
                    "config_value": "***" if spec.sensitive else body.config_value},
        duration_ms=duration_ms,
    )
    return ResponseBase(message=f"系统配置{action}成功")


@router.delete("/{config_key}")
async def delete_system_config(
    config_key: str, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin),
):
    """按配置键删除配置行（重置回注册表默认值）；历史未知键行亦可清理。"""
    start = time.monotonic()
    config = (await db.execute(
        select(PmcpSystemConfig).where(PmcpSystemConfig.config_key == config_key)
    )).scalar_one_or_none()
    if not config:
        return ResponseBase(code=16002, message="配置不存在")
    await db.delete(config)
    await db.commit()
    runtime_config.invalidate()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"], resource_type="config", resource_id=config_key,
        request_summary=f"重置系统配置: {config_key}", result_status="success",
        extra_data={"config_key": config_key}, duration_ms=duration_ms,
    )
    return ResponseBase(message="系统配置已重置为默认值")