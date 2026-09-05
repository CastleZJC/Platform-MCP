"""知识库切片策略枚举（V3.0 M6 骨架，架构 §19.6；F-41）

RAG 常规 7 种切片方式（值域唯一事实来源）：``pmcp_kb_chunk.chunking_strategy``
列取值由此把守（非空 CHECK 见 migration 010，值域由本枚举 + 服务层校验）。
三期实现切片算法；V3.0 仅交付枚举与值域，不实现切分逻辑。
"""

from __future__ import annotations

from enum import Enum


class ChunkingStrategy(str, Enum):
    """7 种切片策略（架构 §19.6 定稿）。"""

    FIXED = "fixed"                          # 固定长度切片（按字符数/ token 数）
    SENTENCE = "sentence"                    # 按句切片（句号/问号/叹号等边界）
    PARAGRAPH = "paragraph"                  # 按段落切片（空行边界）
    SEMANTIC = "semantic"                    # 语义切片（相邻句向量相似度下降点切分）
    RECURSIVE = "recursive"                  # 递归分隔符切片（段落→句子→字符逐级回退）
    MARKDOWN_HEADING = "markdown_heading"    # 按 Markdown 标题层级切片（#/##/###）
    SLIDING_WINDOW = "sliding_window"        # 滑动窗口切片（带重叠的固定窗口）


#: 全部合法策略（frozenset，供服务层校验 ``pmcp_kb_chunk.chunking_strategy`` 取值）
CHUNKING_STRATEGIES: frozenset[ChunkingStrategy] = frozenset(ChunkingStrategy)

#: 策略中文描述（管理页展示 / 三期实现指引）
STRATEGY_DESCRIPTIONS: dict[ChunkingStrategy, str] = {
    ChunkingStrategy.FIXED: "固定长度切片",
    ChunkingStrategy.SENTENCE: "按句切片",
    ChunkingStrategy.PARAGRAPH: "按段落切片",
    ChunkingStrategy.SEMANTIC: "语义切片（相似度断点）",
    ChunkingStrategy.RECURSIVE: "递归分隔符切片",
    ChunkingStrategy.MARKDOWN_HEADING: "按 Markdown 标题切片",
    ChunkingStrategy.SLIDING_WINDOW: "滑动窗口切片（带重叠）",
}


def coerce_strategy(value: str) -> ChunkingStrategy:
    """字符串 → 枚举；非法值抛 ``ValueError``（入参校验统一入口）。"""
    return ChunkingStrategy(value)
