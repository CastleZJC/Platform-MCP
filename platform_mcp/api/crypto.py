"""密码加密 API"""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.audit.models import PmcpCryptoOperationLog
from platform_mcp.auth.middleware import require_admin
from platform_mcp.common.database import get_db
from platform_mcp.common.response import PageResult, ResponseBase
from platform_mcp.datasource.manager import _get_crypto_utils

router = APIRouter(prefix="/crypto", tags=["密码加密"])


class EncryptRequest(BaseModel):
    plaintext: str


class VerifyRequest(BaseModel):
    ciphertext: str


@router.post("/encrypt")
async def encrypt(body: EncryptRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)):
    crypto = _get_crypto_utils()
    operator = _admin.get("username", "unknown")
    start = time.monotonic()
    try:
        ciphertext = crypto.encrypt(body.plaintext)
        db.add(PmcpCryptoOperationLog(
            operator=operator, operation_type="encrypt",
            algorithm="AES-256-GCM", result_status="success", inserted_by=operator,
        ))
        await db.commit()
        await write_audit_log(
            operator=operator,
            resource_type="crypto",
            resource_id=None,
            request_summary="密码加密：success",
            result_status="success",
            extra_data={"operation_type": "encrypt", "algorithm": "AES-256-GCM"},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return ResponseBase(data={"ciphertext": ciphertext})
    except Exception as e:
        db.add(PmcpCryptoOperationLog(
            operator=operator, operation_type="encrypt",
            algorithm="AES-256-GCM", result_status="error", error_message=str(e), inserted_by=operator,
        ))
        await db.commit()
        await write_audit_log(
            operator=operator,
            resource_type="crypto",
            resource_id=None,
            request_summary=f"密码加密失败：{e}",
            result_status="error",
            error_code="15001",
            error_message=str(e),
            extra_data={"operation_type": "encrypt", "algorithm": "AES-256-GCM"},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise


@router.post("/verify")
async def verify(body: VerifyRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_admin)):
    crypto = _get_crypto_utils()
    operator = _admin.get("username", "unknown")
    start = time.monotonic()
    try:
        plaintext = crypto.decrypt(body.ciphertext)
        db.add(PmcpCryptoOperationLog(
            operator=operator, operation_type="verify",
            algorithm="AES-256-GCM", result_status="success", inserted_by=operator,
        ))
        await db.commit()
        await write_audit_log(
            operator=operator,
            resource_type="crypto",
            resource_id=None,
            request_summary="密码验证：success",
            result_status="success",
            extra_data={"operation_type": "verify", "algorithm": "AES-256-GCM"},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return ResponseBase(data={"success": True, "length": len(plaintext)})
    except Exception as e:
        db.add(PmcpCryptoOperationLog(
            operator=operator, operation_type="verify",
            algorithm="AES-256-GCM", result_status="error", error_message=str(e), inserted_by=operator,
        ))
        await db.commit()
        await write_audit_log(
            operator=operator,
            resource_type="crypto",
            resource_id=None,
            request_summary=f"密码验证失败：{e}",
            result_status="error",
            error_code="15001",
            error_message=str(e),
            extra_data={"operation_type": "verify", "algorithm": "AES-256-GCM"},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return ResponseBase(data={"success": False, "error": str(e)})


@router.get("/history")
async def get_crypto_history(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    count_query = select(func.count()).select_from(PmcpCryptoOperationLog)
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(PmcpCryptoOperationLog)
        .order_by(PmcpCryptoOperationLog.inserted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = (await db.execute(query)).scalars().all()

    items = [
        {
            "id": log.id,
            "operator": log.operator,
            "operation_type": log.operation_type,
            "datasource_code": log.datasource_code,
            "algorithm": log.algorithm,
            "result_status": log.result_status,
            "error_message": log.error_message,
            "inserted_at": log.inserted_at.astimezone().strftime("%Y-%m-%d %H:%M:%S") if log.inserted_at else None,
        }
        for log in logs
    ]
    return ResponseBase(data=PageResult.create(items, total, page, page_size))
