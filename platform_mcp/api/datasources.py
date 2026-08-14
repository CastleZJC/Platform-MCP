"""数据源管理 API"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.middleware import get_current_user, require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.datasource.manager import datasource_manager
from platform_mcp.datasource.models import PmcpDatasource
from platform_mcp.group.models import PmcpDatasourceGroupMember, PmcpUserGroup

router = APIRouter(prefix="/datasources", tags=["数据源管理"])


class DatasourceCreateRequest(BaseModel):
    datasource_code: str = Field(min_length=1)
    datasource_name: str = Field(min_length=1)
    db_type: str = Field(min_length=1)
    env_code: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int
    instance_name: str | None = None
    service_name: str | None = None
    database: str | None = None
    username: str
    encrypted_password: str | None = None
    max_concurrent: int = 5
    query_timeout: int = 300
    remark: str | None = None

    @field_validator("datasource_code", "datasource_name", "db_type", "env_code", "host", "username")
    @classmethod
    def _reject_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("必填字段不能为空白字符")
        return v


class DatasourceUpdateRequest(BaseModel):
    datasource_name: str | None = None
    host: str | None = None
    port: int | None = None
    instance_name: str | None = None
    service_name: str | None = None
    database: str | None = None
    username: str | None = None
    encrypted_password: str | None = None
    max_concurrent: int | None = None
    query_timeout: int | None = None
    remark: str | None = None


class StatusUpdateRequest(BaseModel):
    status: int


def _ds_to_dict(ds: PmcpDatasource) -> dict:
    return {
        "id": ds.id,
        "datasource_code": ds.datasource_code,
        "datasource_name": ds.datasource_name,
        "db_type": ds.db_type,
        "env_code": ds.env_code,
        "host": ds.host,
        "port": ds.port,
        "instance_name": ds.instance_name,
        "service_name": ds.service_name,
        "database": ds.database,
        "username": ds.username,
        "status": ds.status,
        "max_concurrent": ds.max_concurrent,
        "query_timeout": ds.query_timeout,
        "remark": ds.remark,
        "created_at": ds.inserted_at.isoformat() if ds.inserted_at else None,
    }


@router.get("")
async def list_datasources(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    db_type: str | None = None,
    env_code: str | None = None,
    status: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    query = select(PmcpDatasource)
    count_query = select(func.count()).select_from(PmcpDatasource)
    if search:
        clause = PmcpDatasource.datasource_code.ilike(f"%{search}%") | PmcpDatasource.datasource_name.ilike(
            f"%{search}%"
        )
        query, count_query = query.where(clause), count_query.where(clause)
    if db_type:
        query, count_query = query.where(PmcpDatasource.db_type == db_type), count_query.where(
            PmcpDatasource.db_type == db_type
        )
    if env_code:
        query, count_query = query.where(PmcpDatasource.env_code == env_code), count_query.where(
            PmcpDatasource.env_code == env_code
        )
    if status is not None:
        query, count_query = query.where(PmcpDatasource.status == status), count_query.where(
            PmcpDatasource.status == status
        )
    # developer 角色通过组过滤可见数据源
    if _user["role_code"] == "developer":
        group_ids: list[int] = list((await db.execute(
                select(PmcpUserGroup.group_id).where(
                    (PmcpUserGroup.user_id == _user["id"]) & (PmcpUserGroup.group_type == "datasource")
                )
            )).scalars().all())
        if group_ids:
            ds_ids: list[int] = list((await db.execute(
                    select(PmcpDatasourceGroupMember.datasource_id).where(
                        PmcpDatasourceGroupMember.group_id.in_(group_ids)
                    )
                )).scalars().all())
            query, count_query = query.where(PmcpDatasource.id.in_(ds_ids)), count_query.where(PmcpDatasource.id.in_(ds_ids))
        else:
            # 未分配任何组 → 不可见任何数据源
            query, count_query = query.where(PmcpDatasource.id < 0), count_query.where(PmcpDatasource.id < 0)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(PmcpDatasource.id)
    items = [_ds_to_dict(ds) for ds in (await db.execute(query)).scalars().all()]
    return ResponseBase(
        data=PageResult(
            items=items, total=total, page=page, page_size=page_size, total_pages=(total + page_size - 1) // page_size
        )
    )


@router.post("")
async def create_datasource(
    body: DatasourceCreateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    existing = await db.execute(select(PmcpDatasource).where(PmcpDatasource.datasource_code == body.datasource_code))
    if existing.scalar_one_or_none():
        return ResponseBase(code=12001, message="数据源编码已存在")
    ds = PmcpDatasource(**body.model_dump())
    db.add(ds)
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="datasource",
        resource_id=str(ds.id),
        request_summary=f"创建数据源: {ds.datasource_code}",
        result_status="success",
        extra_data={"datasource_code": ds.datasource_code, "db_type": ds.db_type, "env_code": ds.env_code},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="数据源创建成功")


@router.put("/{ds_id}")
async def update_datasource(
    ds_id: int, body: DatasourceUpdateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    ds = await db.get(PmcpDatasource, ds_id)
    if not ds:
        return ResponseBase(code=12002, message="数据源不存在")
    changes = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ds, k, v)
        changes.append(f"{k}={v}")
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="datasource",
        resource_id=str(ds_id),
        request_summary=f"更新数据源: {ds.datasource_code}, 变更: {', '.join(changes) if changes else '无'}",
        result_status="success",
        extra_data={"datasource_code": ds.datasource_code, "changes": changes},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="数据源更新成功")


@router.put("/{ds_id}/status")
async def update_ds_status(
    ds_id: int, body: StatusUpdateRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)
):
    import time
    start = time.monotonic()
    ds = await db.get(PmcpDatasource, ds_id)
    if not ds:
        return ResponseBase(code=12002, message="数据源不存在")
    old_status = ds.status
    ds.status = body.status
    await db.commit()
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_admin["username"],
        resource_type="datasource",
        resource_id=str(ds_id),
        request_summary=f"修改数据源状态: {ds.datasource_code}, {old_status} -> {body.status}",
        result_status="success",
        extra_data={"datasource_code": ds.datasource_code, "old_status": old_status, "new_status": body.status},
        duration_ms=duration_ms,
    )
    return ResponseBase(message="状态更新成功")


@router.post("/{ds_id}/test")
async def test_connection(ds_id: int, db: AsyncSession = Depends(get_db), _user: dict = Depends(get_current_user)):
    import time
    start = time.monotonic()
    ds = await db.get(PmcpDatasource, ds_id)
    if not ds:
        return ResponseBase(code=12002, message="数据源不存在")
    result = await datasource_manager.test_connection(ds.datasource_code)
    duration_ms = int((time.monotonic() - start) * 1000)
    await write_audit_log(
        operator=_user["username"],
        resource_type="datasource",
        resource_id=str(ds_id),
        request_summary=f"测试数据源连接: {ds.datasource_code}",
        result_status="success" if result.get("success") else "error",
        extra_data={"datasource_code": ds.datasource_code, "test_result": result.get("success")},
        duration_ms=duration_ms,
    )
    return ResponseBase(data=result)
