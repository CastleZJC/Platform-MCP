"""Skill README 自动生成器单元测试"""

from pathlib import Path

import pytest

from platform_mcp.skills.readme.generator import (
    _generate_file_tree,
    _generate_quick_start,
    generate_readme,
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

        assert "# test-skill" in content
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
    def test_quick_start_contains_skills_path(self):
        """快速开始应包含 skills 目录路径"""
        qs = _generate_quick_start("my-skill")
        assert "skills" in qs
        assert "~/.claude/skills/" in qs

    def test_quick_start_format(self):
        """快速开始格式校验"""
        qs = _generate_quick_start("test")
        assert "1." in qs
        assert "2." in qs