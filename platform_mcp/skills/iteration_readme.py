"""README 迭代段落服务（设计定稿⑥，2026-09-10）

所有 README 末尾追加「版本迭代记录」段落，以 ``<!-- PMCP_ITERATION_SECTION -->`` 标记：

- 广场 README = 权威链：每个归档版本一条（条目内容 = 新版 vs 老版快照 ``file_manifest``
  实际文件 diff），每次发布整体重生成（幂等替换标记及其后全部内容）；类型 publish
  （过审发布）/ merge（合并发布，经 ``pmcp_plaza_merge`` PUBLISHED 记录匹配）；回滚不新建
  版本行，以段落尾「当前生效版本 ≠ 最新归档版」呈现。
- 个人 Skill（origin=ORIGINAL）README = 自身 ``pmcp_skill_version`` 版本史参考表；
  origin=PLAZA 副本采纳迭代时快照恢复链路天然继承广场 README（含本段落）。

事务边界：render_* 仅读库；refresh/backfill 直接落盘（无 DB 写）。README 段落写盘失败
不阻断发布主流程（内部捕获 + 告警，段落缺失不影响内容分发与 MCP 可用性）。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillVersion

#: 迭代段落标记（append_or_refresh_section 以其为界幂等替换）
ITERATION_SECTION_MARKER = "<!-- PMCP_ITERATION_SECTION -->"

#: diff 样例文件名展示上限（表格单行口径）
_DIFF_LIST_CAP = 5


def append_or_refresh_section(readme_text: str | None, section: str) -> str:
    """幂等替换/追加迭代段落：已含标记则以标记为界替换其后内容，否则末尾追加。"""
    text = (readme_text or "").rstrip()
    if ITERATION_SECTION_MARKER in text:
        head = text.split(ITERATION_SECTION_MARKER, 1)[0].rstrip()
        return f"{head}\n\n{section}" if head else section
    return f"{text}\n\n{section}" if text else section


def _manifest_diff(old: list[dict] | None, new: list[dict] | None) -> dict:
    """两版 file_manifest 的 diff（按 sha256 对比，返回 added/removed/changed 路径清单）。"""
    old_map = {f["path"]: f.get("sha256") for f in (old or [])}
    new_map = {f["path"]: f.get("sha256") for f in (new or [])}
    return {
        "added": sorted(p for p in new_map if p not in old_map),
        "removed": sorted(p for p in old_map if p not in new_map),
        "changed": sorted(p for p in new_map if p in old_map and new_map[p] != old_map[p]),
    }


def _diff_cell(diff: dict) -> str:
    """diff 摘要单元格：计数 + 截断样例文件名。"""
    counts = f"新增 {len(diff['added'])} / 修改 {len(diff['changed'])} / 删除 {len(diff['removed'])}"
    names = (diff["added"] + diff["changed"] + diff["removed"])[:_DIFF_LIST_CAP]
    return f"{counts}（{'; '.join(names)}）" if names else counts


def _date_of(value: object) -> str:
    inserted = getattr(value, "inserted_at", None)
    return str(inserted.date().isoformat()) if inserted else "-"


async def render_plaza_iteration_section(db: AsyncSession, plaza_id: int, current_version: str | None) -> str:
    """渲染广场 README 迭代段落（权威链：每归档版一条 diff + 当前生效版本行）。

    类型判定：``pmcp_plaza_merge`` 存在 (plaza_id, new_version=version, status=PUBLISHED)
    记录 → 合并，否则 发布；回滚无新版本行，经尾行「当前生效版本」呈现。
    """
    from platform_mcp.skills.models import PmcpPlazaMerge

    versions = (
        await db.execute(
            select(PmcpPlazaVersion)
            .where(PmcpPlazaVersion.plaza_id == plaza_id)
            .order_by(PmcpPlazaVersion.id.asc())
        )
    ).scalars().all()
    merged = set(
        (await db.execute(
            select(PmcpPlazaMerge.new_version).where(
                PmcpPlazaMerge.plaza_id == plaza_id,
                PmcpPlazaMerge.status == "PUBLISHED",
                PmcpPlazaMerge.new_version.is_not(None),
            )
        )).scalars().all()
    )
    lines = [
        ITERATION_SECTION_MARKER,
        "## 版本迭代记录",
        "",
        "| 版本 | 类型 | 来源版本 | 提交人 | 日期 | 文件变更（vs 上一归档版） |",
        "|------|------|----------|--------|------|------|",
    ]
    prev_manifest: list[dict] | None = None
    for v in versions:
        entry_type = "合并" if v.version in merged else "发布"
        lines.append(
            f"| {v.version} | {entry_type} | {v.source_version or '-'} "
            f"| {v.inserted_by or '-'} | {_date_of(v)} | {_diff_cell(_manifest_diff(prev_manifest, v.file_manifest))} |"
        )
        prev_manifest = v.file_manifest
    rolled_back = bool(versions and current_version and current_version != versions[-1].version)
    lines += [
        "",
        f"- 当前生效版本：**{current_version or '-'}**"
        + ("（回滚生效，非最新归档版）" if rolled_back else ""),
    ]
    return "\n".join(lines)


async def render_personal_iteration_section(db: AsyncSession, skill_id: int) -> str:
    """个人 Skill（origin=ORIGINAL）README 迭代段落：自身 pmcp_skill_version 版本史参考表。"""
    rows = (
        await db.execute(
            select(PmcpSkillVersion)
            .where(PmcpSkillVersion.skill_id == skill_id)
            .order_by(PmcpSkillVersion.id.asc())
        )
    ).scalars().all()
    lines = [
        ITERATION_SECTION_MARKER,
        "## 版本迭代记录（个人存档参考）",
        "",
        "| 版本 | 日期 | 产物来源 |",
        "|------|------|----------|",
    ]
    for r in rows:
        lines.append(f"| {r.version} | {_date_of(r)} | {r.generated_by or '-'} |")
    return "\n".join(lines)


async def refresh_plaza_readme_iteration(db: AsyncSession, plaza) -> bool:
    """重生成广场包内 README.md 的迭代段落（发布/合并/回滚后调用）。

    广场源目录无 README 时以仅含段落的全文创建；无源目录（元数据型）返回 False。
    写盘失败不抛出（告警 + False）——README 段落缺失不影响发布结果与内容分发。
    """
    root_text = str(plaza.source_path or "").strip()
    if not root_text or not Path(root_text).is_dir():
        return False
    try:
        section = await render_plaza_iteration_section(db, plaza.id, plaza.version)
        readme = Path(root_text) / "README.md"
        original = readme.read_text(encoding="utf-8") if readme.exists() else ""
        readme.write_text(append_or_refresh_section(original, section) + "\n", encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001 - README 段落失败不阻断发布主流程
        logger.warning("refresh plaza README iteration failed: plaza_id={} err={}", plaza.id, exc)
        return False


async def backfill_readme_iterations(db: AsyncSession) -> dict:
    """启动幂等补历史（设计⑥）：广场包与个人 origin=ORIGINAL 包 README 缺迭代段落时补齐。

    已含 marker 的跳过（只补不改：历史包内容与归档链非强同源，不重生成既有段落）。
    逐条隔离异常（单条失败不阻断启动与其余条目）。返回 ``{"plaza": n, "personal": n}``。
    """
    from platform_mcp.mcp_server.models import PmcpSkill
    from platform_mcp.skills.models import PmcpSkillPlaza

    counts = {"plaza": 0, "personal": 0}
    plazas = (await db.execute(select(PmcpSkillPlaza))).scalars().all()
    for plaza in plazas:
        root_text = str(plaza.source_path or "").strip()
        if not root_text or not Path(root_text).is_dir():
            continue
        readme = Path(root_text) / "README.md"
        original = readme.read_text(encoding="utf-8") if readme.exists() else ""
        if ITERATION_SECTION_MARKER in original:
            continue
        try:
            section = await render_plaza_iteration_section(db, plaza.id, plaza.version)
            readme.write_text(append_or_refresh_section(original, section) + "\n", encoding="utf-8")
            counts["plaza"] += 1
        except Exception as exc:  # noqa: BLE001 - 补历史逐条隔离
            logger.warning("backfill plaza README iteration failed: plaza_id={} err={}", plaza.id, exc)

    skills = (
        await db.execute(select(PmcpSkill).where(PmcpSkill.origin == "ORIGINAL"))
    ).scalars().all()
    for s in skills:
        root_text = str(s.source_path or "").strip()
        if not root_text or not Path(root_text).is_dir():
            continue
        readme = Path(root_text) / "README.md"
        if not readme.exists():
            continue
        original = readme.read_text(encoding="utf-8")
        if ITERATION_SECTION_MARKER in original:
            continue
        try:
            section = await render_personal_iteration_section(db, s.id)
            readme.write_text(append_or_refresh_section(original, section) + "\n", encoding="utf-8")
            counts["personal"] += 1
        except Exception as exc:  # noqa: BLE001 - 补历史逐条隔离
            logger.warning("backfill personal README iteration failed: skill_id={} err={}", s.id, exc)
    return counts
