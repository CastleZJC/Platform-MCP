"""广场语义向量栈（V3.0 M3.2，架构 §19.5.6 / 计划 M3.2、F-33、VNF-02、R-12）

**EmbeddingProvider（向量生成）双实现**：

- :class:`BgeM3EmbeddingProvider`：BGE-M3 经 fastembed（ONNX Runtime CPU int8，无 torch 依赖），
  权重离线分发（``settings.skill.embedding_model_path``）；**仅当显式配置权重目录且 fastembed 可用**
  时启用（VNF-03：权重不入仓库、不联网下载），否则降级。
- :class:`FallbackHashEmbeddingProvider`：确定性哈希词袋向量（**权重缺失降级**），保证语义搜索链路
  在开发/测试/无权重生产环境始终可用且可测（相似度退化为词重叠余弦，与广场关键词粗排同源）。

**EmbeddingStore（向量存储 + 检索）双实现**：

- :class:`JsonbEmbeddingStore`：``pmcp_skill_plaza.embedding`` JSONB + 内存余弦——pgvector 受限时的
  降级路径（VNF-02「先行验收」，Skill 量级 < 数千可行）。
- :class:`PgVectorEmbeddingStore`：pgvector 原生列 ``embedding_vec`` + DB 侧余弦 ``<=>``（生产可装扩展时）。

:func:`create_embedding_store` 工厂按 settings + 运行期扩展探测选择后端，pgvector 不可用自动降级
JSONB（R-12）。检索契约 ``search(vector, top_k, candidate_ids)``：可见性（状态/涉库/黑名单）由调用方
先筛出 ``candidate_ids``，本模块只负责向量排序——业务可见性与向量检索解耦。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence

from loguru import logger
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.config import get_settings
from platform_mcp.skills.models import PmcpSkillPlaza

_TOKEN_RE = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")
_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "skill", "skills", "的", "了", "和", "与"}
)


def tokenize(text_value: str | None) -> list[str]:
    """中英文分词（非字母数字汉字切分 + 去停用词/单字），供降级哈希向量与关键词粗排共用。"""
    if not text_value:
        return []
    tokens = _TOKEN_RE.split(text_value.lower())
    return [t for t in tokens if t and t not in _STOPWORDS and len(t) >= 2]


def cosine_similarity(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    """余弦相似度（0~1 区间内的相对分；维度不一致/空向量返回 0.0）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ==================== EmbeddingProvider（向量生成）====================


class EmbeddingProvider(ABC):
    """文本 → 向量生成器抽象（BGE-M3 / 降级哈希双实现）。"""

    name: str = "base"

    @property
    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""

    @property
    @abstractmethod
    def available(self) -> bool:
        """是否可用（BGE-M3 权重/依赖缺失时为 False）。"""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成向量（同步 CPU 操作；异步调用方经 :func:`embed_text` 走线程池）。"""


class BgeM3EmbeddingProvider(EmbeddingProvider):
    """BGE-M3 经 fastembed（ONNX Runtime CPU int8，无 torch）。

    仅当显式配置离线权重目录且 fastembed 可导入/加载时可用；任何异常（依赖缺失、权重不存在）
    均降级为不可用（由 :func:`get_embedding_provider` 回退哈希向量），绝不联网下载（VNF-03）。
    """

    name = "bge-m3"

    def __init__(self, model_name: str, model_path: str, dim: int) -> None:
        self._model_name = model_name
        self._model_path = model_path
        self._dim = dim
        self._model: object | None = None
        self._available = False
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name, cache_dir=model_path or None)
            self._available = True
            logger.info("BGE-M3 embedding 就绪（fastembed，权重目录={}）", model_path or "默认缓存")
        except Exception as exc:  # fastembed 缺失 / 权重不可用 → 降级（不联网）
            logger.warning("BGE-M3 不可用（{}），降级确定性哈希向量", exc)
            self._model = None
            self._available = False

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        return self._available

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not self._available or self._model is None:
            raise RuntimeError("BGE-M3 provider 不可用（权重/依赖缺失）")
        embed_fn = getattr(self._model, "embed")
        return [[float(x) for x in vec] for vec in embed_fn(list(texts))]


class FallbackHashEmbeddingProvider(EmbeddingProvider):
    """确定性哈希词袋向量（权重缺失降级）：token → SHA-256 桶位计数 → L2 归一化。

    无外部依赖、跨进程稳定，余弦相似度退化为词重叠度——与广场关键词粗排同源，保证搜索链路可用可测。
    """

    name = "fallback-hash"

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        return True

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text_value: str) -> list[float]:
        vec = [0.0] * self._dim
        for tok in tokenize(text_value):
            digest = hashlib.sha256(tok.encode("utf-8")).hexdigest()
            vec[int(digest, 16) % self._dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        return vec


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """返回进程级单例 EmbeddingProvider（BGE-M3 优先，缺失降级哈希）。"""
    global _provider
    if _provider is not None:
        return _provider
    s = get_settings().skill
    provider: EmbeddingProvider
    if s.embedding_model_path:
        candidate = BgeM3EmbeddingProvider(s.embedding_model_name, s.embedding_model_path, s.embedding_dim)
        provider = candidate if candidate.available else FallbackHashEmbeddingProvider(s.embedding_fallback_dim)
    else:
        provider = FallbackHashEmbeddingProvider(s.embedding_fallback_dim)
    _provider = provider
    logger.info("EmbeddingProvider 选定：{}（dim={}）", provider.name, provider.dim)
    return _provider


def reset_embedding_provider() -> None:
    """清空单例（测试用：切换 settings 后重新选定 provider）。"""
    global _provider
    _provider = None


async def embed_text(text_value: str) -> list[float]:
    """异步生成单条文本向量（同步 provider 走线程池，避免阻塞事件循环）。"""
    provider = get_embedding_provider()
    vectors = await asyncio.to_thread(provider.embed, [text_value])
    return vectors[0]


# ==================== EmbeddingStore（存储 + 检索）====================


class EmbeddingStore(ABC):
    """广场向量存储 + 检索抽象（JSONB / pgvector 双实现）。"""

    backend: str = "base"

    @abstractmethod
    async def upsert(self, plaza_id: int, vector: Sequence[float]) -> None:
        """写入/更新某广场 Skill 的向量。"""

    @abstractmethod
    async def search(
        self, vector: Sequence[float], top_k: int, candidate_ids: Sequence[int]
    ) -> list[tuple[int, float]]:
        """在 ``candidate_ids`` 范围内按余弦降序返回 ``[(plaza_id, score)]``（至多 top_k）。"""

    @abstractmethod
    async def clear(self, plaza_id: int) -> None:
        """清除某广场 Skill 的向量。"""


class JsonbEmbeddingStore(EmbeddingStore):
    """JSONB 列 + 内存余弦（pgvector 受限的降级路径，VNF-02 先行验收）。"""

    backend = "jsonb"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert(self, plaza_id: int, vector: Sequence[float]) -> None:
        plaza = await self._db.get(PmcpSkillPlaza, plaza_id)
        if plaza is not None:
            plaza.embedding = [float(x) for x in vector]
            await self._db.flush()

    async def search(
        self, vector: Sequence[float], top_k: int, candidate_ids: Sequence[int]
    ) -> list[tuple[int, float]]:
        ids = list(candidate_ids)
        if not ids or top_k <= 0:
            return []
        rows = (
            await self._db.execute(
                select(PmcpSkillPlaza.id, PmcpSkillPlaza.embedding).where(PmcpSkillPlaza.id.in_(ids))
            )
        ).all()
        scored: list[tuple[int, float]] = []
        for plaza_id, emb in rows:
            if emb:
                scored.append((int(plaza_id), cosine_similarity(vector, emb)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    async def clear(self, plaza_id: int) -> None:
        plaza = await self._db.get(PmcpSkillPlaza, plaza_id)
        if plaza is not None:
            plaza.embedding = None
            await self._db.flush()


class PgVectorEmbeddingStore(EmbeddingStore):
    """pgvector 原生列 ``embedding_vec`` + DB 侧余弦 ``<=>``（生产可装扩展时）。

    upsert 同时镜像写 JSONB ``embedding``（后端切换无损）；维度与原生列不匹配（如降级哈希向量）时
    检索自动退回 JSONB 内存余弦，保证任何 provider 下结果可用。
    """

    backend = "pgvector"

    def __init__(self, db: AsyncSession, dim: int) -> None:
        self._db = db
        self._dim = dim

    @staticmethod
    def _literal(vector: Sequence[float]) -> str:
        return "[" + ",".join(repr(float(x)) for x in vector) + "]"

    async def upsert(self, plaza_id: int, vector: Sequence[float]) -> None:
        vec = [float(x) for x in vector]
        plaza = await self._db.get(PmcpSkillPlaza, plaza_id)
        if plaza is not None:
            plaza.embedding = vec  # JSONB 镜像（切换无损）
            await self._db.flush()
        if len(vec) == self._dim:
            await self._db.execute(
                text("UPDATE pmcp_skill_plaza SET embedding_vec = CAST(:vec AS vector) WHERE id = :id"),
                {"vec": self._literal(vec), "id": plaza_id},
            )

    async def search(
        self, vector: Sequence[float], top_k: int, candidate_ids: Sequence[int]
    ) -> list[tuple[int, float]]:
        ids = list(candidate_ids)
        if not ids or top_k <= 0:
            return []
        vec = [float(x) for x in vector]
        if len(vec) != self._dim:
            # 维度不匹配（降级哈希向量）→ 退回 JSONB 内存余弦
            return await JsonbEmbeddingStore(self._db).search(vector, top_k, ids)
        stmt = text(
            "SELECT id, 1 - (embedding_vec <=> CAST(:vec AS vector)) AS score "
            "FROM pmcp_skill_plaza "
            "WHERE embedding_vec IS NOT NULL AND id IN :ids "
            "ORDER BY embedding_vec <=> CAST(:vec AS vector) ASC "
            "LIMIT :k"
        ).bindparams(bindparam("ids", expanding=True))
        rows = (
            await self._db.execute(stmt, {"vec": self._literal(vec), "ids": ids, "k": top_k})
        ).all()
        return [(int(row[0]), float(row[1])) for row in rows]

    async def clear(self, plaza_id: int) -> None:
        plaza = await self._db.get(PmcpSkillPlaza, plaza_id)
        if plaza is not None:
            plaza.embedding = None
            await self._db.flush()
        await self._db.execute(
            text("UPDATE pmcp_skill_plaza SET embedding_vec = NULL WHERE id = :id"),
            {"id": plaza_id},
        )


async def pgvector_available(db: AsyncSession) -> bool:
    """运行期探测 pgvector 扩展是否已安装（migration 007 在可装时 CREATE EXTENSION）。"""
    try:
        row = (await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))).first()
        return row is not None
    except Exception:  # 探测失败按不可用处理（降级 JSONB）
        return False


async def create_embedding_store(db: AsyncSession, backend: str | None = None) -> EmbeddingStore:
    """EmbeddingStore 工厂：按 settings + 运行期探测选后端，pgvector 不可用自动降级 JSONB（R-12）。"""
    s = get_settings().skill
    chosen = (backend or s.embedding_backend or "auto").lower()
    if chosen in ("auto", "pgvector"):
        if await pgvector_available(db):
            return PgVectorEmbeddingStore(db, s.embedding_dim)
        if chosen == "pgvector":
            logger.warning("pgvector 显式配置但运行期不可用，降级 JSONB+内存余弦（VNF-02/R-12）")
    return JsonbEmbeddingStore(db)
