"""Skill README 自动生成模块

当 Skill 包缺少 README.md 时，按模板自动生成。
模板参考内部 readme skill 规范。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path


def generate_readme(
    skill_name: str,
    description: str,
    skill_dir: str | Path,
    version: str = "0.1.0",
) -> str:
    """生成 README.md 内容。

    Args:
        skill_name: Skill 名称（脱敏后）
        description: Skill 描述（来自 SKILL.md frontmatter）
        skill_dir: 解压后的 Skill 包根目录路径（用于扫描目录树）
        version: 版本号（默认 v0.1.0）

    Returns:
        生成的 README.md 文本内容
    """
    skill_path = Path(skill_dir)

    # 检测是否含 Python 文件
    has_python = any(
        f.endswith(".py")
        for root, _dirs, files in os.walk(skill_path)
        for f in files
    )

    # 生成目录树
    file_tree = _generate_file_tree(skill_path)

    # 生成快速开始指令
    quick_start = _generate_quick_start(skill_name)

    content = f"""# {skill_name}

{description}

## 环境要求

- Claude Code
"""
    if has_python:
        content += "- Python 3.11.9+\n"

    content += f"""
## 文件说明

```
{skill_name}/
{file_tree}```

## 快速开始

{quick_start}

## 项目信息

| 项目 | 值 |
|------|-----|
| 版本 | v{version} |
| 上传时间 | {date.today().isoformat()} |
"""
    return content


def should_generate_readme(skill_dir: str | Path) -> bool:
    """检查 Skill 包是否需要生成 README.md。

    Returns:
        True 如果包内不存在 README.md
    """
    skill_path = Path(skill_dir)
    return not (skill_path / "README.md").exists()


def write_readme(skill_dir: str | Path, content: str) -> None:
    """将生成的 README.md 写入 Skill 包目录。

    Args:
        skill_dir: Skill 包根目录路径
        content: README.md 内容
    """
    readme_path = Path(skill_dir) / "README.md"
    readme_path.write_text(content, encoding="utf-8")


def _generate_file_tree(skill_path: Path, prefix: str = "") -> str:
    """生成目录树形展示（类似 tree 命令输出）"""
    entries: list[str] = []

    try:
        items = sorted(skill_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return ""

    dirs = [p for p in items if p.is_dir() and p.name not in ("__pycache__", ".git")]
    files = [p for p in items if p.is_file()]

    for i, d in enumerate(dirs):
        is_last_dir = (i == len(dirs) - 1) and len(files) == 0
        connector = "└── " if is_last_dir else "├── "
        entries.append(f"{prefix}{connector}{d.name}/")
        extension = "    " if is_last_dir else "│   "
        entries.append(_generate_file_tree(d, prefix + extension))

    for i, f in enumerate(files):
        is_last = (i == len(files) - 1)
        connector = "└── " if is_last else "├── "
        entries.append(f"{prefix}{connector}{f.name}")

    return "\n".join(entries) + "\n"


def _generate_quick_start(skill_name: str) -> str:
    """生成快速开始说明"""
    return (
        f"1. 解压 Skill 包（如为 .zip 格式）\n"
        f"2. 将 Skill 目录复制到 `~/.claude/skills/` 或项目 `.claude/skills/`"
    )