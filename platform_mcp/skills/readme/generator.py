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
    tools: list[tuple[str, str]] | None = None,
    register_method: str | None = None,
) -> str:
    """生成 README.md 内容。

    Args:
        skill_name: Skill 名称（脱敏后）
        description: Skill 描述（来自 SKILL.md frontmatter）
        skill_dir: 解压后的 Skill 包根目录路径（用于扫描目录树）
        version: 版本号（默认 v0.1.0）
        tools: 平台注册的配套工具清单 (tool_name, description)，内置 Skill 经 registry 传入；
            缺省不渲染「配套工具」章节
        register_method: 注册方式（decorator/upload/form）；``decorator`` 无需审核，
            快速开始不出现审核步骤（V3.0 M3R3 用户验收口径），其余值或缺省均保留审核步骤

    Returns:
        生成的 README.md 文本内容
    """
    needs_review = register_method != "decorator"
    skill_path = Path(skill_dir)
    desc = description or ""

    # 检测是否含 Python 文件
    has_python = any(
        f.endswith(".py")
        for root, _dirs, files in os.walk(skill_path)
        for f in files
    )

    # 生成目录树
    file_tree = _generate_file_tree(skill_path)

    # 生成快速开始指令
    quick_start = _generate_quick_start(tools[0][0] if tools else None, needs_review)

    # 包清单：文件构成统计 + requirements 依赖
    stats = _file_stats(skill_path)
    total_files = sum(stats.values())
    requirements = _parse_requirements(skill_path)

    # 功能描述 = Skill 真实功能描述正文（描述为空时省略该章节）
    content = ""
    if desc:
        content += f"## 功能描述\n\n{desc}\n\n"
    content += """## 环境要求

- 支持 MCP 协议的客户端（Claude Code、Cursor 等均可）——本 Skill 能力经 Platform-MCP MCP Server 统一提供，无需在本地安装 Skill 源码包
"""
    if has_python:
        content += "- Python 3.11.9+（包内含 Python 脚本时）\n"
    if requirements:
        content += "\nPython 依赖（requirements.txt）：\n\n"
        content += "".join(f"- {dep}\n" for dep in requirements)
    if tools:
        content += "\n## 配套工具\n\n"
        content += "".join(f"- `{name}` — {desc}\n" for name, desc in tools)
    if total_files > 0:
        content += f"""
## 文件说明

```
{skill_name}/
{file_tree}```
"""
    content += f"""
## 快速开始

{quick_start}

## 项目信息

| 项目 | 值 |
|------|-----|
| 版本 | v{version} |
| 文件数 | {total_files} |
| 上传时间 | {date.today().isoformat()} |

> 本 README 由 Platform-MCP 模板自动生成（generated_by=template）。
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


_TEXT_EXTS = {".md", ".txt", ".json", ".yml", ".yaml", ".csv"}
_CODE_EXTS = {".py", ".sh", ".sql", ".js", ".ts"}


def _file_stats(skill_path: Path) -> dict[str, int]:
    """统计包内文件构成（文档/脚本/其他），跳过 ``__pycache__`` / ``.git``（与目录树口径一致）。"""
    stats = {"doc": 0, "code": 0, "other": 0}
    for root, dirs, files in os.walk(skill_path):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in _TEXT_EXTS:
                stats["doc"] += 1
            elif ext in _CODE_EXTS:
                stats["code"] += 1
            else:
                stats["other"] += 1
    return stats


def _parse_requirements(skill_path: Path) -> list[str]:
    """解析 requirements.txt 依赖清单（utf-8-sig 兼容 BOM；跳过注释/空行；最多列 20 条）。"""
    req_file = skill_path / "requirements.txt"
    if not req_file.is_file():
        return []
    try:
        lines = req_file.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    deps: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            deps.append(stripped)
        if len(deps) >= 20:
            break
    return deps


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


def _generate_quick_start(tool_hint: str | None = None, needs_review: bool = True) -> str:
    """生成快速开始说明（真实平台流程：广场复制/上传 →〔需审核时〕审核启用 → MCP 接入 → 调用）。

    装饰器注册 Skill（needs_review=False）无需审核，快速开始不出现审核描述（用户验收口径）。
    """
    example = f"（如 `{tool_hint}`）" if tool_hint else ""
    steps = [
        "1. 获取能力：在功能广场对该 Skill「添加至我的」复制到个人库（或经 Web 上传 / MCP 创建），"
        "能力经平台 MCP Server 提供，无需下载或解压源码包",
    ]
    if needs_review:
        steps.append("2. 审核启用：admin 审核通过（状态 ENABLED）后，本 Skill 的工具在 MCP 层自动注册")
    steps.append(
        f"{len(steps) + 1}. 客户端接入：在「个人设置」复制 API Key，按「MCP 接入指南」"
        "在支持 MCP 的客户端（Claude Code 等）配置 mcpServers"
    )
    steps.append(f"{len(steps) + 1}. 调用：重启客户端会话后即可在对话中直接调用本 Skill 的工具{example}")
    return "\n".join(steps)


def generate_readme_en(
    skill_name: str,
    description: str,
    skill_dir: str | Path,
    version: str = "0.1.0",
    tools: list[tuple[str, str]] | None = None,
    register_method: str | None = None,
) -> str:
    """生成英文 README.md 内容（与 :func:`generate_readme` 中文模板结构对齐）。

    V3.0 M2.5 版本化双语存档用（架构 §19.5.6 模板兜底）；M4 挂接 Qwen3-4B 后
    由本地模型生成更自然的英文文案，本模板作为权重缺失/超时兜底。
    ``register_method="decorator"`` 时快速开始无审核步骤（与中文模板同口径）。
    """
    needs_review = register_method != "decorator"
    skill_path = Path(skill_dir)
    desc = description or ""

    has_python = any(
        f.endswith(".py")
        for root, _dirs, files in os.walk(skill_path)
        for f in files
    )

    file_tree = _generate_file_tree(skill_path)
    quick_start = _generate_quick_start_en(tools[0][0] if tools else None, needs_review)

    stats = _file_stats(skill_path)
    total_files = sum(stats.values())
    requirements = _parse_requirements(skill_path)

    content = ""
    if desc:
        content += f"## Description\n\n{desc}\n\n"
    content += """## Requirements

- Any MCP-capable client (Claude Code, Cursor, etc.) — capabilities are served centrally by the Platform-MCP MCP Server; no local Skill package installation is needed
"""
    if has_python:
        content += "- Python 3.11.9+ (when the package contains Python scripts)\n"
    if requirements:
        content += "\nPython dependencies (requirements.txt):\n\n"
        content += "".join(f"- {dep}\n" for dep in requirements)
    if tools:
        content += "\n## Companion Tools\n\n"
        content += "".join(f"- `{name}` — {desc}\n" for name, desc in tools)
    if total_files > 0:
        content += f"""
## Files

```
{skill_name}/
{file_tree}```
"""
    content += f"""
## Quick Start

{quick_start}

## Project Info

| Item | Value |
|------|-------|
| Version | v{version} |
| Files | {total_files} |
| Uploaded | {date.today().isoformat()} |

> This README was auto-generated by the Platform-MCP template (generated_by=template).
"""
    return content


def _generate_quick_start_en(tool_hint: str | None = None, needs_review: bool = True) -> str:
    """生成英文快速开始说明（与中文模板同构的真实平台流程；装饰器注册无审核步骤）。"""
    example = f" (e.g. `{tool_hint}`)" if tool_hint else ""
    steps = [
        "1. Acquire the skill: click \"Add to My\" in the Skill Plaza to copy it into your personal library "
        "(or upload via Web / create via MCP). Capabilities are served by the platform MCP Server — "
        "no package download or extraction is needed",
    ]
    if needs_review:
        steps.append(
            "2. Review & enable: once admin approves (status ENABLED), "
            "the skill's tools are registered on the MCP layer automatically"
        )
    steps.append(
        f"{len(steps) + 1}. Client setup: copy your API Key in \"Profile\" and configure mcpServers "
        "in any MCP-capable client (Claude Code, etc.) per the \"MCP Integration Guide\""
    )
    steps.append(f"{len(steps) + 1}. Invoke: restart the client session and call the skill's tools directly in conversation{example}")
    return "\n".join(steps)