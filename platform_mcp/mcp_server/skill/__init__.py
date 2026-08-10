"""Skill 注册框架"""

from platform_mcp.mcp_server.skill.decorator import get_pending_skills, register_skill
from platform_mcp.mcp_server.skill.protocol import SkillProtocol, ToolMeta
from platform_mcp.mcp_server.skill.registry import SkillRegistry, registry

__all__ = [
    "SkillProtocol",
    "ToolMeta",
    "register_skill",
    "get_pending_skills",
    "SkillRegistry",
    "registry",
]
