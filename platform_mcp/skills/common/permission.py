"""Skill 共用权限层 — _check_env_permission（database + server 共享）

从 skills/database/__init__.py 抽离，避免在 server skill 中复制粘贴。
"""

from __future__ import annotations


def check_env_permission(env_code: str, role_code: str | None = None) -> None:
    """校验 MCP operator 角色是否允许访问目标环境。

    环境访问控制 = 角色规则（developer 禁 PROD）+ 组过滤（manager 层），
    无额外环境白名单参数。
    role_code 优先从 MCP 认证上下文传入（API Key 校验结果）；
    未传入时回退到 settings.mcp.operator_role（兼容遗留）。
    """
    from platform_mcp.common.exceptions import SkillError
    from platform_mcp.config import get_settings

    role = role_code or get_settings().mcp.operator_role

    if role == "developer" and env_code == "PROD":
        raise SkillError("developer 角色不允许访问 PROD 环境")
