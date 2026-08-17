"""Database Skill — SQL 执行能力（5 个 Tool 实现）"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from typing import Any

from loguru import logger

from platform_mcp.mcp_server.skill.decorator import register_skill
from platform_mcp.mcp_server.skill.protocol import ToolMeta
from platform_mcp.skills.common.permission import check_env_permission as _check_env_permission
from platform_mcp.skills.common.risk_types import RiskResult, _LEVEL_ORDER
from platform_mcp.skills.database.risk import risk_engine

_TOOL_NAMES = {
    "execute_sql_text",
    "execute_sql_file",
    "validate_sql",
    "list_datasources",
    "get_execution_status",
}

_execution_store: dict[str, dict] = {}
_EXECUTION_TTL = 1800  # 30 minutes


def _cleanup_expired_executions() -> None:
    now = time.monotonic()
    expired = [eid for eid, rec in _execution_store.items() if now - rec.get("_created_at", 0) > _EXECUTION_TTL]
    for eid in expired:
        del _execution_store[eid]


# 自动异步执行阈值：超过任一阈值则内部转异步（避免 SSE 长连接超时）
_ASYNC_LEN_THRESHOLD = 5000  # SQL 内容字符数
_ASYNC_STMT_THRESHOLD = 3    # 多语句文件语句数


def _should_run_async(content: str, statements: list[str] | None = None) -> bool:
    """自动判定 SQL 是否需要异步执行。

    判定规则（满足任一即异步）：
    - 内容长度 > _ASYNC_LEN_THRESHOLD（默认 5000 字符，约 200 行 SQL）
    - 语句数量 > _ASYNC_STMT_THRESHOLD（默认 3，多语句文件单次同步执行易超时）

    设计动机：MCP streamable-http 的 SSE 单流有超时限制，长 SQL 同步执行
    期间 SSE channel 可能断开导致响应投递失败。由工具内部自动判定可避免
    用户感知 async_exec 参数。
    """
    if len(content) > _ASYNC_LEN_THRESHOLD:
        return True
    if statements is not None and len(statements) > _ASYNC_STMT_THRESHOLD:
        return True
    return False


def _analyze_risks(statements: list[str], env_code: str) -> tuple[list[RiskResult], RiskResult]:
    """逐语句风险评估，返回 (risks, max_risk)。"""
    risks = [risk_engine.analyze(s, env_code) for s in statements]
    max_risk = risks[0]
    for r in risks[1:]:
        if _LEVEL_ORDER[r.level] > _LEVEL_ORDER[max_risk.level]:
            max_risk = r
    return risks, max_risk


def _reject_multi_stmt_high_risk(statements: list[str], risks: list[RiskResult], max_risk: RiskResult) -> dict:
    """BUG20260817 BUG-2：多语句含 HIGH/CRITICAL → 直接拒绝（不走 confirm）。

    整批 confirm 有风险遮蔽（10 条 CREATE 藏 1 条 DROP 只确认一次），
    且 multi-statement 场景 sql_hash 无法逐句绑定。单语句高风险不受影响。
    """
    high_types = [r.statement_type for r in risks if r.needs_confirm]
    high_levels = sorted({r.level.value for r in risks if r.needs_confirm})
    return {
        "success": False,
        "error_code": "MULTI_STMT_HIGH_RISK",
        "message": (
            f"高风险操作不可多语句执行：检测到 {'/'.join(high_levels)} 风险语句"
            f"（{', '.join(high_types)}），请拆分为单语句逐条执行"
        ),
        "statement_count": len(statements),
        "risk_level": max_risk.level.value,
        "reasons": [reason for r in risks if r.needs_confirm for reason in r.reasons],
    }


def _confirm_required_payload(
    tool_name: str, ds_code: str, stmt: str, risk: RiskResult, statement_count: int | None = None
) -> dict:
    """BUG20260817 BUG-4：confirm 拦截响应带重试指引（含 TTL 提示）。"""
    from platform_mcp.skills.database.confirm import confirm_manager

    token = confirm_manager.generate(tool_name, ds_code, stmt, risk.level)
    payload = {
        "success": False,
        "error_code": "CONFIRM_REQUIRED",
        "message": (
            f"风险等级 {risk.level.value}，需二次确认：请将本响应中的 confirm_token 作为参数"
            "重新调用本工具完成执行（token 5 分钟内有效，仅可使用一次）"
        ),
        "risk_level": risk.level.value,
        "reasons": risk.reasons,
        "confirm_token": token,
        "statement_type": risk.statement_type,
    }
    if statement_count is not None:
        payload["statement_count"] = statement_count
    return payload


def _build_tool_meta() -> list[ToolMeta]:
    return [
        ToolMeta(
            tool_name="execute_sql_text",
            display_name="执行SQL文本",
            description="接收 SQL 文本并在指定数据源上执行。支持低风险多语句（全 SELECT/INSERT/UPDATE/DELETE）逐条批量执行；多语句中包含 HIGH/CRITICAL 语句（DDL、无 WHERE 的 DELETE/UPDATE 等）将被直接拒绝（error_code=MULTI_STMT_HIGH_RISK），请拆分为单语句逐条执行；高风险单语句首次调用返回 confirm_token，需携带该 token 重新调用完成执行（5 分钟内有效、仅可使用一次）。SQL*Plus 风格 `/` 分隔符自动忽略。长 SQL（内容 >5000 字符或语句数 >3）自动转异步，返回 execution_id，需调用 get_execution_status 轮询直到 SUCCESS/FAILED",
            input_schema={
                "type": "object",
                "properties": {
                    "sql_text": {"type": "string"},
                    "datasource_code": {"type": "string"},
                    "env_code": {"type": "string", "default": "DEV"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["sql_text", "datasource_code"],
            },
            risk_level="LOW",
            timeout_seconds=300,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="execute_sql_file",
            display_name="执行SQL文件",
            description="接收文件路径，读取 SQL 文件并在指定数据源上执行，逐条执行。多语句中包含 HIGH/CRITICAL 语句将被直接拒绝（error_code=MULTI_STMT_HIGH_RISK），请拆分为单语句文件；单语句高风险（DDL 等）首次调用返回 confirm_token，需携带该 token 重新调用完成执行（5 分钟内有效、仅可使用一次）。SQL*Plus 风格 `/` 分隔符自动忽略。长文件（内容 >5000 字符或语句数 >3）自动转异步，返回 execution_id，需调用 get_execution_status 轮询直到 SUCCESS/FAILED",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "datasource_code": {"type": "string"},
                    "env_code": {"type": "string", "default": "DEV"},
                    "confirm_token": {"type": "string"},
                },
                "required": ["file_path", "datasource_code"],
            },
            risk_level="LOW",
            timeout_seconds=300,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="validate_sql",
            display_name="校验SQL",
            description="校验 SQL 并返回风险等级；返回的 needs_confirm 字段可用于预判是否需二次确认",
            input_schema={
                "type": "object",
                "properties": {
                    "sql_text": {"type": "string"},
                    "env_code": {"type": "string", "default": "DEV"},
                },
                "required": ["sql_text"],
            },
            risk_level="LOW",
            timeout_seconds=10,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="list_datasources",
            display_name="列出数据源",
            description="列出所有可访问的数据源",
            input_schema={
                "type": "object",
                "properties": {
                    "env_code": {"type": "string"},
                },
            },
            risk_level="LOW",
            timeout_seconds=10,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="get_execution_status",
            display_name="查询执行状态",
            description="查询异步执行任务状态",
            input_schema={
                "type": "object",
                "properties": {
                    "execution_id": {"type": "string"},
                },
                "required": ["execution_id"],
            },
            risk_level="LOW",
            timeout_seconds=10,
            audit_required=False,
        ),
    ]


@register_skill("database")
class DatabaseSkill:

    def skill_name(self) -> str:
        return "database"

    def list_tools(self) -> list[ToolMeta]:
        return _build_tool_meta()

    async def validate(self, tool_name: str, params: dict) -> dict:
        from platform_mcp.common.exceptions import SkillError

        if tool_name in ("execute_sql_text", "execute_sql_file"):
            if not params.get("datasource_code"):
                raise SkillError("datasource_code 参数必填")
        if tool_name == "execute_sql_text" and not params.get("sql_text"):
            raise SkillError("sql_text 参数必填")
        if tool_name == "execute_sql_file" and not params.get("file_path"):
            raise SkillError("file_path 参数必填")
        if tool_name == "validate_sql" and not params.get("sql_text"):
            raise SkillError("sql_text 参数必填")
        if tool_name == "get_execution_status" and not params.get("execution_id"):
            raise SkillError("execution_id 参数必填")
        return params

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any:
        if tool_name == "execute_sql_text":
            return await self._execute_sql_text(params, context)
        if tool_name == "execute_sql_file":
            return await self._execute_sql_file(params, context)
        if tool_name == "validate_sql":
            return await self._validate_sql(params)
        if tool_name == "list_datasources":
            return await self._list_datasources(params)
        if tool_name == "get_execution_status":
            return self._get_execution_status(params)
        raise NotImplementedError(f"Tool {tool_name} 未实现")

    def support(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # --- Tool 实现 ---

    async def _execute_sql_text(self, params: dict, context: Any) -> dict:
        from platform_mcp.datasource.manager import datasource_manager
        from platform_mcp.skills.database.confirm import confirm_manager
        from platform_mcp.skills.database.executor import split_statements, sql_executor

        sql = params["sql_text"]
        ds_code = params["datasource_code"]
        env_code = params.get("env_code", "DEV")
        confirm_token = params.get("confirm_token")
        async_exec = params.get("async_exec", False)

        role_code = None
        try:
            from platform_mcp.mcp_server import get_current_identity
            identity = get_current_identity()
            if identity:
                role_code = identity.get("role_code")
        except Exception:
            pass
        _check_env_permission(env_code, role_code)

        # BUG20260817 BUG-1/3：text 路径分句 + `/` 过滤（原实现整段直传驱动，多语句必挂）
        statements = split_statements(sql)
        if not statements:
            return {"success": False, "error_code": "EMPTY_SQL", "message": "SQL 内容为空"}

        risks, max_risk = _analyze_risks(statements, env_code)

        if len(statements) > 1 and any(r.needs_confirm for r in risks):
            return _reject_multi_stmt_high_risk(statements, risks, max_risk)

        if max_risk.needs_confirm:
            if not confirm_token:
                return _confirm_required_payload(
                    "execute_sql_text", ds_code, statements[0], max_risk
                )
            ctx = confirm_manager.validate(
                confirm_token,
                "execute_sql_text",
                ds_code,
                sql_hash=confirm_manager.hash_sql(statements[0]),
            )
            if not ctx:
                return {
                    "success": False,
                    "error_code": "CONFIRM_TOKEN_INVALID",
                    "message": (
                        "confirm_token 无效或已过期（已使用/超 5 分钟/与当前 SQL 不匹配），"
                        "请不带 token 重新调用获取新 token"
                    ),
                }
            confirm_manager.consume(confirm_token)

        conn_params = await datasource_manager.resolve_connection_params(ds_code)

        if async_exec or _should_run_async(sql, statements):
            return await self._start_async_execution(
                conn_params, sql, env_code, max_risk, "sql_text", statements=statements
            )

        results = await sql_executor.execute_statements(statements, conn_params)
        all_ok = all(r.success for r in results)
        result_dict: dict = {
            "success": all_ok,
            "statement_count": len(results),
            "results": [asdict(r) for r in results],
            "risk_level": max_risk.level.value,
            "statement_type": max_risk.statement_type,
        }
        if not all_ok:
            result_dict["error_code"] = "EXECUTION_FAILED"
            result_dict["error_message"] = next(
                (r.error_message for r in results if not r.success), "SQL 执行失败"
            )
        return result_dict

    async def _execute_sql_file(self, params: dict, context: Any) -> dict:
        from platform_mcp.datasource.manager import datasource_manager
        from platform_mcp.skills.database.confirm import confirm_manager
        from platform_mcp.skills.database.executor import split_statements, sql_executor

        file_path = params["file_path"]
        ds_code = params["datasource_code"]
        env_code = params.get("env_code", "DEV")
        confirm_token = params.get("confirm_token")
        async_exec = params.get("async_exec", False)

        role_code = None
        try:
            from platform_mcp.mcp_server import get_current_identity
            identity = get_current_identity()
            if identity:
                role_code = identity.get("role_code")
        except Exception:
            pass
        _check_env_permission(env_code, role_code)

        conn_params = await datasource_manager.resolve_connection_params(ds_code)
        validated_path = sql_executor._validate_file_path(file_path)
        content = validated_path.read_text(encoding="utf-8")

        # BUG20260817 BUG-3：分句统一走 split_statements（过滤 `/` 碎片）
        statements = split_statements(content)
        if not statements:
            return {"success": False, "error_code": "EMPTY_SQL", "error_message": "SQL 文件为空"}

        risks, max_risk = _analyze_risks(statements, env_code)

        # BUG20260817 BUG-2：原实现 max_risk 一次 confirm_token 覆盖整批（10 条 CREATE
        # 藏 1 条 DROP 也只确认一次，风险遮蔽）——收紧为多语句高风险直接拒绝
        if len(statements) > 1 and any(r.needs_confirm for r in risks):
            return _reject_multi_stmt_high_risk(statements, risks, max_risk)

        if max_risk.needs_confirm:
            if not confirm_token:
                return _confirm_required_payload(
                    "execute_sql_file", ds_code, statements[0], max_risk,
                    statement_count=len(statements),
                )
            ctx = confirm_manager.validate(
                confirm_token,
                "execute_sql_file",
                ds_code,
                sql_hash=confirm_manager.hash_sql(statements[0]),
            )
            if not ctx:
                return {
                    "success": False,
                    "error_code": "CONFIRM_TOKEN_INVALID",
                    "message": (
                        "confirm_token 无效或已过期（已使用/超 5 分钟/与当前 SQL 不匹配），"
                        "请不带 token 重新调用获取新 token"
                    ),
                }
            confirm_manager.consume(confirm_token)

        if async_exec or _should_run_async(content, statements):
            return await self._start_async_execution(
                conn_params, content, env_code, max_risk, "sql_file", file_path=file_path
            )

        results = await sql_executor.execute_file(file_path, conn_params)
        all_ok = all(r.success for r in results)
        result_payload: dict = {
            "success": all_ok,
            "statement_count": len(results),
            "results": [asdict(r) for r in results],
            "risk_level": max_risk.level.value,
            "statement_type": max_risk.statement_type,
        }
        if not all_ok:
            result_payload["error_code"] = "EXECUTION_FAILED"
            result_payload["error_message"] = next(
                (r.error_message for r in results if not r.success), "SQL 执行失败"
            )
        return result_payload

    async def _start_async_execution(
        self,
        conn_params: Any,
        sql: str,
        env_code: str,
        risk: Any,
        source_type: str,
        file_path: str | None = None,
        statements: list[str] | None = None,
    ) -> dict:
        from platform_mcp.skills.database.executor import sql_executor

        _cleanup_expired_executions()

        execution_id = str(uuid.uuid4())
        _execution_store[execution_id] = {
            "status": "PENDING",
            "result": None,
            "risk_level": risk.level.value,
            "source_type": source_type,
            "env_code": env_code,
            "_created_at": time.monotonic(),
        }
        if file_path:
            _execution_store[execution_id]["file_path"] = file_path

        async def _run_background():
            """后台执行 SQL，结果写入 _execution_store。

            注意：执行期间可能被 _cleanup_expired_executions 清理（TTL 30 分钟），
            所有 store 写入前必须用 .get() 兜底，避免 KeyError 让 task 异常
            累积导致进程崩溃（"Task exception was never retrieved"）。
            """
            rec = _execution_store.get(execution_id)
            if rec is None:
                logger.warning("async execution %s evicted before RUNNING", execution_id)
                return
            rec["status"] = "RUNNING"
            try:
                if source_type == "sql_file":
                    assert file_path is not None
                    results = await sql_executor.execute_file(file_path, conn_params)
                    rec = _execution_store.get(execution_id)
                    if rec is None:
                        logger.warning(
                            "async execution %s evicted during execution, discarding result",
                            execution_id,
                        )
                        return
                    rec["result"] = [asdict(r) for r in results]
                    rec["status"] = "SUCCESS" if all(r.success for r in results) else "FAILED"
                    rec["statement_count"] = len(results)
                else:
                    # BUG20260817 BUG-1：text 异步路径同样逐条执行（原实现整段直传驱动）
                    stmts = statements
                    if stmts is None:
                        from platform_mcp.skills.database.executor import split_statements
                        stmts = split_statements(sql)
                    results = await sql_executor.execute_statements(stmts, conn_params)
                    rec = _execution_store.get(execution_id)
                    if rec is None:
                        logger.warning(
                            "async execution %s evicted during execution, discarding result",
                            execution_id,
                        )
                        return
                    rec["result"] = [asdict(r) for r in results]
                    rec["status"] = "SUCCESS" if all(r.success for r in results) else "FAILED"
                    rec["statement_count"] = len(results)
            except Exception as e:
                rec = _execution_store.get(execution_id)
                if rec is None:
                    logger.warning(
                        "async execution %s evicted before error capture", execution_id
                    )
                    return
                rec["status"] = "ERROR"
                rec["result"] = {"error_message": str(e)}

        asyncio.create_task(_run_background())

        return {
            "success": True,
            "execution_id": execution_id,
            "status": "PENDING",
            "message": "异步执行已提交",
            "risk_level": risk.level.value,
        }

    async def _validate_sql(self, params: dict) -> dict:
        risk = risk_engine.analyze(params["sql_text"], params.get("env_code", "DEV"))
        return {
            "risk_level": risk.level.value,
            "reasons": risk.reasons,
            "statement_type": risk.statement_type,
            "needs_confirm": risk.needs_confirm,
        }

    async def _list_datasources(self, params: dict) -> dict:
        from platform_mcp.datasource.manager import datasource_manager

        ds_list = await datasource_manager.list_accessible_datasources(params.get("env_code"))
        return {"datasources": ds_list, "total": len(ds_list)}

    def _get_execution_status(self, params: dict) -> dict:
        _cleanup_expired_executions()
        execution_id = params["execution_id"]
        record = _execution_store.get(execution_id)
        if not record:
            return {"success": False, "message": f"执行记录 {execution_id} 不存在或已过期"}
        result = record.get("result")
        source_session = None
        if isinstance(result, dict):
            source_session = result.get("source_session")
        elif isinstance(result, list):
            for r in result:
                if isinstance(r, dict) and r.get("source_session"):
                    source_session = r["source_session"]
                    break
        return {
            "success": True,
            "execution_id": execution_id,
            "status": record["status"],
            "result": result,
            "risk_level": record.get("risk_level"),
            "source_session": source_session,
        }
