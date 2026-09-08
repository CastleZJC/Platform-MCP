"""Skill 包路径识别与自动调整（2026-09-08 用户裁决：自动调整、不打回）

非专业作者注册的 Skill，其 md 中常残留作者本机绝对路径（Windows 盘符 / Unix home），
导致注册后其他机器上的 CC 无法解析引用。本模块在**注册链路落盘后、审计/校验和计算前**
对包内全部 .md 做一次确定性调整（Web zip 上传与 MCP 附件双通道共用）：

- **可解析到包内文件**（按路径尾缀匹配包内相对路径）→ 改写为包内相对 posix 路径
  （"服务器路径"的可寻址形态：skill + 包内相对路径，经 ``get_skill_file`` 下发）；
- **其余绝对路径（工作路径）** → 改写为 ``./<basename>``（Skill 使用时工作目录默认当前路径）；
- URL（http/https/mcp/mailto）与纯相对路径不动。

版本一致性（用户提示"记得考虑版本问题"）：调整先于审计与校验和计算 → 版本存档与广场
快照均为调整后内容；调整记录 ``[{file, before, after, kind}]`` 并入当版 ``audit_snapshot``
JSONB（版本自描述、历史版本不受后续调整影响）。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

# 路径字符排除集：Windows 保留字符、空白、常见中英文标点分隔符（路径不会以这些字符 continuation）
_EXCLUDED = r'\\/:*?"<>|\s\t，。；：！？、（）〈〉《》【】〔〕“”‘’'
_WIN_PATH = re.compile(rf"[A-Za-z]:[\\/](?:[^{_EXCLUDED}]+[\\/])*[^{_EXCLUDED}]*")
_UNIX_HOME = re.compile(r"(?:/home|/Users)/[^'\"'）)\]}>,;，。；：！？、\s\t]+")


def _preceded_by_token(text: str, start: int) -> bool:
    """候选前一字符属更长 token（URL 域名后的 /home、标识符后的盘符等）时跳过。"""
    return start > 0 and (text[start - 1].isalnum() or text[start - 1] in ".-")


def _resolve_package_relative(candidate: str, files: set[str]) -> str | None:
    """绝对路径按最长存在尾缀解析为包内相对 posix 路径；解析不到返回 None。"""
    parts = [p for p in PurePosixPath(candidate.replace("\\", "/")).parts if p not in ("/", ".")]
    parts = [p for p in parts if not (len(p) == 2 and p.endswith(":"))]  # 丢盘符段
    for i in range(len(parts)):
        tail = "/".join(parts[i:])
        if tail in files:
            return tail
    return None


def _adjust_text(text: str, files: set[str], rel_md: str, adjustments: list[dict]) -> str:
    """对单文件文本执行绝对路径改写（单点替换 + 重扫，避免替换改变偏移后旧 match 越界）。"""
    for pattern in (_WIN_PATH, _UNIX_HOME):
        while True:
            replaced = False
            search_from = 0
            m = pattern.search(text, search_from)
            while m:
                candidate = m.group(0)
                start = m.start()
                if _preceded_by_token(text, start):
                    m = pattern.search(text, m.end())
                    continue
                posix = PurePosixPath(candidate.replace("\\", "/"))
                if not posix.name or posix.name.endswith(":"):
                    m = pattern.search(text, m.end())
                    continue
                resolved = _resolve_package_relative(candidate, files)
                if resolved:
                    replacement, kind = resolved, "reference"
                else:
                    replacement, kind = "./" + posix.name, "workdir"
                if replacement != candidate:
                    text = text[:start] + replacement + text[m.end():]
                    adjustments.append(
                        {"file": rel_md, "before": candidate, "after": replacement, "kind": kind}
                    )
                    replaced = True
                    break  # text 已变，从头重扫
                m = pattern.search(text, m.end())
            if not replaced:
                break
    return text


def normalize_package_paths(root: Path) -> list[dict]:
    """包内全部 .md 的绝对路径引用自动调整（写回文件），返回调整记录（见模块 docstring）。

    幂等：已是相对路径的内容不再命中任何绝对路径模式，重复执行零调整。
    """
    files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    adjustments: list[dict] = []
    for md in sorted(root.rglob("*.md"), key=lambda p: p.relative_to(root).as_posix()):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text = _adjust_text(text, files, md.relative_to(root).as_posix(), adjustments)
        if new_text != text:
            md.write_text(new_text, encoding="utf-8", newline="")
    # 同文件同串多次出现只记一条
    seen: set[tuple] = set()
    unique: list[dict] = []
    for a in adjustments:
        key = (a["file"], a["before"], a["after"])
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique
