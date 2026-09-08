"""可复用审核服务（V3.0 M2，架构 §19.5.3 / 计划 M2.3；M4.3 分享迭代内容级）

抽取 Skill 审核域的业务编排，状态转移委托 :mod:`platform_mcp.review.state_machine`
（单一事实来源），本服务负责：

- 权限与归属校验（owner 本人 / admin 审核）；
- 广场副本 upsert（approve 新增入广场 / merge 合并迭代说明 → ``pmcp_skill_plaza``）；
- ``status`` / ``share_status`` / ``plaza_id`` / ``origin`` / ``review_comment`` 联动写入；
- 审计留痕（``resource_type="skill"``，操作明细可区分，F-40）；
- 重复分享二次确认（F-31 ``confirm_reshare``）。

覆盖动作（与 §19.5.3 状态机图一一对应）：
提交分享 / admin 审核（approve 新增入广场 / merge 合并 / reject 拒绝）/ 撤回（停用视同撤回，F-32）/
分享迭代解决（迭代 / 保留，F-30）/ 修改重编辑 / 恢复 / 启停。

M4.3 分享迭代内容级（F-30）：

- **广场内容快照**：approve/merge 时把提审源目录快照到 ``{upload_dir}/_plaza/{plaza_id}``
  （:func:`snapshot_plaza_source`），修复广场副本与个人库共享目录被 ``update_my_skill`` 覆盖的
  污染问题（F-29 广场副本不受未审核更新影响，磁盘层也成立）；
- **merge 内容级同步**：广场副本字段（名称/描述/版本/涉库标记）+ 向量 + 快照刷新（M2.3 仅
  iteration_note → M4 补内容采纳）；
- **resolve iterate 覆盖本地**：广场快照复制回 ``{upload_dir}/{skill_code}`` + 重放 14 条审计
  与脱敏 + 版本化存档（F-28）；``keep`` 不动本地。
- **差异素材查询**（:meth:`build_iteration_diff`）：本地 vs 广场快照 SKILL.md 行级 diff +
  语义相似度 + 双语描述（本地 Qwen3 优先/模板兜底，M4.4 性能提示附带回传）。

设计解耦：三期 KB（M6）可复用同一编排骨架（状态机 + 归属校验 + 共享联动 + 审计）。
事务边界：服务层 ``mutate + flush``，**不 commit**（与 ``process_skill_upload`` 一致，由 ``get_db`` 统一提交）；
审计经 ``write_audit_log`` 独立 session 内部 commit，不受业务事务回滚影响。
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.auth.models import PmcpUser
from platform_mcp.common.exceptions import SkillError
from platform_mcp.config import get_settings
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.review.state_machine import (
    InvalidTransitionError,
    ReviewAction,
    ReviewStatus,
    owner_mcp_usable,
    transition,
    visible_in_personal_library,
)
from platform_mcp.skills.audit.engine import audit_skill_package
from platform_mcp.skills.llm.generation import (
    build_iteration_diff as build_iteration_diff_result,
    build_iteration_diff_material as build_diff_material_impl,
    read_package_skill_md,
)
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillPlaza
from platform_mcp.skills.plaza import derive_involve_flags, index_plaza_embedding
from platform_mcp.skills.versioning import (
    archive_skill_version,
    generate_bilingual_readme,
    generate_bilingual_report,
)

# ==== 错误码（沿用 1000x Skill 域，见 common/exceptions.SkillError 与 api 既有约定）====
CODE_NOT_FOUND = 10002        # Skill 不存在
CODE_INVALID_STATE = 10003    # 非法状态转移 / 前置条件不满足
CODE_FORBIDDEN = 10004        # 权限不足（非本人 / 非 admin）
CODE_RESHARE_CONFIRM = 10005  # 重复分享需二次确认（F-31）


class SkillReviewError(SkillError):
    """审核域业务错误。

    继承 :class:`SkillError`（→ :class:`BaseError`），融入 ``main.py`` 全局异常处理；
    ``error_code`` 沿用 1000x Skill 域，API/MCP 双通道均可捕获后转统一响应。
    """

    def __init__(self, message: str, code: int = 10001) -> None:
        super().__init__(message, error_code=code)


# ==================== 广场内容快照（M4.3，F-29/F-30）====================


def _plaza_snapshot_dir(plaza_id: int) -> Path:
    """广场快照目录：``{upload_dir}/_plaza/{plaza_id}``（独立于个人库 ``{upload_dir}/{skill_code}``）。"""
    return Path(get_settings().skill.upload_dir) / "_plaza" / str(plaza_id)


def snapshot_plaza_source(source_path: str | None, plaza_id: int) -> str:
    """把 skill 源目录快照到 ``{upload_dir}/_plaza/{plaza_id}``，返回快照路径。

    修复广场副本与个人库共享目录的污染问题（F-29：update_my_skill 覆盖
    ``{upload_dir}/{skill_code}`` 不再影响广场磁盘内容）；无源码包/目录不存在返回
    空串（无磁盘内容的内置/元数据型 Skill，DB 字段照常同步）。
    """
    text = str(source_path or "").strip()
    if not text or not Path(text).is_dir():
        return ""
    dest = _plaza_snapshot_dir(plaza_id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(text, dest)
    return str(dest)


def restore_snapshot_to_local(plaza_source_path: str | None, skill_code: str) -> str:
    """把广场快照复制回个人库源目录 ``{upload_dir}/{skill_code}``（resolve iterate 覆盖本地）。

    返回恢复后的本地路径；快照缺失/目录不存在返回空串（调用方按无内容覆盖口径降级——
    仅同步 DB 元数据）。目标目录已有内容时先清除（覆盖式采纳）。
    """
    text = str(plaza_source_path or "").strip()
    if not text or not Path(text).is_dir():
        return ""
    src = Path(text)
    dest = Path(get_settings().skill.upload_dir) / skill_code
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return str(dest)


# ==================== 广场版本归档（2026-09-08，用户裁决：文件级版本管理仅限广场 Skill）===


def _plaza_version_dir(plaza_id: int, version: str) -> Path:
    """广场版本归档目录：``{upload_dir}/_plaza_versions/{plaza_id}/{version}``（不可变历史，回退脚本消费）。"""
    return Path(get_settings().skill.upload_dir) / "_plaza_versions" / str(plaza_id) / version


def build_file_manifest(root: Path) -> list[dict]:
    """文件清单：包内全部文件的相对路径 / 字节数 / SHA-256（``pmcp_plaza_version.file_manifest`` 存档口径）。"""
    manifest: list[dict] = []
    # 按 posix 相对路径字符串排序：Windows Path 比较大小写不敏感，跨平台顺序不一致
    for f in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if not f.is_file():
            continue
        manifest.append(
            {
                "path": f.relative_to(root).as_posix(),
                "size": f.stat().st_size,
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            }
        )
    return manifest


async def archive_plaza_version(
    db: AsyncSession,
    *,
    plaza_id: int,
    version: str,
    source_path: str | None,
    checksum: str | None,
    audit_snapshot: dict | None,
    operator: str | None,
) -> PmcpPlazaVersion:
    """广场版本归档（approve 新增 / merge 迭代时调用，§19.5.3 广场历史版本链）。

    源目录全量快照到 ``_plaza_versions/{plaza_id}/{version}/`` + 文件清单落库；
    ``UNIQUE(plaza_id, version)`` 下同版本重发布覆盖（与 pmcp_skill_version 同语义），
    不同版本累积为不可变历史（手工回退经 ``scripts/_rollback_plaza_version.py``）。
    无源码包（内置/元数据型）仅落 DB 行，snapshot_path 为空串、清单为空。
    """
    text = str(source_path or "").strip()
    snapshot_path, manifest = "", []
    if text and Path(text).is_dir():
        dest = _plaza_version_dir(plaza_id, version)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(text, dest)
        snapshot_path = str(dest)
        manifest = build_file_manifest(dest)

    existing: PmcpPlazaVersion | None = (
        await db.execute(
            select(PmcpPlazaVersion).where(
                PmcpPlazaVersion.plaza_id == plaza_id, PmcpPlazaVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.snapshot_path = snapshot_path
        existing.file_manifest = manifest
        existing.checksum = checksum
        existing.audit_snapshot = audit_snapshot
        existing.updated_by = operator
        record = existing
    else:
        record = PmcpPlazaVersion(
            plaza_id=plaza_id,
            version=version,
            snapshot_path=snapshot_path,
            file_manifest=manifest,
            checksum=checksum,
            audit_snapshot=audit_snapshot,
            inserted_by=operator,
            updated_by=operator,
        )
        db.add(record)
    await db.flush()
    return record


async def backfill_plaza_versions(db: AsyncSession) -> int:
    """部署期幂等补全：现网存量广场 Skill 无任何版本归档时按当前内容快照补一版（文件 + 清单）。"""
    plazas = (await db.execute(select(PmcpSkillPlaza))).scalars().all()
    filled = 0
    for plaza in plazas:
        existing_id = (
            await db.execute(
                select(PmcpPlazaVersion.id).where(PmcpPlazaVersion.plaza_id == plaza.id).limit(1)
            )
        ).scalar_one_or_none()
        if existing_id is not None:
            continue
        await archive_plaza_version(
            db,
            plaza_id=plaza.id,
            version=plaza.version or "0.1.0",
            source_path=plaza.source_path,
            checksum=plaza.source_checksum,
            audit_snapshot=None,
            operator=None,
        )
        filled += 1
    return filled


@dataclass
class ReviewActor:
    """审核动作发起者身份快照（与传输层解耦，Web dict / MCP context 均可构造）。"""

    username: str
    role_code: str
    user_id: int | None = None
    locale: str | None = None
    trace_id: str | None = None

    @classmethod
    def from_user_dict(cls, user: dict, trace_id: str | None = None) -> ReviewActor:
        """由 ``get_current_user`` / MCP 身份 dict 构造（键见 auth.middleware.get_current_user）。"""
        return cls(
            username=user["username"],
            role_code=user.get("role_code") or "developer",
            user_id=user.get("id"),
            locale=user.get("locale"),
            trace_id=trace_id,
        )

    @property
    def is_admin(self) -> bool:
        return self.role_code == "admin"


@dataclass
class ReviewResult:
    """审核动作结果（供 API/MCP 层格式化为统一响应，含 owner 可见的 review_comment）。"""

    skill_id: int
    skill_code: str
    action: str
    old_status: str
    new_status: str
    share_status: str
    plaza_id: int | None = None
    review_comment: str | None = None


class SkillReviewService:
    """Skill 审核域服务。以 ``AsyncSession`` 构造，方法内 ``mutate + flush`` 不 commit。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ==================== 提交 / 撤回 ====================

    async def submit_for_review(
        self,
        actor: ReviewActor,
        skill_id: int,
        *,
        confirm_reshare: bool = False,
    ) -> ReviewResult:
        """提交分享审核（owner）：DRAFT/ENABLED/DISABLED → PENDING_REVIEW。

        F-31 重复分享：已入广场或已在审核管线中时，未带 ``confirm_reshare`` 抛 10005 要求二次确认；
        确认后覆盖上一版本（审核中为覆盖式重提，状态不变；其余走 SUBMIT 转移）。
        """
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        cur = ReviewStatus(skill.status)

        already_shared = skill.share_status == "shared" or cur in {
            ReviewStatus.PENDING_REVIEW,
            ReviewStatus.APPROVED,
            ReviewStatus.SHARE_ITERATION,
        }
        if already_shared and not confirm_reshare:
            raise SkillReviewError(
                "该 Skill 已分享/正在审核中，需二次确认后覆盖上一版本并重新通知审核组",
                code=CODE_RESHARE_CONFIRM,
            )

        if cur == ReviewStatus.PENDING_REVIEW:
            # 覆盖式重提：状态不变，仅刷新留痕并（M5）重新通知审核组
            old = skill.status
            action_label = "reshare"
        else:
            old = self._apply(skill, ReviewAction.SUBMIT)
            action_label = "submit"

        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, action_label, old_status=old)
        # M5.3：提审/重提 → 通知 skill_review 组（§19.5.5；outbox 落库不阻断审核流）
        await self._notify_review(
            actor, skill, "重新提审" if action_label == "reshare" else "提交审核"
        )
        return self._result(skill, action_label, old)

    async def withdraw(self, actor: ReviewActor, skill_id: int) -> ReviewResult:
        """撤回审核（owner）：PENDING_REVIEW → WITHDRAWN（F-32 邮件通知 admin 审核组，M5 挂接）。"""
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        if ReviewStatus(skill.status) != ReviewStatus.PENDING_REVIEW:
            raise SkillReviewError("仅审核中的 Skill 可撤回", code=CODE_INVALID_STATE)
        old = self._apply(skill, ReviewAction.WITHDRAW)
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, "withdraw", old_status=old)
        # M5.3：撤回 → 通知 skill_review 组（F-32）
        await self._notify_review(actor, skill, "撤回审核")
        return self._result(skill, "withdraw", old)

    # ==================== admin 审核 ====================

    async def review(
        self,
        actor: ReviewActor,
        skill_id: int,
        action: Literal["approve", "merge", "reject"],
        *,
        comment: str | None = None,
        iteration_note: str | None = None,
    ) -> ReviewResult:
        """admin 广场审核（仅 PENDING_REVIEW 可审核，对应 Web 审核弹窗 / MCP ``review_skill``）。

        - ``approve``：新增入广场 —— PENDING_REVIEW → APPROVED → ENABLED（链式），upsert 广场副本，
          ``share_status='shared'``（§19.5.3「个人侧已启用，广场副本=已发布」）。
        - ``merge``：合并到广场已有 Skill —— 要求 ``origin=PLAZA``，PENDING_REVIEW → SHARE_ITERATION，
          写广场 ``iteration_note``（F-30 迭代说明）并**内容级同步**广场副本（快照 + 字段 + 向量 +
          涉库标记，M4.3：提审内容采纳入广场）。
        - ``reject``：拒绝 —— PENDING_REVIEW → REJECTED，``review_comment`` 存拒绝原因（owner 可见，F-11）。
        """
        self._require_admin(actor)
        skill = await self._get_skill(skill_id)
        if ReviewStatus(skill.status) != ReviewStatus.PENDING_REVIEW:
            raise SkillReviewError("仅审核中的 Skill 可执行广场审核", code=CODE_INVALID_STATE)

        old = skill.status
        if action == "approve":
            self._apply(skill, ReviewAction.APPROVE)      # → APPROVED（里程碑态）
            plaza = await self._publish_to_plaza(skill, actor)
            self._apply(skill, ReviewAction.ACTIVATE)     # → ENABLED（广场副本已发布）
            skill.share_status = "shared"
            skill.review_comment = comment
            audit_action = "review_approve"
            extra: dict = {"plaza_skill_code": plaza.skill_code}
        elif action == "merge":
            if skill.origin != "PLAZA":
                raise SkillReviewError(
                    "合并仅适用于源自广场的 Skill（origin=PLAZA）；原创 Skill 请用 approve 新增入广场",
                    code=CODE_INVALID_STATE,
                )
            self._apply(skill, ReviewAction.MERGE)        # → SHARE_ITERATION
            note = iteration_note or comment
            plaza = await self._merge_to_plaza(skill, actor, note)
            skill.review_comment = note
            audit_action = "review_merge"
            extra = {"iteration_note": note, "plaza_id": plaza.id, "content_synced": True}
        elif action == "reject":
            self._apply(skill, ReviewAction.REJECT)       # → REJECTED
            skill.review_comment = comment
            audit_action = "review_reject"
            extra = {"reason": comment}
        else:  # pragma: no cover - Literal 已约束，防御性兜底
            raise SkillReviewError("action 必须为 approve/merge/reject", code=CODE_INVALID_STATE)

        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, audit_action, old_status=old, extra=extra)
        # M5.3：审核结果全量通知提交人（通过/合并/拒绝，F-37「非仅拒绝」）——审核组 ∪ 提交人本人
        _action_cn = {"review_approve": "审核通过", "review_merge": "合并迭代", "review_reject": "审核拒绝"}[
            audit_action
        ]
        await self._notify_review(
            actor, skill, _action_cn,
            comment=comment, iteration_note=iteration_note if action == "merge" else None,
            include_owner=True,
        )
        return self._result(skill, audit_action, old)

    # ==================== 分享迭代 / 修改 / 恢复 ====================

    async def resolve_share_iteration(
        self,
        actor: ReviewActor,
        skill_id: int,
        choice: Literal["iterate", "keep"],
    ) -> ReviewResult:
        """解决分享迭代（owner）：SHARE_ITERATION → ENABLED（F-30，选择后状态=已启用）。

        ``iterate``=采纳合并（内容级覆盖本地，M4.3）：广场快照复制回 ``{upload_dir}/{skill_code}``
        + 重放 14 条审计与脱敏 + DB 元数据同步（名称/描述/版本/审计结论）+ 版本化存档（F-28，
        模板兜底）；广场快照缺失时降级为仅同步元数据。``keep``=保留本地（忽略本次迭代，不动内容）。
        """
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        if ReviewStatus(skill.status) != ReviewStatus.SHARE_ITERATION:
            raise SkillReviewError("仅分享迭代中的 Skill 可解决迭代", code=CODE_INVALID_STATE)
        if choice not in ("iterate", "keep"):  # pragma: no cover - Literal 已约束
            raise SkillReviewError("choice 必须为 iterate 或 keep", code=CODE_INVALID_STATE)
        old = self._apply(skill, ReviewAction.RESOLVE_ITERATION)
        content_merged = False
        if choice == "iterate":
            content_merged = await self._apply_plaza_content_to_local(skill, actor)
        skill.updated_by = actor.username
        await self._db.flush()
        audit_action = f"resolve_iteration_{choice}"
        await self._audit(
            actor, skill, audit_action, old_status=old,
            extra={"choice": choice, "content_merged": content_merged},
        )
        return self._result(skill, audit_action, old)

    async def build_iteration_diff(self, actor: ReviewActor, skill_id: int) -> dict:
        """分享迭代差异查询（M4.3/M4.4，F-30）：owner/admin 可查，仅 SHARE_ITERATION 态。

        对比本地源目录与广场快照的 ``SKILL.md``：行级 diff（difflib）+ 语义相似度（BGE-M3 /
        降级哈希余弦）+ 双语差异描述（本地 Qwen3 优先，失败模板兜底）+ 性能提示（M4.4）；
        任一侧缺失按空文本口径降级（广场快照缺失/无源码包时 identical 语义）。返回结构见
        :func:`platform_mcp.skills.llm.generation.build_iteration_diff`。
        """
        skill, _plaza, local_md, plaza_md = await self._iteration_diff_inputs(actor, skill_id)
        return await build_iteration_diff_result(
            skill_name=skill.skill_name, local_md=local_md, plaza_md=plaza_md
        )

    async def build_iteration_diff_material(self, actor: ReviewActor, skill_id: int) -> dict:
        """差异素材查询（MCP 通道，M4.3）：行级 diff + 语义相似度，**不本地生成描述**。

        CC+MCP 外部通道（glm 5.3）据此素材自行生成自然语言差异描述（平台只校验与审计，
        §19.5.1 双通道职责边界）；权限/状态校验与 :meth:`build_iteration_diff` 同口径。
        """
        skill, _plaza, local_md, plaza_md = await self._iteration_diff_inputs(actor, skill_id)
        material = await build_diff_material_impl(local_md, plaza_md)
        material["skill_code"] = skill.skill_code
        return material

    async def _iteration_diff_inputs(
        self, actor: ReviewActor, skill_id: int
    ) -> tuple[PmcpSkill, PmcpSkillPlaza, str, str]:
        """差异查询公共前置：权限（owner/admin）+ 状态（SHARE_ITERATION）+ 双侧 SKILL.md 原文。"""
        skill = await self._get_skill(skill_id)
        if skill.inserted_by != actor.username and not actor.is_admin:
            raise SkillReviewError("仅本人或 admin 可查看迭代差异", code=CODE_FORBIDDEN)
        if ReviewStatus(skill.status) != ReviewStatus.SHARE_ITERATION:
            raise SkillReviewError("仅分享迭代中的 Skill 可查看差异", code=CODE_INVALID_STATE)
        plaza = await self._locate_plaza(skill)
        return (
            skill,
            plaza,
            read_package_skill_md(skill.source_path),
            read_package_skill_md(plaza.source_path),
        )

    async def revise(self, actor: ReviewActor, skill_id: int) -> ReviewResult:
        """修改后重编辑（owner）：REJECTED → DRAFT（保留上次拒绝原因供参考，重提审时覆盖）。"""
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        old = self._apply(skill, ReviewAction.REVISE)
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, "revise", old_status=old)
        return self._result(skill, "revise", old)

    async def restore(self, actor: ReviewActor, skill_id: int) -> ReviewResult:
        """恢复（owner）：WITHDRAWN → DRAFT。"""
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        old = self._apply(skill, ReviewAction.RESTORE)
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, "restore", old_status=old)
        return self._result(skill, "restore", old)

    # ==================== 启停（含 F-32 停用视同撤回）====================

    async def set_enabled(self, actor: ReviewActor, skill_id: int, enabled: bool) -> ReviewResult:
        """创建人启停已过审 Skill（owner）。

        - ``enabled=False``：ENABLED → DISABLED；**若处于 PENDING_REVIEW（已提交未过审）则视同撤回**
          → WITHDRAWN（F-32）。
        - ``enabled=True``：DISABLED → ENABLED。
        """
        skill = await self._get_skill(skill_id)
        self._require_owner(skill, actor)
        cur = ReviewStatus(skill.status)
        if not enabled:
            if cur == ReviewStatus.PENDING_REVIEW:
                old = self._apply(skill, ReviewAction.WITHDRAW)  # 停用视同撤回
                action_label = "withdraw_via_disable"
            else:
                old = self._apply(skill, ReviewAction.DISABLE)
                action_label = "disable"
        else:
            old = self._apply(skill, ReviewAction.ENABLE)
            action_label = "enable"
        skill.updated_by = actor.username
        await self._db.flush()
        await self._audit(actor, skill, action_label, old_status=old)
        # M5.3：停用视同撤回 → 通知 skill_review 组（F-32；owner 自身动作，不另发 owner）
        if action_label == "withdraw_via_disable":
            await self._notify_review(actor, skill, "撤回审核（停用）")
        return self._result(skill, action_label, old)

    # ==================== 可见性 / 可用性查询（F-27，供 API/MCP 复用）====================

    def is_visible_to(self, actor: ReviewActor, skill: PmcpSkill) -> bool:
        """个人库查询层可见性（委托状态机可见性矩阵，F-27）。"""
        return visible_in_personal_library(
            status=skill.status,
            share_status=skill.share_status,
            role_code=actor.role_code,
            is_owner=skill.inserted_by == actor.username,
            is_builtin=skill.register_method == "decorator",
        )

    def owner_can_use_mcp(self, skill: PmcpSkill) -> bool:
        """本人是否可经 MCP 使用该 Skill（未过审仅本人可用；拒绝/撤回/停用不可用）。"""
        return owner_mcp_usable(skill.status)

    # ==================== 私有 helper ====================

    async def _get_skill(self, skill_id: int) -> PmcpSkill:
        skill: PmcpSkill | None = await self._db.get(PmcpSkill, skill_id)
        if skill is None:
            raise SkillReviewError("Skill 不存在", code=CODE_NOT_FOUND)
        return skill

    def _require_owner(self, skill: PmcpSkill, actor: ReviewActor) -> None:
        if skill.inserted_by != actor.username:
            raise SkillReviewError("无权操作他人 Skill", code=CODE_FORBIDDEN)

    def _require_admin(self, actor: ReviewActor) -> None:
        if not actor.is_admin:
            raise SkillReviewError("仅 admin 可执行广场审核", code=CODE_FORBIDDEN)

    def _apply(self, skill: PmcpSkill, action: ReviewAction) -> str:
        """对 skill 执行状态机动作并写回 ``status``，返回旧状态字符串。

        非法转移由状态机抛 :class:`InvalidTransitionError`，此处转 :class:`SkillReviewError`(10003)。
        """
        old = skill.status
        try:
            target = transition(old, action)
        except InvalidTransitionError as exc:
            raise SkillReviewError(f"非法状态转移：{exc}", code=CODE_INVALID_STATE) from exc
        skill.status = target.value
        return old

    async def _resolve_user_id(self, username: str | None) -> int | None:
        """username → user_id（广场 uploader_id 用）；无对应用户返回 None。"""
        if not username:
            return None
        user_id: int | None = (
            await self._db.execute(select(PmcpUser.id).where(PmcpUser.username == username))
        ).scalar_one_or_none()
        return user_id

    async def _notify_review(
        self,
        actor: ReviewActor,
        skill: PmcpSkill,
        action_cn: str,
        *,
        comment: str | None = None,
        iteration_note: str | None = None,
        include_owner: bool = False,
    ) -> None:
        """skill_review 邮件捕捉点（M5.3，§19.5.5）：审核组 ∪ 提交人本人（结果类）。

        经 outbox 落库不发送（Web 进程周期 flush）；dispatch 内部异常全捕获，
        通知链路故障不影响审核流主链路。
        """
        from platform_mcp.notify.service import dispatch_notification

        extra: list[tuple[int | None, str]] | None = None
        if include_owner:
            row = (
                await self._db.execute(
                    select(PmcpUser.id, PmcpUser.email).where(
                        PmcpUser.username == skill.inserted_by
                    )
                )
            ).first()
            if row is not None and row.email:
                extra = [(row.id, row.email)]
        await dispatch_notification(
            "skill_review",
            {
                "user": actor.username,
                "resource": skill.skill_name,
                "action": action_cn,
                "reason": comment or "",
                "iteration_note": iteration_note or "",
            },
            source="review",
            extra_recipients=extra,
            trace_id=actor.trace_id,
            operator=actor.username,
        )

    async def _publish_to_plaza(self, skill: PmcpSkill, actor: ReviewActor) -> PmcpSkillPlaza:
        """按 ``skill_code`` upsert 广场副本（approve 新增入广场 / F-31 覆盖上一版本），回写 ``plaza_id``。

        M4.3：源内容快照到 ``{upload_dir}/_plaza/{plaza_id}``（与个人库目录隔离，F-29 磁盘层
        成立）；涉库/涉服务器标记由 audit_result 的 R2-xx / R3-xx 命中派生（架构 §19.5.3 / F-23），
        带标记的广场副本对一般用户在 Web 与 MCP 双端均不可见（可见性由广场检索/工具层按角色过滤）。
        """
        plaza: PmcpSkillPlaza | None = (
            await self._db.execute(
                select(PmcpSkillPlaza).where(PmcpSkillPlaza.skill_code == skill.skill_code)
            )
        ).scalar_one_or_none()
        uploader_id = await self._resolve_user_id(skill.inserted_by)
        involve_flags = derive_involve_flags(skill.audit_result)
        if plaza is None:
            plaza = PmcpSkillPlaza(
                skill_code=skill.skill_code,
                status="PUBLISHED",
                inserted_by=actor.username,
            )
            self._db.add(plaza)
            await self._db.flush()  # 取得 plaza.id（快照目录以 plaza_id 命名）
        snapshot = snapshot_plaza_source(skill.source_path, plaza.id)
        await archive_plaza_version(
            self._db,
            plaza_id=plaza.id,
            version=skill.version or "0.1.0",
            source_path=skill.source_path,
            checksum=skill.source_checksum,
            audit_snapshot=skill.audit_result,
            operator=actor.username,
        )
        plaza.skill_name = skill.skill_name
        plaza.description = skill.description
        plaza.version = skill.version
        plaza.uploader_id = uploader_id
        plaza.involve_flags = involve_flags
        if snapshot:
            plaza.source_path = snapshot
            plaza.source_checksum = skill.source_checksum
        plaza.status = "PUBLISHED"
        plaza.updated_by = actor.username
        await self._db.flush()
        skill.plaza_id = plaza.id
        # 广场语义向量：发布/覆盖入广场时计算名称+描述向量（BGE-M3 / 降级哈希，架构 §19.5.6 / F-33）。
        await index_plaza_embedding(self._db, plaza.id, plaza.skill_name, plaza.description)
        return plaza

    async def _locate_plaza(self, skill: PmcpSkill) -> PmcpSkillPlaza:
        """定位合并/迭代目标广场副本（优先 ``skill.plaza_id``，回退按 ``skill_code`` 查）。"""
        plaza: PmcpSkillPlaza | None = None
        if skill.plaza_id is not None:
            plaza = await self._db.get(PmcpSkillPlaza, skill.plaza_id)
        if plaza is None:
            plaza = (
                await self._db.execute(
                    select(PmcpSkillPlaza).where(PmcpSkillPlaza.skill_code == skill.skill_code)
                )
            ).scalar_one_or_none()
        if plaza is None:
            raise SkillReviewError("合并目标广场副本不存在", code=CODE_INVALID_STATE)
        return plaza

    async def _merge_to_plaza(
        self, skill: PmcpSkill, actor: ReviewActor, note: str | None
    ) -> PmcpSkillPlaza:
        """merge：定位广场副本 → 写 ``iteration_note`` → 内容级同步（M4.3）。

        内容级同步 = 提审源目录快照入广场 + 副本字段刷新（名称/描述/版本/涉库标记）+ 语义向量
        重建（广场搜索口径与内容保持一致）；广场保持 PUBLISHED。
        """
        plaza = await self._locate_plaza(skill)
        plaza.iteration_note = note
        snapshot = snapshot_plaza_source(skill.source_path, plaza.id)
        await archive_plaza_version(
            self._db,
            plaza_id=plaza.id,
            version=skill.version or "0.1.0",
            source_path=skill.source_path,
            checksum=skill.source_checksum,
            audit_snapshot=skill.audit_result,
            operator=actor.username,
        )
        plaza.skill_name = skill.skill_name
        plaza.description = skill.description
        plaza.version = skill.version
        plaza.involve_flags = derive_involve_flags(skill.audit_result)
        if snapshot:
            plaza.source_path = snapshot
            plaza.source_checksum = skill.source_checksum
        plaza.status = "PUBLISHED"
        plaza.updated_by = actor.username
        await self._db.flush()
        await index_plaza_embedding(self._db, plaza.id, plaza.skill_name, plaza.description)
        return plaza

    async def _apply_plaza_content_to_local(self, skill: PmcpSkill, actor: ReviewActor) -> bool:
        """resolve iterate：广场快照覆盖回本地（M4.3 内容级采纳）。

        快照复制到 ``{upload_dir}/{skill_code}`` → 重放 14 条审计（新内容入个人库的第一道
        审核口径）→ DB 元数据同步（名称/描述/版本/审计结论/README 标记）→ 版本化存档（F-28，
        模板兜底；generated_by=template，本地模型升级任务不在此用户动作链路）。返回是否完成内容级
        覆盖（快照缺失返回 False，仅元数据同步）。
        """
        plaza = await self._locate_plaza(skill)
        restored = restore_snapshot_to_local(plaza.source_path, skill.skill_code)
        # 元数据同步（采纳合并：以广场发布口径为准）
        skill.skill_name = plaza.skill_name
        skill.description = plaza.description
        skill.version = plaza.version or skill.version
        if not restored:
            return False
        root = Path(restored)
        audit_result = audit_skill_package(root, plaza.skill_name)
        audit_result.compute_counts()
        if audit_result.critical_count > 0:
            audit_status = "failed"
        elif audit_result.warning_count > 0:
            audit_status = "warning"
        else:
            audit_status = "passed"
        skill.source_path = restored
        skill.source_checksum = plaza.source_checksum or skill.source_checksum
        skill.audit_status = audit_status
        skill.audit_result = audit_result.to_audit_summary()
        if (root / "README.md").exists():
            skill.readme_generated = True
        # 版本化存档（F-28 每次更新均存档；similar 标注本次采纳源=广场合并）
        similar = [{
            "plaza_id": plaza.id, "skill_code": plaza.skill_code, "skill_name": plaza.skill_name,
            "version": plaza.version, "similarity": 1.0, "recommendation": "merge",
        }]
        readme_zh, readme_en = generate_bilingual_readme(
            skill.skill_name, skill.description, root, skill.version or "0.0.0"
        )
        report_zh, report_en = generate_bilingual_report(
            skill_code=skill.skill_code, skill_name=skill.skill_name,
            description=skill.description, version=skill.version or "0.0.0",
            audit_result=audit_result, similar_skills=similar,
        )
        await archive_skill_version(
            self._db, skill_id=skill.id, version=skill.version or "0.0.0",
            checksum=skill.source_checksum, readme_zh=readme_zh, readme_en=readme_en,
            report_zh=report_zh, report_en=report_en,
            audit_snapshot=audit_result.to_audit_summary(), operator=actor.username,
        )
        return True

    def _result(self, skill: PmcpSkill, action: str, old_status: str) -> ReviewResult:
        return ReviewResult(
            skill_id=skill.id,
            skill_code=skill.skill_code,
            action=action,
            old_status=old_status,
            new_status=skill.status,
            share_status=skill.share_status,
            plaza_id=skill.plaza_id,
            review_comment=skill.review_comment,
        )

    async def _audit(
        self,
        actor: ReviewActor,
        skill: PmcpSkill,
        action: str,
        *,
        old_status: str,
        result_status: str = "success",
        error_message: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """审计留痕（``resource_type="skill"``，F-40 操作明细可区分）。

        注：skill_review 邮件（提审/通过/合并/拒绝/撤回）由 M5 在各流程点显式触发（§19.5.5），
        本服务仅落审计；审计与邮件同为 owner/admin 可见决策留痕，review_comment 为 owner 侧持久化。
        """
        detail: dict = {
            "skill_code": skill.skill_code,
            "action": action,
            "old_status": old_status,
            "new_status": skill.status,
            "share_status": skill.share_status,
            "plaza_id": skill.plaza_id,
        }
        if extra:
            detail.update(extra)
        await write_audit_log(
            trace_id=actor.trace_id,
            operator=actor.username,
            skill_name=skill.skill_code,
            resource_type="skill",
            resource_id=str(skill.id),
            request_summary=f"Skill 审核流：{skill.skill_code} — {action}",
            result_status=result_status,
            error_message=error_message,
            extra_data=detail,
        )
