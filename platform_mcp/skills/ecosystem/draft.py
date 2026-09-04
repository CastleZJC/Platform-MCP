"""MCP 双通道 Skill 草稿内容处理（V3.0 M2.4，架构 §19.5.3 / 计划 M2.4、F-29、F-36）

CC 经 MCP ``create_skill_draft`` / ``update_my_skill`` 传入 SKILL.md 文本内容，平台侧：

- 落盘到 ``skill.upload_dir/<skill_code>``（与 Web 上传同一存储布局，F-29「广场副本不受
  未审核更新影响」由 plaza 独立表天然成立）；
- 重放 14 条审计规则 + 脱敏校验（§19.5.3「合规审计为第一道审核」/ F-36 外部模型产物重放校验基线）；
- 缺 README 时模板兜底生成，并产出中英双语 README（M2.5 版本化存档，架构 §19.5.6 模板兜底；
  M4 挂本地生成模型后切换 model 产物）。

与 Web 上传（:mod:`platform_mcp.skills.upload`）共享审计/脱敏/README/版本化基础设施，差异仅在
输入形态（内容字符串 vs zip/7z 包）与初始状态（DRAFT vs PENDING_REVIEW）。广场相似度扫描见
:mod:`platform_mcp.skills.plaza`（中性领域模块，Web/MCP 双链路共享）。
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from platform_mcp.config import get_settings
from platform_mcp.skills.audit.engine import audit_skill_package
from platform_mcp.skills.audit.models import AuditResult
from platform_mcp.skills.audit.sanitizer import check_sanitization
from platform_mcp.skills.readme.generator import generate_readme, should_generate_readme, write_readme
from platform_mcp.skills.versioning import generate_bilingual_readme


@dataclass
class DraftBuildResult:
    """草稿内容落盘 + 审计重放结果（供 create/update 写库、版本化存档与 MCP 响应格式化）。"""

    source_path: str
    source_checksum: str
    audit_result: AuditResult
    audit_status: str  # passed / warning / failed
    readme_generated: bool
    readme_zh: str = ""  # 中文 README（M2.5 版本化存档）
    readme_en: str = ""  # 英文 README（模板兜底，M4 切本地模型）


def _store_draft(extract_dir: Path, skill_code: str) -> str:
    """将草稿内容目录复制到持久存储 ``skill.upload_dir/<skill_code>``（与 Web 上传同布局）。

    目标目录已存在内容时先清除（覆盖式更新，F-29：更新仅影响个人库草稿，广场副本独立不受影响）。
    """
    settings = get_settings()
    store_dir = Path(settings.skill.upload_dir) / skill_code
    if store_dir.exists() and any(store_dir.iterdir()):
        shutil.rmtree(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    for item in extract_dir.iterdir():
        if item.is_dir() and item.name in ("__pycache__", ".git"):
            continue
        dest = store_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    return str(store_dir)


def _content_checksum(skill_md: str, readme: str | None) -> str:
    """草稿内容 SHA-256（Web 上传对 zip 包取校验和；MCP 通道对文本内容取，供版本对账）。"""
    sha256 = hashlib.sha256()
    sha256.update(skill_md.encode("utf-8"))
    if readme:
        sha256.update(b"\x00README\x00")
        sha256.update(readme.encode("utf-8"))
    return sha256.hexdigest()


def _derive_audit_status(audit_result: AuditResult) -> str:
    """审计结论 → ``audit_status``（与 :func:`platform_mcp.skills.upload.process_skill_upload` 同口径）。"""
    if audit_result.critical_count > 0:
        return "failed"
    if audit_result.warning_count > 0:
        return "warning"
    return "passed"


def build_draft_content(
    *,
    skill_code: str,
    skill_name: str,
    description: str | None,
    skill_md: str,
    version: str,
    readme: str | None = None,
) -> DraftBuildResult:
    """把 CC 传入的 SKILL.md（+ 可选 README）内容落盘、重放审计、模板兜底 README，返回存档结果。

    流程：写临时目录 → 14 条审计规则 + 脱敏校验（重放）→ 缺 README 则模板生成 → 复制到持久存储。
    审计命中 🔴 不阻断草稿创建（草稿为工作态，CC 可据返回的违规清单经 ``update_my_skill`` 迭代修复）；
    硬门禁在 admin 广场审核环节（§19.5.3）。
    """
    temp_dir = tempfile.mkdtemp(prefix="skill_draft_")
    try:
        root = Path(temp_dir)
        (root / "SKILL.md").write_text(skill_md, encoding="utf-8")

        readme_generated = False
        if readme:
            (root / "README.md").write_text(readme, encoding="utf-8")
        elif should_generate_readme(root):
            write_readme(root, generate_readme(skill_name, description or "", root, version))
            readme_generated = True

        audit_result = audit_skill_package(root, skill_name)
        for r in check_sanitization(root, skill_name):
            if not r.passed:
                audit_result.results.append(r)
        audit_result.compute_counts()

        source_path = _store_draft(root, skill_code)
        checksum = _content_checksum(skill_md, readme)
        readme_zh, readme_en = generate_bilingual_readme(skill_name, description, root, version)
        return DraftBuildResult(
            source_path=source_path,
            source_checksum=checksum,
            audit_result=audit_result,
            audit_status=_derive_audit_status(audit_result),
            readme_generated=readme_generated,
            readme_zh=readme_zh,
            readme_en=readme_en,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
