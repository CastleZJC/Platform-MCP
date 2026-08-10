"""Seed database + server skills + skill-web mapping"""
import asyncio
from platform_mcp.common import database as _db


async def _ensure_skill(s, skill_code: str, skill_name: str, description: str, tool_count: int):
    """幂等插入：若已存在则跳过。"""
    from sqlalchemy import text

    r = await s.execute(text("SELECT id FROM pmcp_skill WHERE skill_code = :c"), {"c": skill_code})
    if r.scalar_one_or_none() is None:
        await s.execute(text("""
            INSERT INTO pmcp_skill (skill_code, skill_name, description, status, register_method, tool_count, inserted_by)
            VALUES (:code, :name, :desc, 1, 'decorator', :tc, 'system')
        """), {"code": skill_code, "name": skill_name, "desc": description, "tc": tool_count})
        await s.commit()
        print(f"OK: {skill_code} skill seeded ({tool_count} tools)")
    else:
        print(f"SKIP: {skill_code} already exists")


async def seed():
    _db._ensure_engine()
    async with _db.async_session_factory() as s:
        await _ensure_skill(
            s,
            "database",
            "Database Skill",
            "SQL 执行能力：SQL 文本/文件执行、风险校验、数据源列举、异步状态查询",
            5,
        )
        await _ensure_skill(
            s,
            "server",
            "Server Skill",
            "Linux SSH/SFTP 能力：shell 命令执行、文件上传下载、命令风控、服务器列举、异步状态",
            6,
        )


asyncio.run(seed())

