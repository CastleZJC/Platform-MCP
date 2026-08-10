"""Server Skill — SSH 命令执行 + SFTP 文件传输（6 个 Tool 实现）

镜像 skills/database/__init__.py 的整体结构：
- @register_skill("server") 装饰器
- _build_tool_meta() 返回 6 个 ToolMeta
- ServerSkill 类实现 skill_name / list_tools / validate / execute / support
- _check_env_permission 复用 skills/common/permission.py
- _execution_store + _EXECUTION_TTL=1800 异步执行结果 30 分钟 TTL
- HIGH/CRITICAL 命令/传输走 server_confirm_manager 二次确认

异步策略（与 database 一致）：
- execute_command：默认同步，用户显式 async_exec=True 转异步
- upload_file/download_file：默认同步，>200MB 转 async；HIGH+ 风险路径走 confirm_token
- get_server_execution_status：查询异步执行结果
"""

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
from platform_mcp.skills.common.risk_types import RiskLevel
from platform_mcp.skills.server.executor import _MAX_COMMAND_INPUT_BYTES
from platform_mcp.skills.server.risk import shell_risk_engine


_TOOL_NAMES = {
    "execute_command",
    "upload_file",
    "download_file",
    "list_servers",
    "validate_command",
    "get_server_execution_status",
}

_execution_store: dict[str, dict] = {}
_EXECUTION_TTL = 1800  # 30 minutes
_ASYNC_SIZE_THRESHOLD = 200 * 1024 * 1024  # 200MB SFTP 触发异步

# 系统关键目录前缀（即使 server.allowed_paths 配错也兜底判 CRITICAL）
_SYSTEM_CRITICAL_PATHS = (
    "/etc/", "/boot/", "/usr/", "/bin/", "/sbin/", "/lib/", "/lib64/",
    "/proc/", "/sys/", "/dev/",
)
_SYSTEM_HIGH_PATHS = (
    "/var/log/", "/var/spool/", "/root/", "/var/lib/",
)
_LARGE_FILE_MB_HIGH = 400  # >400MB → HIGH
_LARGE_FILE_MB_MEDIUM = 100  # >100MB → MEDIUM


def _cleanup_expired_executions() -> None:
    now = time.monotonic()
    expired = [eid for eid, rec in _execution_store.items() if now - rec.get("_created_at", 0) > _EXECUTION_TTL]
    for eid in expired:
        del _execution_store[eid]


def _should_run_async_transfer(file_size: int | None) -> bool:
    """SFTP 文件大小阈值判定。"""
    if file_size is None:
        return False
    return file_size > _ASYNC_SIZE_THRESHOLD


def _assess_transfer_risk(remote_path: str, file_size: int | None, env_code: str) -> RiskLevel:
    """SFTP 路径 + 文件大小风险评估。

    CRITICAL: 写系统关键目录（/etc、/boot、/usr、/bin、/sbin、/lib、/proc、/sys、/dev）
    HIGH:     写 /var/log、/var/spool、/root、/var/lib；或文件 >400MB
    MEDIUM:   文件 >100MB
    LOW:      其他（白名单校验由 _validate_remote_path 保证）
    """
    p = remote_path or ""
    for prefix in _SYSTEM_CRITICAL_PATHS:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return RiskLevel.CRITICAL
    for prefix in _SYSTEM_HIGH_PATHS:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return RiskLevel.HIGH
    if file_size is not None:
        if file_size > _LARGE_FILE_MB_HIGH * 1024 * 1024:
            return RiskLevel.HIGH
        if file_size > _LARGE_FILE_MB_MEDIUM * 1024 * 1024:
            return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _build_tool_meta() -> list[ToolMeta]:
    return [
        ToolMeta(
            tool_name="execute_command",
            display_name="执行命令",
            description="通过 SSH 在远端 Linux 服务器执行 shell 命令。命令输入上限 100KB，stdout/stderr 截断 1MB，命令超时 30 分钟。HIGH/CRITICAL 命令（rm -rf、mkfs、sudo 等）先返回 confirm_token，需二次确认；async_exec=true 时转异步返回 execution_id，可用 get_server_execution_status 轮询",
            input_schema={
                "type": "object",
                "properties": {
                    "server_code": {"type": "string", "description": "目标服务器编码，如 linux-app-dev"},
                    "command": {"type": "string", "description": "shell 命令文本"},
                    "env_code": {"type": "string", "default": "DEV"},
                    "confirm_token": {"type": "string", "description": "HIGH/CRITICAL 命令的二次确认 token"},
                    "async_exec": {"type": "boolean", "default": False, "description": "强制异步执行"},
                },
                "required": ["server_code", "command"],
            },
            risk_level="LOW",
            timeout_seconds=1800,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="upload_file",
            display_name="上传文件",
            description="通过 SFTP 将本地文件上传到远端 Linux 服务器。本地路径必须在 settings.datasource.allowed_sql_dirs 白名单内；远端路径必须在 server.allowed_paths 白名单内。写系统目录（/etc、/boot 等）判 CRITICAL；文件上限 500MB；>200MB 转异步",
            input_schema={
                "type": "object",
                "properties": {
                    "server_code": {"type": "string"},
                    "local_path": {"type": "string"},
                    "remote_path": {"type": "string"},
                    "env_code": {"type": "string", "default": "DEV"},
                    "confirm_token": {"type": "string", "description": "HIGH/CRITICAL 上传（系统目录、超大文件）的二次确认 token"},
                    "async_exec": {"type": "boolean", "default": False},
                },
                "required": ["server_code", "local_path", "remote_path"],
            },
            risk_level="LOW",
            timeout_seconds=600,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="download_file",
            display_name="下载文件",
            description="通过 SFTP 将远端 Linux 服务器文件下载到本地。路径白名单与大小限制同 upload_file；从系统目录下载敏感文件判 HIGH+ 走 confirm_token",
            input_schema={
                "type": "object",
                "properties": {
                    "server_code": {"type": "string"},
                    "remote_path": {"type": "string"},
                    "local_path": {"type": "string"},
                    "env_code": {"type": "string", "default": "DEV"},
                    "confirm_token": {"type": "string", "description": "HIGH/CRITICAL 下载的二次确认 token"},
                    "async_exec": {"type": "boolean", "default": False},
                },
                "required": ["server_code", "remote_path", "local_path"],
            },
            risk_level="LOW",
            timeout_seconds=600,
            audit_required=True,
        ),
        ToolMeta(
            tool_name="list_servers",
            display_name="列出服务器",
            description="列出所有可访问的 Linux 服务器（filter by env_code）",
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
            tool_name="validate_command",
            display_name="校验命令",
            description="校验 shell 命令并返回风险等级（不发往远端）",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "env_code": {"type": "string", "default": "DEV"},
                    "server_code": {"type": "string", "default": ""},
                },
                "required": ["command"],
            },
            risk_level="LOW",
            timeout_seconds=10,
            audit_required=False,
        ),
        ToolMeta(
            tool_name="get_server_execution_status",
            display_name="查询服务器执行状态",
            description="查询 server skill 异步执行任务状态（execute_command / upload_file / download_file 的 async_exec=true 返回的 execution_id）",
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


@register_skill("server")
class ServerSkill:

    def skill_name(self) -> str:
        return "server"

    def list_tools(self) -> list[ToolMeta]:
        return _build_tool_meta()

    async def validate(self, tool_name: str, params: dict) -> dict:
        from platform_mcp.common.exceptions import SkillError

        if tool_name == "execute_command":
            if not params.get("server_code"):
                raise SkillError("server_code 参数必填")
            command = params.get("command")
            if not command:
                raise SkillError("command 参数必填")
            if len(command) > _MAX_COMMAND_INPUT_BYTES:
                raise SkillError(
                    f"命令长度 {len(command)} 超过 {_MAX_COMMAND_INPUT_BYTES // 1024}KB 限制"
                )
        elif tool_name in ("upload_file", "download_file"):
            if not params.get("server_code"):
                raise SkillError("server_code 参数必填")
            if not params.get("local_path"):
                raise SkillError("local_path 参数必填")
            if not params.get("remote_path"):
                raise SkillError("remote_path 参数必填")
        elif tool_name == "validate_command":
            if not params.get("command"):
                raise SkillError("command 参数必填")
        elif tool_name == "get_server_execution_status":
            if not params.get("execution_id"):
                raise SkillError("execution_id 参数必填")
        return params

    async def execute(self, tool_name: str, params: dict, context: Any) -> Any:
        if tool_name == "execute_command":
            return await self._execute_command(params, context)
        if tool_name == "upload_file":
            return await self._upload_file(params, context)
        if tool_name == "download_file":
            return await self._download_file(params, context)
        if tool_name == "list_servers":
            return await self._list_servers(params)
        if tool_name == "validate_command":
            return await self._validate_command(params)
        if tool_name == "get_server_execution_status":
            return self._get_server_execution_status(params)
        raise NotImplementedError(f"Tool {tool_name} 未实现")

    def support(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # --- Tool 实现 ---

    async def _execute_command(self, params: dict, context: Any) -> dict:
        from platform_mcp.server.manager import server_manager
        from platform_mcp.skills.server.confirm import server_confirm_manager
        from platform_mcp.skills.server.executor import server_executor

        server_code = params["server_code"]
        command = params["command"]
        env_code = params.get("env_code", "DEV")
        confirm_token = params.get("confirm_token")
        async_exec = params.get("async_exec", False)

        role_code = self._read_role_code()
        _check_env_permission(env_code, role_code)

        risk = shell_risk_engine.analyze(command, env_code)
        if risk.needs_confirm:
            if not confirm_token:
                token = server_confirm_manager.generate("execute_command", server_code, command, risk.level)
                return {
                    "success": False,
                    "message": f"风险等级 {risk.level.value}，需要二次确认",
                    "risk_level": risk.level.value,
                    "reasons": risk.reasons,
                    "confirm_token": token,
                    "command_head": command[:64],
                }
            ctx = server_confirm_manager.validate(confirm_token, "execute_command", server_code)
            if not ctx:
                return {"success": False, "message": "confirm_token 无效或已过期"}
            server_confirm_manager.consume(confirm_token)

        conn_params = await server_manager.resolve_connection_params(server_code)

        if async_exec:
            return await self._start_async_execution(
                conn_params, command, env_code, risk, "command"
            )

        result = await server_executor.execute_command(conn_params, command)
        result_dict = asdict(result)
        result_dict["risk_level"] = risk.level.value
        result_dict["command_head"] = command[:64]
        return result_dict

    async def _upload_file(self, params: dict, context: Any) -> dict:
        from pathlib import Path

        from platform_mcp.server.manager import server_manager
        from platform_mcp.skills.server.confirm import server_confirm_manager
        from platform_mcp.skills.server.executor import server_executor

        server_code = params["server_code"]
        local_path = params["local_path"]
        remote_path = params["remote_path"]
        env_code = params.get("env_code", "DEV")
        confirm_token = params.get("confirm_token")
        async_exec = params.get("async_exec", False)

        role_code = self._read_role_code()
        _check_env_permission(env_code, role_code)

        try:
            file_size = Path(local_path).stat().st_size if Path(local_path).exists() else None
        except OSError:
            file_size = None

        # 路径 + 大小风险评估（与 database skill 对称的 confirm_token 流程）
        risk_level = _assess_transfer_risk(remote_path, file_size, env_code)
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            if not confirm_token:
                token = server_confirm_manager.generate(
                    "upload_file", server_code, f"upload->{remote_path}({file_size})", risk_level
                )
                return {
                    "success": False,
                    "message": f"风险等级 {risk_level.value}，需要二次确认",
                    "risk_level": risk_level.value,
                    "reasons": [f"上传到敏感路径或超大文件: {remote_path} size={file_size}"],
                    "confirm_token": token,
                    "remote_path": remote_path,
                }
            ctx = server_confirm_manager.validate(confirm_token, "upload_file", server_code)
            if not ctx:
                return {"success": False, "message": "confirm_token 无效或已过期"}
            server_confirm_manager.consume(confirm_token)

        conn_params = await server_manager.resolve_connection_params(server_code)

        if async_exec or _should_run_async_transfer(file_size):
            from platform_mcp.skills.common.risk_types import RiskResult

            return await self._start_async_execution(
                conn_params,
                command="",
                env_code=env_code,
                risk=RiskResult(level=risk_level, reasons=["upload"], statement_type="UPLOAD"),
                source_type="upload",
                local_path=local_path,
                remote_path=remote_path,
            )

        result = await server_executor.upload_file(conn_params, local_path, remote_path)
        return {
            **asdict(result),
            "operation": "upload",
            "local_path": local_path,
            "remote_path": remote_path,
            "risk_level": risk_level.value,
        }

    async def _download_file(self, params: dict, context: Any) -> dict:
        from platform_mcp.server.manager import server_manager
        from platform_mcp.skills.server.confirm import server_confirm_manager
        from platform_mcp.skills.server.executor import server_executor

        server_code = params["server_code"]
        remote_path = params["remote_path"]
        local_path = params["local_path"]
        env_code = params.get("env_code", "DEV")
        confirm_token = params.get("confirm_token")
        async_exec = params.get("async_exec", False)

        role_code = self._read_role_code()
        _check_env_permission(env_code, role_code)

        # 远端路径风险评估（不知道大小，仅按路径判）
        risk_level = _assess_transfer_risk(remote_path, None, env_code)
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            if not confirm_token:
                token = server_confirm_manager.generate(
                    "download_file", server_code, f"download->{remote_path}", risk_level
                )
                return {
                    "success": False,
                    "message": f"风险等级 {risk_level.value}，需要二次确认",
                    "risk_level": risk_level.value,
                    "reasons": [f"从敏感路径下载: {remote_path}"],
                    "confirm_token": token,
                    "remote_path": remote_path,
                }
            ctx = server_confirm_manager.validate(confirm_token, "download_file", server_code)
            if not ctx:
                return {"success": False, "message": "confirm_token 无效或已过期"}
            server_confirm_manager.consume(confirm_token)

        conn_params = await server_manager.resolve_connection_params(server_code)

        if async_exec:
            from platform_mcp.skills.common.risk_types import RiskResult

            return await self._start_async_execution(
                conn_params,
                command="",
                env_code=env_code,
                risk=RiskResult(level=risk_level, reasons=["download"], statement_type="DOWNLOAD"),
                source_type="download",
                local_path=local_path,
                remote_path=remote_path,
            )

        result = await server_executor.download_file(conn_params, remote_path, local_path)
        return {
            **asdict(result),
            "operation": "download",
            "local_path": local_path,
            "remote_path": remote_path,
            "risk_level": risk_level.value,
        }

    async def _list_servers(self, params: dict) -> dict:
        from platform_mcp.server.manager import server_manager

        srv_list = await server_manager.list_accessible_servers(params.get("env_code"))
        return {"servers": srv_list, "total": len(srv_list)}

    async def _validate_command(self, params: dict) -> dict:
        command = params["command"]
        env_code = params.get("env_code", "DEV")
        risk = shell_risk_engine.analyze(command, env_code)
        return {
            "risk_level": risk.level.value,
            "reasons": risk.reasons,
            "statement_type": risk.statement_type,
            "needs_confirm": risk.needs_confirm,
        }

    def _get_server_execution_status(self, params: dict) -> dict:
        _cleanup_expired_executions()
        execution_id = params["execution_id"]
        record = _execution_store.get(execution_id)
        if not record:
            return {"success": False, "message": f"执行记录 {execution_id} 不存在或已过期"}
        return {
            "success": True,
            "execution_id": execution_id,
            "status": record["status"],
            "result": record.get("result"),
            "risk_level": record.get("risk_level"),
            "source_type": record.get("source_type"),
        }

    def _read_role_code(self) -> str | None:
        try:
            from platform_mcp.mcp_server import get_current_identity

            identity = get_current_identity()
            if identity:
                return identity.get("role_code")
        except Exception:
            return None
        return None

    async def _start_async_execution(
        self,
        conn_params: Any,
        command: str,
        env_code: str,
        risk: Any,
        source_type: str,
        local_path: str | None = None,
        remote_path: str | None = None,
    ) -> dict:
        from platform_mcp.skills.server.executor import server_executor

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
        if local_path:
            _execution_store[execution_id]["local_path"] = local_path
        if remote_path:
            _execution_store[execution_id]["remote_path"] = remote_path

        async def _run_background():
            """后台执行命令/传输，结果写入 _execution_store。

            TTL 30 分钟内可能被 _cleanup_expired_executions 清理，store 写入前 .get() 兜底。
            """
            from dataclasses import asdict as _asdict

            rec = _execution_store.get(execution_id)
            if rec is None:
                logger.warning("async execution %s evicted before RUNNING", execution_id)
                return
            rec["status"] = "RUNNING"
            try:
                if source_type == "command":
                    cmd_result = await server_executor.execute_command(conn_params, command)
                    rec = _execution_store.get(execution_id)
                    if rec is None:
                        logger.warning("async execution %s evicted during run", execution_id)
                        return
                    rec["result"] = _asdict(cmd_result)
                    rec["status"] = "SUCCESS" if cmd_result.success else "FAILED"
                elif source_type == "upload":
                    assert local_path is not None and remote_path is not None
                    up_result = await server_executor.upload_file(conn_params, local_path, remote_path)
                    rec = _execution_store.get(execution_id)
                    if rec is None:
                        return
                    rec["result"] = _asdict(up_result)
                    rec["status"] = "SUCCESS" if up_result.success else "FAILED"
                elif source_type == "download":
                    assert local_path is not None and remote_path is not None
                    dl_result = await server_executor.download_file(conn_params, remote_path, local_path)
                    rec = _execution_store.get(execution_id)
                    if rec is None:
                        return
                    rec["result"] = _asdict(dl_result)
                    rec["status"] = "SUCCESS" if dl_result.success else "FAILED"
            except Exception as e:
                rec = _execution_store.get(execution_id)
                if rec is None:
                    logger.warning("async execution %s evicted before error capture", execution_id)
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
            "source_type": source_type,
        }
