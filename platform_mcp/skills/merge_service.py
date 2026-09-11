"""广场 merge 工作台服务（设计定稿④，2026-09-10，批次3）

admin 在 Web 审核弹窗 / MCP 通道把一个或多个个人 Skill 的内容合并为广场 Skill 的
新版本，支持试用（临时包）与逐文件冲突裁决：

- ``build_merge_version``：以广场基线（指定历史版本 / 源 ``copied_from_plaza_version`` /
  当前快照）为底做**文件级并集**；多源同路径内容不同记入冲突清单（默认主源 = 源列表
  首位，admin 可在 publish 时逐文件改判）；合并树写入临时包
  ``{upload_dir}/_plaza_merge/{plaza_id}/{token}/`` 并预跑 14 条合规审计（摘要入
  ``audit_summary``），落 ``pmcp_plaza_merge`` 行（status=BUILT）。来源不限
  ``origin=PLAZA`` —— 原创 Skill 并入已有广场（场景①）同样支持。
- ``publish_merge_version``：``publish`` = 应用裁决 → 终审重放（🔴 严重命中**阻断**）→
  快照覆盖 ``_plaza/{plaza_id}`` → 版本归档（``source_version``=主源提交人版本）→
  广场字段刷新（description 取主源；code/name 不变）→ 语义向量重建 → README 迭代段落
  重生成 → 持有者批量置迭代态 → skill_review 组通知 → status=PUBLISHED；
  ``discard`` = 删临时包 + status=DISCARDED。

事务边界：``mutate + flush`` 不 commit（与审核服务一致，由 ``get_db`` / MCP
``_session_scope`` 统一提交）；审计经 ``write_audit_log`` 独立 session。
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loguru import logger

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.config import get_settings
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.service import (
    CODE_FORBIDDEN,
    CODE_INVALID_STATE,
    CODE_NOT_FOUND,
    ReviewActor,
    SkillReviewError,
    archive_plaza_version,
    mark_plaza_holders_for_iteration,
)
from platform_mcp.skills.audit.engine import audit_skill_package
from platform_mcp.skills.iteration_readme import refresh_plaza_readme_iteration
from platform_mcp.skills.models import PmcpPlazaMerge, PmcpPlazaVersion, PmcpSkillPlaza
from platform_mcp.skills.plaza import derive_involve_flags, index_plaza_embedding
from platform_mcp.skills.versioning import next_patch_version

# ==================== 磁盘工具 ====================


def _merge_dir(plaza_id: int, token: str) -> Path:
    """合并临时包目录：``{upload_dir}/_plaza_merge/{plaza_id}/{token}``。"""
    return Path(get_settings().skill.upload_dir) / "_plaza_merge" / str(plaza_id) / token


def _plaza_version_dir(plaza_id: int, version: str) -> Path:
    """历史版本快照目录（与 review.service._plaza_version_dir 同口径，基线解析用）。"""
    return Path(get_settings().skill.upload_dir) / "_plaza_versions" / str(plaza_id) / version


def _read_tree(root: Path | str | None) -> dict[str, bytes]:
    """读取目录全部文件为 ``{posix相对路径: bytes}``；目录缺失/为空返回空 dict。

    ``Path("")`` 归一化为 ``Path(".")``（进程 CWD），元数据型空 source_path 若不拦会
    把整个工作目录当包扫入 —— 显式按空树处理。
    """
    text = str(root or "").strip()
    if not text or text in (".", "./"):
        return {}
    base = Path(text)
    if not base.is_dir():
        return {}
    tree: dict[str, bytes] = {}
    for f in sorted(base.rglob("*"), key=lambda p: p.relative_to(base).as_posix()):
        if f.is_file():
            tree[f.relative_to(base).as_posix()] = f.read_bytes()
    return tree


def _tree_checksum(root: Path) -> str:
    """目录树校验和：按排序后 ``相对路径 + 文件 SHA-256`` 级联（合并发布产物口径）。"""
    sha = hashlib.sha256()
    for f in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if f.is_file():
            sha.update(f.relative_to(root).as_posix().encode("utf-8"))
            sha.update(hashlib.sha256(f.read_bytes()).digest())
    return sha.hexdigest()


def _write_tree(dest: Path, tree: dict[str, bytes]) -> None:
    """把 ``{相对路径: bytes}`` 写入目标目录（先清空；拒绝 ``..`` 穿越路径）。"""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel, data in tree.items():
        if ".." in rel.split("/") or rel.startswith("/"):
            raise SkillReviewError(f"非法包内路径：{rel}", code=CODE_INVALID_STATE)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def serialize_merge(row: PmcpPlazaMerge) -> dict:
    """工作台行序列化（Web / MCP 展示与试用引导共用）。"""
    return {
        "merge_token": row.merge_token,
        "plaza_id": row.plaza_id,
        "source_skills": row.source_skills or [],
        "base_version": row.base_version,
        "new_version": row.new_version,
        "conflicts": row.conflicts or [],
        "audit_summary": row.audit_summary,
        "snapshot_path": row.snapshot_path,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.inserted_at.isoformat() if row.inserted_at else None,
    }


# ==================== build：文件级并集 + 冲突清单 ====================


def _resolve_base_dir(
    plaza: PmcpSkillPlaza, sources: list[PmcpSkill], base_version: str | None
) -> tuple[Path, str]:
    """解析合并基线目录与展示标签：显式版本 → 源 copied_from_plaza_version → 当前快照。"""
    if base_version:
        explicit = _plaza_version_dir(plaza.id, base_version)
        if explicit.is_dir():
            return explicit, base_version
        raise SkillReviewError(
            f"基线版本 {base_version} 的快照不存在（_plaza_versions/{plaza.id}/{base_version}）",
            code=CODE_INVALID_STATE,
        )
    if len(sources) == 1 and sources[0].copied_from_plaza_version:
        copied = _plaza_version_dir(plaza.id, sources[0].copied_from_plaza_version)
        if copied.is_dir():
            return copied, sources[0].copied_from_plaza_version or ""
    return Path(str(plaza.source_path or "")), (plaza.version or "") + "（当前）"


def _audit_summary_of(root: Path, skill_name: str) -> dict:
    """14 条合规审计预跑摘要（build 供裁决参考 / publish 为终审依据）。"""
    result = audit_skill_package(root, skill_name)
    result.compute_counts()
    return result.to_audit_summary()


async def build_merge_version(
    db: AsyncSession,
    *,
    plaza_id: int,
    source_skill_ids: list[int],
    actor: ReviewActor,
    base_version: str | None = None,
    target_version: str | None = None,
    comment: str | None = None,
) -> dict:
    """构建合并临时包（仅 admin）。源列表首位 = 主源（冲突默认值 / description 口径）。

    返回 ``serialize_merge`` 结构（含 merge_token、冲突清单、审计摘要），供审核弹窗
    展示与 ``get_skill_file(merge_token=...)`` 试用。
    """
    if not actor.is_admin:
        raise SkillReviewError("仅 admin 可构建合并版本", code=CODE_FORBIDDEN)
    plaza = await db.get(PmcpSkillPlaza, plaza_id)
    if plaza is None:
        raise SkillReviewError("目标广场 Skill 不存在", code=CODE_NOT_FOUND)

    # 源加载与去重（保序）：内置装饰器 Skill 不可作合并源（系统 Skill 不参与用户合并）
    seen: set[int] = set()
    ordered: list[int] = []
    for sid in source_skill_ids or []:
        if sid not in seen:
            seen.add(sid)
            ordered.append(int(sid))
    if not ordered:
        raise SkillReviewError("source_skill_ids 不能为空", code=CODE_INVALID_STATE)
    sources: list[PmcpSkill] = []
    for sid in ordered:
        skill = await db.get(PmcpSkill, sid)
        if skill is None:
            raise SkillReviewError(f"来源 Skill {sid} 不存在", code=CODE_NOT_FOUND)
        if skill.register_method == "decorator":
            raise SkillReviewError(
                f"来源 Skill {skill.skill_code} 为内置装饰器 Skill，不可作合并源", code=CODE_INVALID_STATE
            )
        sources.append(skill)

    base_dir, base_label = _resolve_base_dir(plaza, sources, base_version)
    base_tree = _read_tree(base_dir)
    # 源树（源自身目录缺失按空树参与并集，不阻断——元数据型源仅贡献字段口径）
    source_trees: list[tuple[PmcpSkill, dict[str, bytes]]] = [
        (s, _read_tree(s.source_path)) for s in sources
    ]

    # 文件级并集：base 全量保留 + 源文件按路径覆盖；多源同路径内容不同记冲突（默认主源）
    merged: dict[str, bytes] = dict(base_tree)
    provided: dict[str, list[tuple[PmcpSkill, bytes]]] = {}
    for skill, tree in source_trees:
        for rel, data in tree.items():
            provided.setdefault(rel, []).append((skill, data))
    conflicts: list[dict] = []
    for rel, entries in provided.items():
        distinct = {hashlib.sha256(data).hexdigest() for _, data in entries}
        merged[rel] = entries[0][1]  # 列表首位 = 主源内容（默认裁决）
        if len(distinct) > 1:
            candidates = [
                {
                    "source_skill_id": s.id,
                    "skill_code": s.skill_code,
                    "role": "primary" if i == 0 else "secondary",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
                for i, (s, data) in enumerate(entries)
            ]
            if rel in base_tree:
                candidates.append({
                    "source_skill_id": None,
                    "skill_code": plaza.skill_code,
                    "role": "base",
                    "sha256": hashlib.sha256(base_tree[rel]).hexdigest(),
                    "size": len(base_tree[rel]),
                })
            conflicts.append({
                "path": rel,
                "candidates": candidates,
                "default_source_skill_id": entries[0][0].id,
                "resolution": None,
            })

    token = secrets.token_urlsafe(12)
    temp_dir = _merge_dir(plaza.id, token)
    _write_tree(temp_dir, merged)
    audit_summary = _audit_summary_of(temp_dir, plaza.skill_name)
    new_version = target_version or next_patch_version(plaza.version)

    row = PmcpPlazaMerge(
        merge_token=token,
        plaza_id=plaza.id,
        source_skills=[
            {
                "skill_id": s.id,
                "skill_code": s.skill_code,
                "skill_name": s.skill_name,
                "role": "primary" if i == 0 else "secondary",
                "version": s.version,
                "submitted_by": s.inserted_by,
            }
            for i, s in enumerate(sources)
        ],
        base_version=base_label,
        new_version=new_version,
        conflicts=conflicts or None,
        audit_summary=audit_summary,
        snapshot_path=str(temp_dir),
        status="BUILT",
        created_by=actor.username,
        inserted_by=actor.username,
        updated_by=actor.username,
    )
    db.add(row)
    await db.flush()
    await write_audit_log(
        trace_id=actor.trace_id,
        operator=actor.username,
        resource_type="skill",
        resource_id=str(plaza.id),
        request_summary=(
            f"merge 工作台 build：广场 {plaza.skill_code} ← {len(sources)} 源 "
            f"(token={token}, 冲突 {len(conflicts)})"
        ),
        extra_data={
            "action": "merge_build",
            "merge_token": token,
            "plaza_id": plaza.id,
            "source_skill_ids": ordered,
            "base_version": base_label,
            "new_version": new_version,
            "conflict_count": len(conflicts),
            "comment": comment,
            "audit_passed": audit_summary.get("passed"),
        },
    )
    result = serialize_merge(row)
    result["message_hint"] = (
        "临时包已构建：可用 get_skill_file(merge_token=...) 试用；publish 前可对冲突逐文件改判"
    )
    logger.info(
        "merge build: plaza={} token={} sources={} conflicts={} version={}",
        plaza.id, token, ordered, len(conflicts), new_version,
    )
    return result


# ==================== publish / discard ====================


def _normalize_resolution(value: Any) -> int | str:
    """裁决值归一：``"base"`` 保留基线，其余（int / 数字串）= 来源 skill_id。"""
    text = str(value).strip()
    if text == "base":
        return "base"
    try:
        return int(text)
    except ValueError as exc:
        raise SkillReviewError(
            f"非法裁决值：{value}（须为来源 skill_id 或 'base'）", code=CODE_INVALID_STATE
        ) from exc


async def _require_source(db: AsyncSession, skill_id: int) -> PmcpSkill:
    skill = await db.get(PmcpSkill, skill_id)
    if skill is None:
        raise SkillReviewError(f"来源 Skill {skill_id} 不存在", code=CODE_NOT_FOUND)
    return skill


def _source_ids(row: PmcpPlazaMerge) -> list[int]:
    return [int(s["skill_id"]) for s in (row.source_skills or [])]


def _base_version_for_rebuild(row: PmcpPlazaMerge) -> str | None:
    """publish 阶段重解析基线目录：BUILT 时记录的版本号（去除「（当前）」标签）。"""
    label = row.base_version or ""
    if not label or "（当前）" in label:
        return None
    return label


async def publish_merge_version(
    db: AsyncSession,
    *,
    merge_token: str,
    action: Literal["publish", "discard"],
    actor: ReviewActor,
    resolutions: dict[str, Any] | None = None,
    target_version: str | None = None,
    comment: str | None = None,
) -> dict:
    """发布 / 丢弃合并临时包（仅 admin，仅 BUILT 可操作）。

    ``publish``：应用 ``resolutions``（``{path: skill_id | "base"}``，仅冲突路径可改判）→
    14 条终审重放（🔴 严重命中阻断发布）→ 快照覆盖 + 版本归档 + 广场字段刷新（description
    取主源）→ 向量重建 → README 迭代段落重生成 → 持有者批量置迭代态（设计①）→
    skill_review 组通知 → 行置 PUBLISHED 并清理临时包。
    """
    if not actor.is_admin:
        raise SkillReviewError("仅 admin 可发布合并版本", code=CODE_FORBIDDEN)
    row = (
        await db.execute(select(PmcpPlazaMerge).where(PmcpPlazaMerge.merge_token == merge_token))
    ).scalar_one_or_none()
    if row is None:
        raise SkillReviewError("merge_token 不存在", code=CODE_NOT_FOUND)
    if row.status != "BUILT":
        raise SkillReviewError(f"该合并任务已终结（status={row.status}）", code=CODE_INVALID_STATE)

    temp_dir = Path(row.snapshot_path or "")
    if action == "discard":
        if temp_dir.is_dir():
            shutil.rmtree(temp_dir, ignore_errors=True)
        row.status = "DISCARDED"
        row.updated_by = actor.username
        await db.flush()
        await write_audit_log(
            trace_id=actor.trace_id,
            operator=actor.username,
            resource_type="skill",
            resource_id=str(row.plaza_id),
            request_summary=f"merge 工作台 discard：token={merge_token}",
            extra_data={"action": "merge_discard", "merge_token": merge_token, "plaza_id": row.plaza_id},
        )
        return {"merge_token": merge_token, "status": "DISCARDED"}

    if not temp_dir.is_dir():
        raise SkillReviewError("合并临时包目录缺失（可能已被清理），请重新 build", code=CODE_INVALID_STATE)
    plaza = await db.get(PmcpSkillPlaza, row.plaza_id)
    if plaza is None:
        raise SkillReviewError("目标广场 Skill 不存在", code=CODE_NOT_FOUND)

    # ---- 应用逐文件裁决（仅冲突路径；来源树 / 基线树重读作为候选内容）----
    conflict_by_path = {c["path"]: c for c in (row.conflicts or [])}
    if resolutions:
        unknown = [p for p in resolutions if p not in conflict_by_path]
        if unknown:
            raise SkillReviewError(
                f"裁决路径不在冲突清单中：{unknown}", code=CODE_INVALID_STATE
            )
        source_rows = [await _require_source(db, sid) for sid in _source_ids(row)]
        base_dir, _label = _resolve_base_dir(plaza, source_rows, _base_version_for_rebuild(row))
        base_tree = _read_tree(base_dir)
        for path, value in resolutions.items():
            pick = _normalize_resolution(value)
            conflict = conflict_by_path[path]
            if pick == "base":
                if path not in base_tree:
                    raise SkillReviewError(f"路径 {path} 基线无内容，不能裁决为 base", code=CODE_INVALID_STATE)
                data = base_tree[path]
            else:
                source = next((s for s in source_rows if s.id == pick), None)
                if source is None:
                    raise SkillReviewError(f"来源 Skill {pick} 不在该合并任务的源清单中", code=CODE_INVALID_STATE)
                candidate = next(
                    (c for c in conflict["candidates"] if c.get("source_skill_id") == pick), None
                )
                if candidate is None:
                    raise SkillReviewError(
                        f"路径 {path} 的候选不含来源 Skill {pick}", code=CODE_INVALID_STATE
                    )
                tree = _read_tree(source.source_path)
                picked = tree.get(path)
                if picked is None:
                    raise SkillReviewError(
                        f"来源 Skill {pick} 的包内已无 {path}，无法按该源裁决", code=CODE_INVALID_STATE
                    )
                data = picked
            target = temp_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            conflict["resolution"] = "base" if pick == "base" else pick
        row.conflicts = [conflict_by_path[p] for p in conflict_by_path]  # 重新赋值触发 JSONB 变更追踪

    # ---- 终审重放：🔴 严重命中阻断发布（工作台产物入广场的最后一道口径）----
    audit_summary = _audit_summary_of(temp_dir, plaza.skill_name)
    row.audit_summary = audit_summary
    if int(audit_summary.get("critical_count", 0) or 0) > 0:
        row.updated_by = actor.username
        await db.flush()
        await write_audit_log(
            trace_id=actor.trace_id,
            operator=actor.username,
            resource_type="skill",
            resource_id=str(plaza.id),
            request_summary=f"merge 工作台 publish 被审计阻断：token={merge_token}",
            result_status="failed",
            error_message=f"🔴 严重违规 {audit_summary.get('critical_count')} 条",
            extra_data={"action": "merge_publish_blocked", "merge_token": merge_token, "plaza_id": plaza.id},
        )
        raise SkillReviewError(
            f"终审重放存在 🔴 严重违规 {audit_summary.get('critical_count')} 条，发布被阻断；请修正后重新 build",
            code=CODE_INVALID_STATE,
        )

    # ---- 发布：快照覆盖 + 版本归档 + 字段刷新 + 持有者标记 + 通知 ----
    primary = await _require_source(db, _source_ids(row)[0])
    version = target_version or row.new_version or next_patch_version(plaza.version)
    checksum = _tree_checksum(temp_dir)
    snapshot = snapshot_merge_to_plaza(temp_dir, plaza.id)
    await archive_plaza_version(
        db,
        plaza_id=plaza.id,
        version=version,
        source_path=str(temp_dir),
        checksum=checksum,
        audit_snapshot=audit_summary,
        operator=actor.username,
        source_version=primary.version,
    )
    # 广场字段：code/name 不变（场景①：B 并入 A，A 身份保持）；description 取主源口径
    plaza.description = primary.description
    plaza.version = version
    plaza.iteration_note = comment or plaza.iteration_note
    plaza.involve_flags = derive_involve_flags(audit_summary)
    if snapshot:
        plaza.source_path = snapshot
        plaza.source_checksum = checksum
    plaza.status = "PUBLISHED"
    plaza.updated_by = actor.username
    row.status = "PUBLISHED"
    row.new_version = version
    row.updated_by = actor.username
    await db.flush()
    await index_plaza_embedding(db, plaza.id, plaza.skill_name, plaza.description)
    await refresh_plaza_readme_iteration(db, plaza)
    marked = await mark_plaza_holders_for_iteration(
        db, plaza_id=plaza.id, new_version=version, actor=actor, reason="merge_publish"
    )
    await _notify_merge_publish(actor, plaza, primary, version, comment, marked)
    await write_audit_log(
        trace_id=actor.trace_id,
        operator=actor.username,
        resource_type="skill",
        resource_id=str(plaza.id),
        request_summary=(
            f"merge 工作台 publish：广场 {plaza.skill_code} → v{version} "
            f"(源 {len(_source_ids(row))} 个, 持有者标记 {marked})"
        ),
        extra_data={
            "action": "merge_publish",
            "merge_token": merge_token,
            "plaza_id": plaza.id,
            "version": version,
            "source_version": primary.version,
            "source_skill_ids": _source_ids(row),
            "holders_marked": marked,
            "comment": comment,
        },
    )
    shutil.rmtree(temp_dir, ignore_errors=True)
    result = serialize_merge(row)
    result["holders_marked"] = marked
    logger.info(
        "merge publish: plaza={} version={} token={} marked={}",
        plaza.id, version, merge_token, marked,
    )
    return result


def snapshot_merge_to_plaza(temp_dir: Path, plaza_id: int) -> str:
    """合并临时包快照覆盖 ``_plaza/{plaza_id}``（与 snapshot_plaza_source 同目录语义）。"""
    from platform_mcp.review.service import _plaza_snapshot_dir

    dest = _plaza_snapshot_dir(plaza_id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(temp_dir, dest)
    return str(dest)


async def _notify_merge_publish(
    actor: ReviewActor,
    plaza: PmcpSkillPlaza,
    primary: PmcpSkill,
    version: str,
    comment: str | None,
    marked: int,
) -> None:
    """合并发布通知 skill_review 组（outbox 落库不阻断，与审核服务同口径）。"""
    from platform_mcp.notify.service import dispatch_notification

    await dispatch_notification(
        "skill_review",
        {
            "user": actor.username,
            "resource": plaza.skill_name,
            "action": "合并发布（工作台）",
            "reason": comment or "",
            "iteration_note": comment or "",
            "skill_id": str(primary.id),
            "submitter": primary.inserted_by,
            "version": version,
        },
        source="merge",
        trace_id=actor.trace_id,
        operator=actor.username,
    )


async def list_plaza_versions(db: AsyncSession, plaza_id: int) -> list[dict]:
    """广场版本列表（只读；Web 版本弹窗与回滚（批次4）共用）。"""
    rows = (
        await db.execute(
            select(PmcpPlazaVersion)
            .where(PmcpPlazaVersion.plaza_id == plaza_id)
            .order_by(PmcpPlazaVersion.id.desc())
        )
    ).scalars().all()
    return [
        {
            "plaza_id": r.plaza_id,
            "version": r.version,
            "source_version": r.source_version,
            "snapshot_path": r.snapshot_path,
            "file_count": len(r.file_manifest or []),
            "checksum": r.checksum,
            "audit_passed": (r.audit_snapshot or {}).get("passed"),
            "created_at": r.inserted_at.isoformat() if r.inserted_at else None,
        }
        for r in rows
    ]
