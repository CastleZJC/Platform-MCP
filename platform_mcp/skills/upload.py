"""Skill 包上传服务 — 解压、审计、脱敏、README 生成、存储写入"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import py7zr
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.config import get_settings
from platform_mcp.skills.audit.engine import audit_skill_package
from platform_mcp.skills.audit.models import AuditResult, Severity
from platform_mcp.skills.audit.sanitizer import check_sanitization, sanitize_skill_name
from platform_mcp.skills.readme.generator import generate_readme, should_generate_readme, write_readme


@dataclass
class SkillUploadResult:
    """上传流程结果"""
    skill_name: str
    skill_code: str
    description: str
    version: str
    audit_result: AuditResult
    sanitization_passed: bool
    readme_generated: bool
    source_path: str
    source_checksum: str
    source_format: str


def _extract_package(file_path: Path, extract_dir: Path, fmt: str) -> Path:
    """解压 Skill 包，返回包根目录（含 SKILL.md 的目录）。

    支持 .zip 和 .7z 格式。如果压缩包内第一层是目录且含 SKILL.md，
    则返回该目录；否则将整个解压内容视为包根目录。
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "zip":
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(extract_dir)
    elif fmt == "7z":
        with py7zr.SevenZipFile(str(file_path), mode="r") as sz:
            sz.extractall(path=str(extract_dir))
    else:
        raise ValueError(f"不支持的包格式: {fmt}")

    # 查找包含 SKILL.md 的目录作为包根
    for root, _dirs, files in os.walk(extract_dir):
        if any(f.upper() == "SKILL.MD" for f in files):
            return Path(root)

    # 没有 SKILL.md，使用解压根目录
    return extract_dir


def _parse_skill_md(skill_dir: Path) -> tuple[str, str, str]:
    """解析 SKILL.md frontmatter，返回 (name, description, version)。

    version 默认 "0.1.0"。
    """
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        # SKILL.md 不区分大小写查找
        for f in skill_dir.iterdir():
            if f.is_file() and f.name.upper() == "SKILL.MD":
                skill_md_path = f
                break
        else:
            return "", "", "0.1.0"

    content = skill_md_path.read_text(encoding="utf-8")
    name = ""
    description = ""
    version = "0.1.0"

    # 简易 YAML frontmatter 解析
    if content.strip().startswith("---"):
        parts = content.strip().split("---", 2)
        if len(parts) >= 3:
            try:
                import yaml
                frontmatter = yaml.safe_load(parts[1])
                if isinstance(frontmatter, dict):
                    name = frontmatter.get("name", "")
                    description = frontmatter.get("description", "")
                    version = frontmatter.get("version", "0.1.0")
            except Exception:
                pass

    return name, description, version


def _compute_checksum(file_path: Path) -> str:
    """计算文件 SHA-256 校验和"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _detect_format(filename: str) -> str:
    """从文件名推断包格式"""
    lower = filename.lower()
    if lower.endswith(".7z"):
        return "7z"
    if lower.endswith(".zip"):
        return "zip"
    raise ValueError(f"不支持的文件格式，仅支持 .zip 和 .7z: {filename}")


def _store_package(extract_dir: Path, skill_code: str, fmt: str) -> str:
    """将解压后的 Skill 包移动到持久存储目录。

    Returns:
        存储路径（相对路径）
    """
    settings = get_settings()
    store_dir = Path(settings.skill.upload_dir) / skill_code
    store_dir.mkdir(parents=True, exist_ok=True)

    # 如果目标目录已存在内容，先清除
    if store_dir.exists() and any(store_dir.iterdir()):
        shutil.rmtree(store_dir)
        store_dir.mkdir(parents=True, exist_ok=True)

    # 复制整个解压目录内容到存储路径
    for item in extract_dir.iterdir():
        if item.is_dir() and item.name in ("__pycache__", ".git"):
            continue
        dest = store_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    return str(store_dir)


async def process_skill_upload(
    file_path: Path,
    original_filename: str,
    db: AsyncSession,
    operator: str,
) -> SkillUploadResult:
    """Skill 包上传全流程：解压 → 解析 → 审计 → 脱敏 → README → 存储 → 写库。

    Args:
        file_path: 上传文件临时路径
        original_filename: 原始文件名（用于推断格式）
        db: 数据库会话
        operator: 操作人

    Returns:
        SkillUploadResult 上传结果
    """
    from platform_mcp.mcp_server.models import PmcpSkill
    from platform_mcp.skills.audit.models import PmcpSkillAuditReport

    # 1. 检测格式
    fmt = _detect_format(original_filename)

    # 2. 计算校验和
    checksum = _compute_checksum(file_path)

    # 3. 解压到临时目录
    temp_dir = tempfile.mkdtemp(prefix="skill_upload_")
    try:
        extract_dir = Path(temp_dir)
        skill_root = _extract_package(file_path, extract_dir, fmt)

        # 4. 解析 SKILL.md
        raw_name, description, version = _parse_skill_md(skill_root)
        if not raw_name:
            raise ValueError("SKILL.md 缺少 name 字段，无法注册 Skill")

        # 5. 脱敏：清理 Skill 名称
        skill_name, was_sanitized = sanitize_skill_name(raw_name)
        skill_code = skill_name.replace(" ", "-").lower()

        # 6. 执行 14 规则审计
        audit_result = audit_skill_package(skill_root, skill_name)

        # 7. 执行内部引用脱敏检查
        sanitization_results = check_sanitization(skill_root, skill_name)
        sanitization_passed = all(r.passed for r in sanitization_results)
        # 将脱敏违规合并到审计结果中
        for r in sanitization_results:
            if not r.passed:
                audit_result.results.append(r)

        # 重新计算统计
        audit_result.compute_counts()

        # 8. 如果缺少 README.md，自动生成
        readme_generated = False
        if should_generate_readme(skill_root):
            readme_content = generate_readme(skill_name, description, skill_root, version)
            write_readme(skill_root, readme_content)
            readme_generated = True

        # 9. 存储包到持久目录
        source_path = _store_package(skill_root, skill_code, fmt)

        # 10. 写入数据库
        # 确定 audit_status
        if audit_result.critical_count > 0:
            audit_status = "failed"
        elif audit_result.warning_count > 0:
            audit_status = "warning"
        else:
            audit_status = "passed"

        skill_record = PmcpSkill(
            skill_code=skill_code,
            skill_name=skill_name,
            description=description,
            status=2,  # PENDING_REVIEW
            register_method="upload",
            tool_count=0,
            source_path=source_path,
            source_checksum=checksum,
            source_format=fmt,
            version=version,
            audit_status=audit_status,
            audit_result=audit_result.to_audit_summary(),
            readme_generated=readme_generated,
            inserted_by=operator,
        )
        db.add(skill_record)
        await db.flush()

        # 写入审计报告明细
        for r in audit_result.results:
            if not r.passed:
                report = PmcpSkillAuditReport(
                    skill_id=skill_record.id,
                    auditor="system",
                    rule_id=r.rule_id,
                    severity=r.severity.value,
                    file_path=r.file_path,
                    line_number=r.line_number,
                    description=r.description,
                    suggestion=r.suggestion,
                )
                db.add(report)

        await db.flush()

        logger.info(
            "Skill uploaded: code={}, audit_status={}, critical={}, warning={}, suggestion={}",
            skill_code, audit_status,
            audit_result.critical_count, audit_result.warning_count, audit_result.suggestion_count,
        )

        return SkillUploadResult(
            skill_name=skill_name,
            skill_code=skill_code,
            description=description,
            version=version,
            audit_result=audit_result,
            sanitization_passed=sanitization_passed,
            readme_generated=readme_generated,
            source_path=source_path,
            source_checksum=checksum,
            source_format=fmt,
        )
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)