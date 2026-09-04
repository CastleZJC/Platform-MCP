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
    if skill_code == "skill_ecosystem":
        from platform_mcp.skills.ecosystem import SkillEcosystemSkill
        return SkillEcosystemSkill()
    if skill_code == "skill_plaza":
        from platform_mcp.skills.ecosystem.plaza_tools import SkillPlazaToolsSkill
        return SkillPlazaToolsSkill()
    if skill_code == "skill_account":
        from platform_mcp.skills.ecosystem.account_tools import SkillAccountToolsSkill
        return SkillAccountToolsSkill()
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
        # 勘误5：停用 Skill 编码集合（消费 pmcp_skill.status=DISABLED）
        self._disabled_skills: set[str] = set()

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

    def set_disabled_skills(self, skill_codes: set[str]) -> None:
        """设置停用 Skill 集合（勘误5：真实消费 pmcp_skill.status）。

        启动时由 ``_register_skills`` 从库加载；HTTP 模式周期刷新。停用 Skill 的
        Tool 不被路由/列举，handler 调用被状态门拒绝——启停对 MCP 层真实生效（F-43）。
        """
        self._disabled_skills = set(skill_codes)

    def is_skill_disabled(self, skill_name: str) -> bool:
        return skill_name in self._disabled_skills

    @staticmethod
    def _role_allows(meta: ToolMeta | None, role_code: str | None) -> bool:
        """角色可见性（架构 §19.5.7）：``role_code`` 为空（遗留 stdio 无 Key）不过滤，
        保持既有 operator_role 回退语义；否则角色须在 ``meta.roles`` 内。"""
        if role_code is None or meta is None:
            return True
        return role_code in meta.roles

    def route(self, tool_name: str, role_code: str | None = None) -> SkillProtocol | None:
        skill = self._tool_map.get(tool_name)
        # 勘误5：停用 Skill 不可路由
        if skill is not None and skill.skill_name() in self._disabled_skills:
            return None
        # V3.0 M3.5：角色不可见的 Tool 不可路由
        if skill is not None and not self._role_allows(self._tool_metas.get(tool_name), role_code):
            return None
        return skill

    def get_tool_meta(self, tool_name: str, role_code: str | None = None) -> ToolMeta | None:
        skill = self._tool_map.get(tool_name)
        if skill is not None and skill.skill_name() in self._disabled_skills:
            return None
        meta = self._tool_metas.get(tool_name)
        if not self._role_allows(meta, role_code):
            return None
        return meta

    def list_all_tools(self, role_code: str | None = None) -> list[ToolMeta]:
        # 勘误5：过滤停用 Skill 的 Tool；V3.0 M3.5：叠加按 role_code 动态过滤（§19.5.7）
        return [
            meta
            for tool_name, meta in self._tool_metas.items()
            if self._tool_map[tool_name].skill_name() not in self._disabled_skills
            and self._role_allows(meta, role_code)
        ]

    def allowed_tool_names(self, role_code: str | None = None) -> set[str]:
        """当前角色可见（且未停用）的工具名集合，供 FastMCP list_tools 按身份过滤。"""
        return {meta.tool_name for meta in self.list_all_tools(role_code)}

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
        _registry = self
        _sig = _build_handler_signature(meta.input_schema)

        async def _handler(**kwargs) -> str:
            import time

            ctx = build_context(_meta.tool_name, **kwargs)
            # 勘误5：路由状态门 —— Skill 停用（pmcp_skill.status=DISABLED）时拒绝调用并审计
            if _registry.is_skill_disabled(_skill.skill_name()):
                disabled_msg = f"Skill '{_skill.skill_name()}' 已停用，不可调用"
                await log_mcp_call(ctx, "error", 0, error=disabled_msg, error_code="SKILL_DISABLED")
                return format_tool_result(
                    None, ctx.trace_id, error_code=10001, error_message=disabled_msg
                )
            # V3.0 M3.5：角色门 —— 调用路由按认证身份 role_code 过滤（§19.5.7），
            # 与 list_tools 双保险（客户端缓存旧工具清单时仍拦截）。无身份（遗留 stdio 无 Key）不拦。
            _role_code = (ctx.identity or {}).get("role_code")
            if _role_code is not None and _role_code not in _meta.roles:
                forbidden_msg = f"角色 '{_role_code}' 无权调用工具 '{_meta.tool_name}'"
                await log_mcp_call(ctx, "error", 0, error=forbidden_msg, error_code="ROLE_FORBIDDEN")
                return format_tool_result(
                    None, ctx.trace_id, error_code=10004, error_message=forbidden_msg
                )
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
                # BUG20260817 BUG-5 收紧：confirm 拦截（CONFIRM_REQUIRED）同样记 error ——
                # 该次调用 SQL 未执行，如实反映；携带 token 重试成功后有独立 success 行，
                # 审计可对账"确认→执行"两跳。error_code 优先取业务 payload 显式携带值
                # （MULTI_STMT_HIGH_RISK / CONFIRM_REQUIRED / CONFIRM_TOKEN_INVALID /
                # EMPTY_SQL / EXECUTION_FAILED / WORKSTATION_PATH），缺省 10001。
                if isinstance(result, dict) and result.get("success") is False:
                    biz_error = str(
                        result.get("error_message")
                        or result.get("message")
                        or "业务执行失败"
                    )
                    biz_error_code = str(result.get("error_code") or "10001")
                    await log_mcp_call(
                        ctx, "error", duration_ms,
                        error=biz_error, error_code=biz_error_code,
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
