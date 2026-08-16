"""SkillRegistry — Skill 注册、路由与 Tool 查询"""

from __future__ import annotations

import inspect
from typing import Any, cast

from loguru import logger
from mcp.server.fastmcp import FastMCP

from platform_mcp.mcp_server.skill.protocol import SkillProtocol, ToolMeta


_JSON_TYPE_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def get_skill_instance(skill_code: str) -> SkillProtocol | None:
    """工厂函数：按 skill_code 实例化 Skill，供 web 进程（registry 空）使用。

    Web 进程不消费 _pending_skills 队列（仅 MCP server 启动时消费），
    因此 web 层若需要 Skill 实例获取 list_tools()，必须用此工厂直接实例化，
    不能依赖 SkillRegistry。
    """
    if skill_code == "database":
        from platform_mcp.skills.database import DatabaseSkill
        return DatabaseSkill()
    if skill_code == "server":
        from platform_mcp.skills.server import ServerSkill
        return ServerSkill()
    return None


def _build_handler_signature(input_schema: dict) -> inspect.Signature:
    """从 ToolMeta.input_schema (JSON Schema) 构建 inspect.Signature。

    FastMCP 通过 inspect.signature(fn) 自省生成 pydantic model。
    若 handler 用 **kwargs，model 会变成 {kwargs: dict}（required），
    导致标准 MCP 客户端（arguments 直接是参数 dict）校验失败。

    本函数把 JSON Schema 还原为显式参数签名，让 FastMCP 生成正确 model。
    """
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    params: list[inspect.Parameter] = []
    for name, schema in properties.items():
        py_type = _JSON_TYPE_TO_PY.get(schema.get("type", "string"), str)
        if name in required:
            params.append(
                inspect.Parameter(
                    name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=py_type
                )
            )
        else:
            default = schema.get("default") if "default" in schema else None
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=py_type,
                    default=default,
                )
            )
    return inspect.Signature(params)


class SkillRegistry:
    """维护 skill_name -> Skill / tool_name -> Skill 映射，支持 Tool 注册到 FastMCP。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillProtocol] = {}
        self._tool_map: dict[str, SkillProtocol] = {}
        self._tool_metas: dict[str, ToolMeta] = {}

    def register(self, skill: SkillProtocol) -> None:
        name = skill.skill_name()
        self._skills[name] = skill
        tools = skill.list_tools()
        for meta in tools:
            self._tool_map[meta.tool_name] = skill
            self._tool_metas[meta.tool_name] = meta
        logger.info(
            "registered skill: {}, tools: {}",
            name,
            [m.tool_name for m in tools],
        )

    def get_skill(self, skill_name: str) -> SkillProtocol | None:
        return self._skills.get(skill_name)

    def route(self, tool_name: str) -> SkillProtocol | None:
        return self._tool_map.get(tool_name)

    def get_tool_meta(self, tool_name: str) -> ToolMeta | None:
        return self._tool_metas.get(tool_name)

    def list_all_tools(self) -> list[ToolMeta]:
        return list(self._tool_metas.values())

    def register_all_tools(self, mcp: FastMCP) -> None:
        """将所有已注册 Skill 的 Tool 注册到 FastMCP 实例。"""
        for tool_name, meta in self._tool_metas.items():
            skill = self._tool_map[tool_name]
            self._register_single_tool(mcp, meta, skill)

    def _register_single_tool(self, mcp: FastMCP, meta: ToolMeta, skill: SkillProtocol) -> None:
        from platform_mcp.mcp_server.call_log import log_mcp_call
        from platform_mcp.mcp_server.context import McpContext, build_context
        from platform_mcp.mcp_server.tool_wrapper import format_tool_result

        _skill = skill
        _meta = meta
        _sig = _build_handler_signature(meta.input_schema)

        async def _handler(**kwargs) -> str:
            import time

            ctx = build_context(_meta.tool_name, **kwargs)
            start = time.monotonic()
            try:
                params = dict(kwargs)
                validated = await _skill.validate(_meta.tool_name, params)
                result = await _skill.execute(_meta.tool_name, validated, ctx)
                if isinstance(result, dict):
                    ctx.risk_level = result.get("risk_level")
                    extra: dict = {}
                    if result.get("statement_type") is not None:
                        extra["statement_type"] = result.get("statement_type")
                    if result.get("row_count") is not None:
                        extra["row_count"] = result.get("row_count")
                    if result.get("confirm_token"):
                        extra["confirm_token"] = result.get("confirm_token")
                    if result.get("source_session"):
                        ctx.source_session = result.get("source_session")
                    if extra:
                        ctx.extra_data = extra
                duration_ms = int((time.monotonic() - start) * 1000)
                # BUG20260814163941 补充修复：executor 内部捕获的业务失败以 success=False
                # 正常返回（不抛异常），此前一律记 success → "业务失败=审计成功"。
                # confirm_token 存在时是风险确认流，不算失败。
                if (
                    isinstance(result, dict)
                    and result.get("success") is False
                    and not result.get("confirm_token")
                ):
                    biz_error = str(
                        result.get("error_message")
                        or result.get("message")
                        or "业务执行失败"
                    )
                    await log_mcp_call(
                        ctx, "error", duration_ms,
                        error=biz_error, error_code="10001",
                    )
                else:
                    await log_mcp_call(ctx, "success", duration_ms)
                return format_tool_result(result, ctx.trace_id)
            except Exception as e:
                duration_ms = int((time.monotonic() - start) * 1000)
                from platform_mcp.common.exceptions import BaseError

                code = e.error_code if isinstance(e, BaseError) else 10001
                await log_mcp_call(
                    ctx, "error", duration_ms,
                    error=str(e), error_code=str(code),
                )
                return format_tool_result(None, ctx.trace_id, error_code=code, error_message=str(e))

        # 关键：在 add_tool 之前设置 __signature__，让 FastMCP 的 func_metadata
        # 通过 inspect.signature(fn) 自省时看到显式参数（从 input_schema 还原），
        # 生成的 pydantic model 才是 {field1: type1, field2: type2}，标准 MCP 客户端
        # 的 arguments（直接是参数 dict）才能通过校验。装饰器形式会先自省再设签名，无效。
        cast(Any, _handler).__signature__ = _sig
        _handler.__name__ = meta.tool_name
        _handler.__qualname__ = meta.tool_name
        mcp.add_tool(_handler, name=_meta.tool_name, description=_meta.description)


# 全局单例
registry = SkillRegistry()
