"""SQL 执行器 — 执行查询、格式化结果、路径安全校验"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import re

import sqlparse
from loguru import logger

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.datasource.manager import ConnectionParams
from platform_mcp.skills.database.connection import get_connection
from platform_mcp.mcp_server.skill.concurrency import ConcurrencyLimiter

_MAX_RESULT_ROWS = 1000
_MAX_SQL_TEXT_LENGTH = 1024 * 1024  # 1MB

_concurrency_limiter = ConcurrencyLimiter()


_SLASH_TERMINATOR_RE = re.compile(r"(?m)^[ \t]*/[ \t\r]*$")
_PLACEHOLDER = "\x00"
_BLOCK_UNIT_START_RE = re.compile(
    r"\s*(declare|begin|create\s+(?:or\s+replace\s+)?(?:procedure|function|trigger|package))\b",
    re.IGNORECASE,
)
_BEGIN_KW_RE = re.compile(r"[Bb][Ee][Gg][Ii][Nn](?![A-Za-z0-9_])")
_END_KW_RE = re.compile(r"[Ee][Nn][Dd](?![A-Za-z0-9_])")
_END_NON_BLOCK_RE = re.compile(r"\s+(?:if|loop|case)\b", re.IGNORECASE)


def _shield_block_semicolons(content: str) -> str:
    """PL/SQL 块内部分号替换为占位符（sqlparse 分句后还原），避免匿名/命名块被内部分号拆碎。

    块单位 = 以 BEGIN/DECLARE 或 CREATE PROCEDURE/FUNCTION/TRIGGER/TYPE/PACKAGE 开头的语句；
    BEGIN 层级 +1，END（非 END IF/LOOP/CASE）层级 -1，层级 > 0 期间的 ';' 被屏蔽。
    注释、'...' 字符串（含 '' 转义）、"..." 引号标识符直通，避免误判。
    """
    out: list[str] = []
    i, n = 0, len(content)
    depth = 0
    head_active = False  # declare/create 过程类头部贡献的隐式层级
    at_unit_start = True
    while i < n:
        ch = content[i]
        if content[i : i + 2] == "--":
            j = content.find("\n", i)
            j = n if j == -1 else j + 1
            out.append(content[i:j]); i = j; continue
        if content[i : i + 2] == "/*":
            j = content.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(content[i:j]); i = j; continue
        if ch == "'":
            j = i + 1
            while j < n:
                if content[j] == "'":
                    if j + 1 < n and content[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(content[i : j + 1]); i = j + 1; continue
        if ch == '"':
            k = content.find('"', i + 1)
            j = n if k == -1 else k + 1
            out.append(content[i:j]); i = j; continue
        if at_unit_start and not ch.isspace():
            m = _BLOCK_UNIT_START_RE.match(content, i)
            if m:
                head = m.group(1).lower()
                # begin 开头由后续关键词扫描自 +1；declare / create 过程类声明段即块内（隐式 +1）
                if head == "begin":
                    depth, head_active = 0, False
                else:
                    depth, head_active = 1, True
            at_unit_start = False
        if ch in ("B", "b", "E", "e") and not (i and (content[i - 1].isalnum() or content[i - 1] == "_")):
            if _BEGIN_KW_RE.match(content, i) is not None:
                depth += 1
                out.append(content[i : i + 5]); i += 5; continue
            if depth > 0 and _END_KW_RE.match(content, i) is not None:
                if _END_NON_BLOCK_RE.match(content, i + 3) is None:
                    depth -= 1
                    # 头部隐式层级的单元：顶层 END（深度回到 1）即单元闭合
                    if head_active and depth == 1:
                        depth, head_active = 0, False
                out.append(content[i : i + 3]); i += 3; continue
        if ch == ";":
            if depth > 0:
                out.append(_PLACEHOLDER)
            else:
                out.append(";")
                at_unit_start = True
            i += 1; continue
        out.append(ch); i += 1
    return "".join(out)


def split_statements(content: str) -> list[str]:
    """sqlparse 分句 + SQL*Plus `/` 终结符 + PL/SQL 块保护（BUG20260817 BUG-1/3 延伸）。

    顺序：行首独立 `/` 归一为 `;`（无尾分号 DDL / PLSQL 块的终结符）→ 块内分号
    屏蔽为占位符（匿名/命名块不被内部分号拆碎）→ sqlparse 分句 → 还原占位符、
    剥离尾部分号（oracledb 对 "\n;" 结尾报 ORA-00911）→ 过滤空碎片。
    """
    normalized = _SLASH_TERMINATOR_RE.sub(";", content)
    shielded = _shield_block_semicolons(normalized)
    stmts = [s.value.strip() for s in sqlparse.parse(shielded) if s.value.strip()]
    restored = [s.replace(_PLACEHOLDER, ";") for s in stmts]
    # 块语句保留 END; 分号（块语法一部分，缺失则 PLS-00103）；普通语句剥离尾分号（ORA-00911）
    cleaned = [r if _BLOCK_UNIT_START_RE.match(r) else r.rstrip(";").strip() for r in restored]
    return [s for s in cleaned if not set(s) <= set("/; \t\r\n")]


@dataclass
class ExecutionResult:
    success: bool
    affected_rows: int = 0
    columns: list[str] | None = None
    rows: list[list[str | None]] | None = None
    row_count: int = 0
    error_message: str | None = None
    duration_ms: int = 0
    risk_level: str = "LOW"
    truncated: bool = False
    source_session: dict | None = None


class SQLExecutor:

    async def execute_query(
        self,
        params: ConnectionParams,
        sql: str,
        timeout: int | None = None,
    ) -> ExecutionResult:
        if len(sql) > _MAX_SQL_TEXT_LENGTH:
            return ExecutionResult(
                success=False, error_message=f"SQL 文本超过 {_MAX_SQL_TEXT_LENGTH // 1024 // 1024}MB 限制"
            )
        timeout = timeout or params.query_timeout
        start = time.monotonic()
        try:
            async with _concurrency_limiter.acquire(params.datasource_code, params.max_concurrent):
                result = await asyncio.wait_for(self._do_execute(params, sql), timeout=timeout)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            return result
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error_message=f"SQL 执行超时 ({timeout}s)",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

    async def execute_statements(
        self,
        statements: list[str],
        params: ConnectionParams,
        timeout: int | None = None,
    ) -> list[ExecutionResult]:
        """逐条执行已分句的 SQL，失败即停（对齐 execute_file 行为）。"""
        results: list[ExecutionResult] = []
        for sql in statements:
            r = await self.execute_query(params, sql, timeout)
            results.append(r)
            if not r.success:
                break
        return results

    async def execute_file(
        self,
        file_path: str,
        params: ConnectionParams,
        timeout: int | None = None,
    ) -> list[ExecutionResult]:
        path = self._validate_file_path(file_path, env_code=params.env_code)
        content = path.read_text(encoding="utf-8")
        statements = split_statements(content)
        if not statements:
            return [ExecutionResult(success=False, error_message="SQL 文件为空")]

        return await self.execute_statements(statements, params, timeout)

    def _validate_file_path(self, file_path: str, env_code: str = "DEV") -> Path:
        from platform_mcp.config import get_settings

        settings = get_settings()
        allowed = settings.datasource.allowed_sql_dirs
        max_size = settings.datasource.max_file_size_mb * 1024 * 1024

        path = Path(file_path).resolve()
        if not path.exists():
            raise PathSecurityError(f"文件不存在: {file_path}")
        if path.suffix.lower() != ".sql":
            raise PathSecurityError(f"仅允许 .sql 文件: {file_path}")
        if path.is_symlink():
            raise PathSecurityError(f"禁止符号链接: {file_path}")
        if path.stat().st_size > max_size:
            raise PathSecurityError(f"文件超过 {settings.datasource.max_file_size_mb}MB: {file_path}")
        if not allowed:
            # P1-6 修复：白名单空配置时按环境拦截
            # BUG20260814163941 BUG-2：拦截语义 = 目标资源环境（pmcp_datasource.env_code），
            # 而非 MCP 部署环境（settings.env）——PROD 部署操作 DEV 数据源不应被误伤
            if env_code == "PROD":
                raise PathSecurityError(
                    "目标数据源属 PROD 环境，必须配置 allowed_sql_dirs，禁止任意路径执行 SQL 文件"
                )
            logger.warning(
                "allowed_sql_dirs 未配置，目标环境={} 允许任意路径执行 SQL 文件（PROD 目标强制要求配置）",
                env_code,
            )
        else:
            allowed_resolved = [str(Path(d).resolve()) for d in allowed]
            if not any(str(path).startswith(d) for d in allowed_resolved):
                raise PathSecurityError(f"文件不在白名单目录内: {file_path}")
        return path

    async def _do_execute(self, params: ConnectionParams, sql: str) -> ExecutionResult:
        async with get_connection(params) as conn:
            if params.db_type == "oracle":
                return await self._execute_oracle(conn, sql)
            else:
                return await self._execute_mysql(conn, sql)

    async def _execute_oracle(self, conn: Any, sql: str) -> ExecutionResult:
        loop = asyncio.get_running_loop()

        def _run():
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                sid = getattr(conn, "session_id", None)
                serial = getattr(conn, "serial_num", None)
                source_session = (
                    {"type": "oracle", "sid": sid, "serial": serial}
                    if sid is not None
                    else None
                )
                if cursor.description:
                    columns = [d[0] for d in cursor.description]
                    rows_raw = cursor.fetchmany(_MAX_RESULT_ROWS + 1)
                    truncated = len(rows_raw) > _MAX_RESULT_ROWS
                    rows = [_format_row(r) for r in rows_raw[:_MAX_RESULT_ROWS]]
                    return ExecutionResult(
                        success=True,
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        affected_rows=cursor.rowcount,
                        truncated=truncated,
                        source_session=source_session,
                    )
                conn.commit()
                return ExecutionResult(
                    success=True, affected_rows=cursor.rowcount, source_session=source_session
                )
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                cursor.close()

        return await loop.run_in_executor(None, _run)

    async def _execute_mysql(self, conn: Any, sql: str) -> ExecutionResult:
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT CONNECTION_ID()")
                row = await cur.fetchone()
                conn_id = row[0] if row else None
                source_session = (
                    {"type": "mysql", "conn_id": conn_id} if conn_id is not None else None
                )
            except Exception:
                source_session = None
            await cur.execute(sql)
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows_raw = await cur.fetchmany(_MAX_RESULT_ROWS + 1)
                truncated = len(rows_raw) > _MAX_RESULT_ROWS
                rows = [_format_row(r) for r in rows_raw[:_MAX_RESULT_ROWS]]
                await conn.commit()
                return ExecutionResult(
                    success=True,
                    columns=columns,
                    rows=rows,
                    row_count=len(rows),
                    affected_rows=cur.rowcount,
                    truncated=truncated,
                    source_session=source_session,
                )
            await conn.commit()
            return ExecutionResult(
                success=True, affected_rows=cur.rowcount, source_session=source_session
            )


def _format_row(row: tuple) -> list[str | None]:
    result: list[str | None] = []
    for v in row:
        if v is None:
            result.append(None)
        elif isinstance(v, (Decimal, float)):
            result.append(str(v))
        elif isinstance(v, datetime):
            result.append(v.isoformat())
        elif isinstance(v, bytes):
            result.append(f"<BLOB {len(v)}B>")
        else:
            result.append(str(v))
    return result


sql_executor = SQLExecutor()
