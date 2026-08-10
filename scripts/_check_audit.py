"""临时脚本：检查最新审计日志"""
import asyncio
from sqlalchemy import select
from platform_mcp.common.database import BaseModel

async def main():
    from platform_mcp.common.database import async_engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from platform_mcp.audit.models import PmcpAuditLog

    async with AsyncSession(async_engine) as session:
        result = await session.execute(select(PmcpAuditLog).order_by(PmcpAuditLog.id.desc()).limit(2))
        for log in result.scalars():
            print(f'ID={log.id}, operator={log.operator}, type={log.resource_type}, summary={log.request_summary}, status={log.result_status}')

asyncio.run(main())
