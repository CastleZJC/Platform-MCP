"""Skill 共用权限层 — _check_env_permission（database + server 共享）

从 skills/database/__init__.py 抽离，避免在 server skill 中复制粘贴。
"""

from __future__ import annotations


def check_env_permission(env_code: str, role_code: str | None = None) -> None:
    """校验 MCP operator 角色是否允许访问目标环境。

    role_code 优先从 MCP 认证上下文传入（API Key 校验结果）；
    未传入时回退到 settings.mcp.operator_role（兼容遗留）。
    """
    from platform_mcp.common.exceptions import SkillError
    from platform_mcp.config import get_settings

    settings = get_settings()
    role = role_code or settings.mcp.operator_role

    if settings.mcp.allowed_envs is not None:
        if env_code not in settings.mcp.allowed_envs:
            raise SkillError(f"当前角色 {role} 不允许访问环境 {env_code}")

    if role == "developer" and env_code == "PROD":
        raise SkillError("developer 角色不允许访问 PROD 环境")
