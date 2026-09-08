"""广场 Skill 版本手工回退（运维脚本，2026-09-08）

文件级版本管理仅限广场 Skill（approve/merge 时快照入 ``{upload_dir}/_plaza_versions/
{plaza_id}/{version}/``，清单落 ``pmcp_plaza_version``）。本脚本把指定历史版本快照
恢复为广场当前内容并回写 DB，全程审计留痕（resource_type=skill）。前端不开放回退
按钮——按用户裁决为运维手工路径（个人/装饰器系统 Skill 仅最新版，无版本可回退）。

用法（仓库根目录，DB 可达）：
    python scripts/_rollback_plaza_version.py --plaza-id 3 --version 0.1.0 [--note "回退原因"] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path

from sqlalchemy import select

from platform_mcp.audit.logger import write_audit_log
from platform_mcp.common.database import _ensure_engine, get_session_factory
from platform_mcp.review.service import _plaza_snapshot_dir
from platform_mcp.skills.models import PmcpPlazaVersion, PmcpSkillPlaza


async def main() -> None:
    parser = argparse.ArgumentParser(description="广场 Skill 版本手工回退（快照恢复 + DB 回写 + 审计留痕）")
    parser.add_argument("--plaza-id", type=int, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--note", default="", help="回退原因（写入审计 extra_data.note）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印计划，不执行变更")
    args = parser.parse_args()

    _ensure_engine()
    async with get_session_factory()() as session:
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

        if live.exists():
            shutil.rmtree(live)
        shutil.copytree(snapshot, live)
        old_version = plaza.version
        plaza.version = args.version
        plaza.source_path = str(live)
        if version_row.checksum:
            plaza.source_checksum = version_row.checksum
        plaza.updated_by = "rollback-script"
        await session.flush()
        await write_audit_log(
            trace_id=None,
            operator="rollback-script",
            skill_name=plaza.skill_code,
            resource_type="skill",
            resource_id=str(plaza.id),
            request_summary=f"广场版本手工回退：v{old_version} -> v{args.version}",
            extra_data={"note": args.note, "files": file_count},
        )
        await session.commit()
        print("回退完成（DB 已提交，审计已留痕）")


if __name__ == "__main__":
    asyncio.run(main())
