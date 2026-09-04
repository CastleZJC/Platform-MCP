-- =====================================================================
-- Platform-MCP V3.0 M3 — migration 007 渲染产物（fresh-install raw SQL）
-- 对应 alembic/versions/007_plaza_embedding.py
-- 内容：pmcp_skill_plaza 加 embedding JSONB 列（BGE-M3 语义搜索向量，架构 §19.5.6）
-- 说明：
--   1. embedding JSONB —— 规范存储 + 内存余弦降级路径（VNF-02），无扩展依赖，始终创建。
--   2. embedding_vec vector(1024) —— pgvector 原生列（DB 侧余弦 <=>），仅生产可装 vector
--      扩展时启用（见下方可选段）；不可装则跳过，EmbeddingStore 运行期自动降级 JSONB（R-12）。
--   迁移编号：M3 独占 007（embedding），M5 notify→008，M6 KB→009（架构 §19.5.8 编号于 M6.3/F-42 同步）。
-- =====================================================================

BEGIN;

-- ==================== 1. JSONB 向量列（始终创建，降级路径）====================
ALTER TABLE pmcp_skill_plaza ADD COLUMN embedding JSONB;
COMMENT ON COLUMN pmcp_skill_plaza.embedding IS 'Skill 语义向量（BGE-M3 / 降级哈希；JSONB 存储 + 内存余弦，架构 §19.5.6 / VNF-02）';

COMMIT;

-- ==================== 2. pgvector 原生列（可选：仅生产可装 vector 扩展时执行）====================
-- 目标库无法安装 pgvector 时跳过本段，EmbeddingStore 工厂自动降级为 JSONB+内存余弦（R-12/VNF-02）。
-- 执行前确认：SELECT 1 FROM pg_available_extensions WHERE name = 'vector'; 有记录。
-- BEGIN;
-- CREATE EXTENSION IF NOT EXISTS vector;
-- ALTER TABLE pmcp_skill_plaza ADD COLUMN embedding_vec vector(1024);
-- COMMENT ON COLUMN pmcp_skill_plaza.embedding_vec IS 'pgvector 原生向量列（DB 侧余弦 <=>，架构 §19.5.6）';
-- COMMIT;
