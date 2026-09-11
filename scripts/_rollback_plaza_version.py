"""广场 Skill 版本回退（运维脚本壳，2026-09-11 服务化）

文件级版本管理仅限广场 Skill（approve/merge/publish 时快照入 ``{upload_dir}/
_plaza_versions/{plaza_id}/{version}/``，清单落 ``pmcp_plaza_version``）。历史上为
手工脚本；V3.0 生命周期增强（设计定稿⑦）将回退服务化为
:func:`platform_mcp.skills.plaza_service.rollback_plaza_version`（与 Web
``POST /plaza/{id}/versions/{version}/rollback`` 同一编排：快照恢复 + DB 回写 +
README 迭代段落 + 持有者迭代标记 + 审计），本脚本保留 CLI 壳与 ``--dry-run``
预检，实际变更一律委托服务（单一咽喉）。

用法（仓库根目录，DB 可达）：
    python scripts/_rollback_plaza_version.py --plaza-id 3 --version 0.1.0 [--note "回退原因"] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select

from platform_mcp.common.database import _ensure_engine, get_session_factory
from platform_mcp.review.service import ReviewActor, _plaza_snapshot_dir
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillPlaza
from platform_mcp.skills.plaza_service import rollback_plaza_version

# 脚本通道身份：运维手工路径，admin 口径（实际执行者经 git/终端留痕）
_SCRIPT_ACTOR = ReviewActor(username="rollback-script", role_code="admin")


async def main() -> None:
    parser = argparse.ArgumentParser(description="广场 Skill 版本回退（委托 rollback_plaza_version 服务：快照恢复 + 迭代标记 + 审计）")
    parser.add_argument("--plaza-id", type=int, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--note", default=None, help="回退原因（写入审计 extra_data.note）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印计划，不执行变更")
    args = parser.parse_args()

    _ensure_engine()
    async with get_session_factory()() as session:
        # 预检（与 Web/API 同口径的存活性校验，dry-run 与实跑共用）
        plaza = await session.get(PmcpSkillPlaza, args.plaza_id)
        if plaza is None:
            raise SystemExit(f"plaza_id={args.plaza_id} 不存在")
        version_row = (
            await session.execute(
                select(PmcpPlazaVersion).where(
                    PmcpPlazaVersion.plaza_id == args.plaza_id,
                    PmcpPlazaVersion.version == args.version,
                )
            )
        ).scalar_one_or_none()
        if version_row is None:
            raise SystemExit(f"版本 {args.version} 无归档记录（pmcp_plaza_version）")
        snapshot = Path(version_row.snapshot_path or "")
        if not snapshot.is_dir():
            raise SystemExit(f"版本快照目录缺失：{snapshot}")

        live = _plaza_snapshot_dir(args.plaza_id)
        file_count = len(version_row.file_manifest or [])
        print(f"回退 {plaza.skill_code}: v{plaza.version} -> v{args.version}（{file_count} 个文件）")
        print(f"快照：{snapshot}")
        print(f"当前：{live}")
        if args.dry_run:
            print("dry-run：未执行任何变更")
            return

        result = await rollback_plaza_version(
            session,
            args.plaza_id,
            args.version,
            _SCRIPT_ACTOR,
            note=args.note or None,
            channel="script",
        )
        await session.commit()
        print(
            f"回退完成：v{result['from_version']} -> v{result['to_version']}"
            f"（{result['file_count']} 个文件，{result['holders_marked']} 个持有者副本标记迭代；"
            f"DB 已提交，审计已留痕）"
        )


if __name__ == "__main__":
    asyncio.run(main())
