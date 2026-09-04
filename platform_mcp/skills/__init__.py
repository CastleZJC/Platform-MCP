"""Skill 自动发现 — 导入各 Skill 模块触发 @register_skill 装饰器

注：``skill_ecosystem`` 依赖审核业务层 :mod:`platform_mcp.review.service`，而后者依赖
:mod:`platform_mcp.skills.models`；若在包 ``__init__`` 中 eager 导入会形成
``skills → ecosystem → review.service → skills.models → skills`` 的包级循环导入
（任何先导入 ``review.service`` 的路径都会崩）。故 ``skill_ecosystem`` 不在此 eager 导入，
改由 MCP 启动的 ``_register_skills()`` 显式导入注册；Web 进程经
``registry.get_skill_instance`` 懒实例化，两条路径均不触发该循环。
"""

from platform_mcp.skills.database import DatabaseSkill  # noqa: F401
from platform_mcp.skills.server import ServerSkill  # noqa: F401
