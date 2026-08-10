"""Skill 自动发现 — 导入各 Skill 模块触发 @register_skill 装饰器"""

from platform_mcp.skills.database import DatabaseSkill  # noqa: F401
from platform_mcp.skills.server import ServerSkill  # noqa: F401
