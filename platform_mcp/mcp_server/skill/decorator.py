"""@register_skill 装饰器 — 模块导入时收集 Skill 类"""

from __future__ import annotations

from typing import Any

_pending_skills: list[type] = []


def register_skill(name: str):
    """装饰器，标记 Skill 类并加入待注册队列。"""

    def decorator(cls: type) -> type:
        cls._skill_name = name  # type: ignore[attr-defined]
        _pending_skills.append(cls)
        return cls

    return decorator


def get_pending_skills() -> list[type]:
    """返回待注册 Skill 类列表，供 SkillRegistry 初始化时消费。"""
    return list(_pending_skills)


def clear_pending_skills() -> None:
    """清空待注册队列（测试用）。"""
    _pending_skills.clear()
