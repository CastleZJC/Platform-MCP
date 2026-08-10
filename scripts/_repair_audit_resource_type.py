"""一次性修复脚本：把历史 SQL 执行类审计从 resource_type='datasource' 改为 'sql'。

原因：旧版 call_log.py 把所有 MCP 调用硬编码为 resource_type='datasource'，
导致 execute_sql_text 等工具的审计被错归类。本次升级后已按 tool_name 区分，
但历史记录需要此脚本回填。

用法：python scripts/_repair_audit_resource_type.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from platform_mcp.common import database as _db

SQL_TOOLS = (
    "('execute_sql_text', 'execute_sql_file', 'validate_sql', 'get_execution_status')"
)


async def main() -> None:
    _db._ensure_engine()
    async with _db.async_session_factory() as s:
        cnt = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM pmcp_audit_log "
                    "WHERE resource_type = 'datasource' AND tool_name IN " + SQL_TOOLS
                )
            )
        ).scalar()
        print(f"[repair] 待修复记录: {cnt} 条")

        if cnt == 0:
            print("[repair] 无需修复，退出")
            return

        result = await s.execute(
            text(
                "UPDATE pmcp_audit_log "
                "SET resource_type = 'sql', updated_at = NOW() "
                "WHERE resource_type = 'datasource' AND tool_name IN " + SQL_TOOLS
            )
        )
        await s.commit()
        print(f"[repair] 实际更新: {result.rowcount} 条")

        remain = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM pmcp_audit_log "
                    "WHERE resource_type = 'datasource' AND tool_name IN " + SQL_TOOLS
                )
            )
        ).scalar()
        print(f"[repair] 修复后剩余错归类: {remain} 条（应为 0）")


if __name__ == "__main__":
    asyncio.run(main())
