"""Skill README 自动生成器单元测试"""

from pathlib import Path

import pytest

from platform_mcp.skills.readme.generator import (
    _generate_file_tree,
    _generate_quick_start,
    _generate_quick_start_en,
    generate_readme,
    generate_readme_en,
    should_generate_readme,
    write_readme,
)


# ==================== generate_readme 测试 ====================

class TestGenerateReadme:
    def test_basic_generation(self, tmp_path):
        """基础场景：纯 Skill 包生成 README"""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test\ndescription: Test\n---\n", encoding="utf-8")
        (skill_dir / "main.py").write_text("# clean", encoding="utf-8")

        content = generate_readme("test-skill", "A test skill", skill_dir)

        assert "## 功能描述" in content
        assert "A test skill" in content
        assert "## 环境要求" in content
        assert "Claude Code" in content
        assert "Python 3.11.9+" in content
        assert "## 文件说明" in content
        assert "## 快速开始" in content
        assert "## 项目信息" in content
        assert "v0.1.0" in content

    def test_python_detection(self, tmp_path):
        """含 .py 文件时应提示 Python 要求"""
        skill_dir = tmp_path / "py-skill"
        skill_dir.mkdir()
        (skill_dir / "main.py").write_text("x = 1", encoding="utf-8")

        content = generate_readme("py-skill", "Python skill", skill_dir)
        assert "Python 3.11.9+" in content

    def test_no_python_no_python_line(self, tmp_path):
        """不含 .py 文件时不应包含 Python 提示"""
        skill_dir = tmp_path / "md-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: md\ndescription: MD only\n---\n", encoding="utf-8")
        (skill_dir / "guide.md").write_text("# guide", encoding="utf-8")

        content = generate_readme("md-skill", "MD-only skill", skill_dir)
        assert "Python 3.11.9+" not in content

    def test_custom_version(self, tmp_path):
        """自定义版本号"""
        skill_dir = tmp_path / "v-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: v\ndescription: V\n---\n", encoding="utf-8")

        content = generate_readme("v-skill", "versioned skill", skill_dir, version="1.2.3")
        assert "v1.2.3" in content

    def test_file_tree_includes_skill_files(self, tmp_path):
        """README 文件树应包含 Skill 包内文件"""
        skill_dir = tmp_path / "tree-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: tree\ndescription: T\n---\n", encoding="utf-8")
        (skill_dir / "README.md").write_text("# existing", encoding="utf-8")
        (skill_dir / "main.py").write_text("x = 1", encoding="utf-8")
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "doc.md").write_text("doc", encoding="utf-8")

        content = generate_readme("tree-skill", "tree test", skill_dir)
        assert "SKILL.md" in content
        assert "main.py" in content
        assert "references/" in content

    def test_excludes_pycache_and_git(self, tmp_path):
        """目录树应跳过 __pycache__ 与 .git"""
        skill_dir = tmp_path / "clean-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: c\ndescription: C\n---\n", encoding="utf-8")
        (skill_dir / "__pycache__").mkdir()
        (skill_dir / "__pycache__" / "main.cpython-311.pyc").write_text("bytecode", encoding="utf-8")
        (skill_dir / ".git").mkdir()
        (skill_dir / ".git" / "config").write_text("git-config", encoding="utf-8")
        (skill_dir / "main.py").write_text("x = 1", encoding="utf-8")

        content = generate_readme("clean-skill", "clean test", skill_dir)
        assert "__pycache__" not in content
        assert ".git" not in content


# ==================== should_generate_readme 测试 ====================

class TestShouldGenerateReadme:
    def test_no_readme_returns_true(self, tmp_path):
        """无 README.md 应返回 True"""
        skill_dir = tmp_path / "no-readme"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: n\ndescription: N\n---\n", encoding="utf-8")
        assert should_generate_readme(skill_dir) is True

    def test_has_readme_returns_false(self, tmp_path):
        """已有 README.md 应返回 False"""
        skill_dir = tmp_path / "has-readme"
        skill_dir.mkdir()
        (skill_dir / "README.md").write_text("# existing", encoding="utf-8")
        assert should_generate_readme(skill_dir) is False


# ==================== write_readme 测试 ====================

class TestWriteReadme:
    def test_write_creates_file(self, tmp_path):
        """write_readme 应创建 README.md 文件"""
        skill_dir = tmp_path / "write-skill"
        skill_dir.mkdir()
        content = "# generated\nHello"

        write_readme(skill_dir, content)

        readme_path = Path(skill_dir) / "README.md"
        assert readme_path.exists()
        assert readme_path.read_text(encoding="utf-8") == content

    def test_write_overwrites_existing(self, tmp_path):
        """write_readme 应覆盖已存在的 README.md"""
        skill_dir = tmp_path / "overwrite-skill"
        skill_dir.mkdir()
        (skill_dir / "README.md").write_text("old", encoding="utf-8")

        write_readme(skill_dir, "new content")
        assert (Path(skill_dir) / "README.md").read_text(encoding="utf-8") == "new content"


# ==================== _generate_file_tree 测试 ====================

class TestGenerateFileTree:
    def test_empty_dir(self, tmp_path):
        """空目录树应返回空内容"""
        empty = tmp_path / "empty"
        empty.mkdir()
        tree = _generate_file_tree(empty)
        assert tree.strip() == ""

    def test_only_files(self, tmp_path):
        """只有文件的目录树"""
        d = tmp_path / "files"
        d.mkdir()
        (d / "a.py").write_text("a", encoding="utf-8")
        (d / "b.md").write_text("b", encoding="utf-8")
        tree = _generate_file_tree(d)
        assert "a.py" in tree
        assert "b.md" in tree
        assert "├──" in tree or "└──" in tree

    def test_nested_dirs(self, tmp_path):
        """嵌套目录树"""
        d = tmp_path / "nested"
        d.mkdir()
        (d / "sub").mkdir()
        (d / "sub" / "inner.py").write_text("x", encoding="utf-8")
        (d / "main.py").write_text("y", encoding="utf-8")
        tree = _generate_file_tree(d)
        assert "sub/" in tree
        assert "inner.py" in tree
        assert "main.py" in tree


# ==================== _generate_quick_start 测试 ====================

class TestGenerateQuickStart:
    def test_quick_start_real_platform_flow(self):
        """快速开始为真实平台流程：无"解压/复制到本地 skills 目录"虚构步骤"""
        qs = _generate_quick_start("execute_sql_text")
        assert "添加至我的" in qs
        assert "MCP 接入指南" in qs
        assert "无需下载或解压源码包" in qs
        assert "~/.claude/skills/" not in qs
        assert "`execute_sql_text`" in qs

    def test_quick_start_format(self):
        """快速开始格式校验"""
        qs = _generate_quick_start(None)
        assert "1." in qs
        assert "2." in qs

    def test_quick_start_decorated_skill_no_review(self):
        """装饰器注册 Skill 无需审核：快速开始 3 步、无审核描述（用户验收口径）"""
        qs = _generate_quick_start("execute_sql_text", needs_review=False)
        assert "审核" not in qs
        assert "1." in qs and "2." in qs and "3." in qs
        assert "4." not in qs

    def test_quick_start_en_decorated_skill_no_review(self):
        qs = _generate_quick_start_en("execute_sql_text", needs_review=False)
        assert "Review" not in qs
        assert "4." not in qs


# ==================== 增强段落测试（V3.0 反馈：README 过于简单）====================


class TestReadmeEnrichedSections:
    """功能描述（=描述正文，无 H1 标题行）/ Python 依赖 / 文件数 / 空包口径 / 模板署名 / 英文镜像"""

    def test_功能描述为描述正文_无标题行与样板段(self, tmp_path):
        skill_dir = tmp_path / "desc-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: S\n---\n", encoding="utf-8")

        content = generate_readme("desc-skill", "SQL 执行能力：文本/文件执行、风险校验", skill_dir)
        assert "## 功能描述" in content
        assert "SQL 执行能力：文本/文件执行、风险校验" in content
        assert "# desc-skill" not in content  # 无 H1 标题行
        assert "## 功能概述" not in content
        assert "暂未附源码包" not in content  # 空包样板段移除

    def test_描述为空省略功能描述章节(self, tmp_path):
        skill_dir = tmp_path / "nodesc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: n\ndescription: N\n---\n", encoding="utf-8")

        content = generate_readme("nodesc", "", skill_dir)
        assert "## 功能描述" not in content
        assert "## 环境要求" in content

    def test_requirements列出依赖并跳过注释(self, tmp_path):
        skill_dir = tmp_path / "req-skill"
        skill_dir.mkdir()
        (skill_dir / "main.py").write_text("x=1", encoding="utf-8")
        (skill_dir / "requirements.txt").write_text(
            "# comment\nasyncssh==2.17.0\n\nsqlparse>=0.5\n", encoding="utf-8"
        )

        content = generate_readme("req-skill", "d", skill_dir)
        assert "Python 依赖（requirements.txt）" in content
        assert "- asyncssh==2.17.0" in content
        assert "- sqlparse>=0.5" in content
        assert "# comment" not in content

    def test_无requirements不显示依赖段(self, tmp_path):
        skill_dir = tmp_path / "noreq"
        skill_dir.mkdir()
        (skill_dir / "main.py").write_text("x=1", encoding="utf-8")

        content = generate_readme("noreq", "d", skill_dir)
        assert "Python 依赖" not in content

    def test_requirements兼容BOM(self, tmp_path):
        """requirements.txt 带 UTF-8 BOM 时仍可解析（utf-8-sig）"""
        skill_dir = tmp_path / "bom-skill"
        skill_dir.mkdir()
        (skill_dir / "main.py").write_text("x=1", encoding="utf-8")
        (skill_dir / "requirements.txt").write_text("﻿httpx==0.27.2\n", encoding="utf-8")

        content = generate_readme("bom-skill", "d", skill_dir)
        assert "- httpx==0.27.2" in content

    def test_空包无样板段(self, tmp_path):
        """空包（内置/MCP 创建）不再渲染任何「经 MCP 通道创建」样板口径"""
        skill_dir = tmp_path / "meta-only"
        skill_dir.mkdir()

        content = generate_readme("meta-only", "d", skill_dir)
        assert "暂未附源码包" not in content
        assert "本 Skill 包共" not in content
        assert "## 快速开始" in content

    def test_项目信息含文件数(self, tmp_path):
        skill_dir = tmp_path / "cnt"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: c\ndescription: C\n---\n", encoding="utf-8")
        (skill_dir / "main.py").write_text("x=1", encoding="utf-8")

        content = generate_readme("cnt", "d", skill_dir)
        assert "| 文件数 | 2 |" in content

    def test_模板署名footer(self, tmp_path):
        skill_dir = tmp_path / "footer"
        skill_dir.mkdir()

        content = generate_readme("footer", "d", skill_dir)
        assert "generated_by=template" in content

    def test_统计跳过pycache与git(self, tmp_path):
        """文件统计与目录树同口径：跳过 __pycache__ / .git"""
        skill_dir = tmp_path / "prune"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: p\ndescription: P\n---\n", encoding="utf-8")
        (skill_dir / "__pycache__").mkdir()
        (skill_dir / "__pycache__" / "m.cpython-311.pyc").write_text("b", encoding="utf-8")

        content = generate_readme("prune", "d", skill_dir)
        assert "| 文件数 | 1 |" in content

    def test_英文版含Overview与依赖(self, tmp_path):
        skill_dir = tmp_path / "en-skill"
        skill_dir.mkdir()
        (skill_dir / "main.py").write_text("x=1", encoding="utf-8")
        (skill_dir / "requirements.txt").write_text("httpx==0.27.2\n", encoding="utf-8")

        content = generate_readme_en("en-skill", "d", skill_dir)
        assert "## Description" in content
        assert "Python dependencies (requirements.txt)" in content
        assert "- httpx==0.27.2" in content
        assert "generated_by=template" in content

    def test_英文空包口径(self, tmp_path):
        skill_dir = tmp_path / "en-empty"
        skill_dir.mkdir()

        content = generate_readme_en("en-empty", "d", skill_dir)
        assert "without a source package" not in content
        assert "## Quick Start" in content

    def test_英文快速开始真实流程(self):
        qs = _generate_quick_start_en("execute_sql_text")
        assert "Add to My" in qs
        assert "MCP Integration Guide" in qs
        assert "~/.claude/skills/" not in qs
        assert "`execute_sql_text`" in qs


# ==================== 平台交付口径测试（V3.0 反馈批次2：环境要求/配套工具/文件树）====================


class TestReadmePlatformFlowSections:
    """环境要求 MCP 客户端通用化 / 配套工具清单 / 空包不渲染空文件树"""

    def test_环境要求为通用MCP客户端(self, tmp_path):
        """标准 MCP：任意可配置 mcpServers 的客户端均可，不只 Claude Code"""
        skill_dir = tmp_path / "env"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: e\ndescription: E\n---\n", encoding="utf-8")

        content = generate_readme("env", "d", skill_dir)
        assert "支持 MCP 协议的客户端" in content
        assert "Cursor" in content

    def test_配套工具章节渲染工具清单(self, tmp_path):
        skill_dir = tmp_path / "tools"
        skill_dir.mkdir()
        tools = [("execute_sql_text", "执行 SQL 文本"), ("validate_sql", "校验 SQL 风险")]

        content = generate_readme("tools-skill", "d", skill_dir, tools=tools)
        assert "## 配套工具" in content
        assert "`execute_sql_text` — 执行 SQL 文本" in content
        assert "`validate_sql` — 校验 SQL 风险" in content

    def test_英文配套工具章节(self, tmp_path):
        skill_dir = tmp_path / "entools"
        skill_dir.mkdir()
        tools = [("execute_sql_text", "Execute SQL text")]

        content = generate_readme_en("entools", "d", skill_dir, tools=tools)
        assert "## Companion Tools" in content
        assert "`execute_sql_text` — Execute SQL text" in content

    def test_无包不渲染空文件说明(self, tmp_path):
        """空包（内置/MCP 创建）不渲染「文件说明」空树，快速开始仍可用"""
        skill_dir = tmp_path / "nopkg"
        skill_dir.mkdir()

        content = generate_readme("nopkg", "d", skill_dir)
        assert "## 文件说明" not in content
        assert "## 快速开始" in content

    def test_有包仍渲染文件说明(self, tmp_path):
        skill_dir = tmp_path / "pkg"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: p\ndescription: P\n---\n", encoding="utf-8")

        content = generate_readme("pkg", "d", skill_dir)
        assert "## 文件说明" in content

    def test_装饰器注册模板无审核步骤(self, tmp_path):
        """register_method=decorator 快速开始无审核；缺省（upload）保留审核"""
        skill_dir = tmp_path / "deco"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: d\ndescription: D\n---\n", encoding="utf-8")

        zh = generate_readme("deco", "d", skill_dir, register_method="decorator")
        en = generate_readme_en("deco", "d", skill_dir, register_method="decorator")
        assert "审核" not in zh
        assert "Review" not in en
        zh_upload = generate_readme("deco", "d", skill_dir)
        assert "审核启用" in zh_upload