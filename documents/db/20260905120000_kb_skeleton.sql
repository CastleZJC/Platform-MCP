-- =====================================================================
-- Platform-MCP V3.0 M6 — migration 010 渲染产物（fresh-install raw SQL）
-- 对应 alembic/versions/010_kb_skeleton.py
-- 内容：三期知识库骨架五表（架构 §19.6，V3.0 仅搭骨架，三期实现业务）
--   1. pmcp_kb        —— 主体（kb_type personal/shared + owner + status
--                        值域复用 review 8 状态，三期挂接 review 服务）
--   2. pmcp_kb_doc    —— 文档（源路径 + checksum + 原文）
--   3. pmcp_kb_chunk  —— 切片（chunking_strategy 7 枚举 + embedding JSONB，
--                        同 plaza 惯例：JSONB + 内存余弦降级；pgvector 原生
--                        列三期按生产环境条件创建，本迁移不建）
--   4. pmcp_kb_version—— 版本存档（双语字段同 pmcp_skill_version 惯例）
--   5. pmcp_kb_share  —— 分享与审核关联（merge_target_id + review_comment；
--                        审核流三期直接挂接 platform_mcp/review/，不另建）
-- 迁移编号：010 = 三期 KB 骨架（008 组去环境维度/009 notify 顺延后，
--   本迁移落地 head=010；编号一致性 F-42 于 M6.3 终核同步文档）。
-- =====================================================================

BEGIN;

-- ==================== 1. 知识库主体 ====================
CREATE TABLE pmcp_kb (
    kb_code      VARCHAR(64)  NOT NULL,
    kb_name      VARCHAR(128) NOT NULL,
    kb_type      VARCHAR(16)  NOT NULL DEFAULT 'personal',
    owner_id     BIGINT       NULL REFERENCES pmcp_user (id) ON DELETE SET NULL,
    description  TEXT         NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'DRAFT',
    id           BIGSERIAL    NOT NULL PRIMARY KEY,
    inserted_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inserted_by  VARCHAR(64)  NULL,
    updated_by   VARCHAR(64)  NULL
);
COMMENT ON TABLE pmcp_kb IS '知识库主体（V3.0 M6 骨架，三期实现，架构 §19.6）';
COMMENT ON COLUMN pmcp_kb.kb_type IS '类型（personal-个人 / shared-专用可分享，架构 §19.6）';
COMMENT ON COLUMN pmcp_kb.owner_id IS '所有者用户 ID（个人库归属；shared 库发起人）';
COMMENT ON COLUMN pmcp_kb.status IS '状态（值域复用 review 8 状态，三期挂接 platform_mcp/review/ 状态机）';
ALTER TABLE pmcp_kb ADD CONSTRAINT uq_pmcp_kb_code UNIQUE (kb_code);
ALTER TABLE pmcp_kb ADD CONSTRAINT ck_pmcp_kb_code_nonempty CHECK (kb_code <> '');
ALTER TABLE pmcp_kb ADD CONSTRAINT ck_pmcp_kb_name_nonempty CHECK (kb_name <> '');
ALTER TABLE pmcp_kb ADD CONSTRAINT ck_pmcp_kb_type_domain CHECK (kb_type IN ('personal', 'shared'));
ALTER TABLE pmcp_kb ADD CONSTRAINT ck_pmcp_kb_status_nonempty CHECK (status <> '');

-- ==================== 2. 文档 ====================
CREATE TABLE pmcp_kb_doc (
    kb_id        BIGINT        NOT NULL REFERENCES pmcp_kb (id) ON DELETE CASCADE,
    doc_name     VARCHAR(256)  NOT NULL,
    source_path  TEXT          NULL,
    checksum     VARCHAR(64)   NULL,
    content      TEXT          NULL,
    id           BIGSERIAL     NOT NULL PRIMARY KEY,
    inserted_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    inserted_by  VARCHAR(64)   NULL,
    updated_by   VARCHAR(64)   NULL
);
COMMENT ON TABLE pmcp_kb_doc IS '知识库文档（V3.0 M6 骨架）';
COMMENT ON COLUMN pmcp_kb_doc.source_path IS '源文件存储路径（三期导入链路）';
COMMENT ON COLUMN pmcp_kb_doc.checksum IS '源文件 SHA-256';
COMMENT ON COLUMN pmcp_kb_doc.content IS '文档原文内容';
ALTER TABLE pmcp_kb_doc ADD CONSTRAINT ck_pmcp_kb_doc_name_nonempty CHECK (doc_name <> '');
CREATE INDEX ix_kb_doc_kb_id ON pmcp_kb_doc (kb_id);

-- ==================== 3. 切片（RAG 检索单元）====================
CREATE TABLE pmcp_kb_chunk (
    doc_id             BIGINT       NOT NULL REFERENCES pmcp_kb_doc (id) ON DELETE CASCADE,
    chunk_index        INTEGER      NOT NULL,
    chunking_strategy  VARCHAR(32)  NOT NULL,
    content            TEXT         NOT NULL,
    embedding          JSONB        NULL,
    id                 BIGSERIAL    NOT NULL PRIMARY KEY,
    inserted_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inserted_by        VARCHAR(64)  NULL,
    updated_by         VARCHAR(64)  NULL
);
COMMENT ON TABLE pmcp_kb_chunk IS '知识库切片（V3.0 M6 骨架，RAG 检索单元）';
COMMENT ON COLUMN pmcp_kb_chunk.chunk_index IS '文档内切片序号（从 0 起）';
COMMENT ON COLUMN pmcp_kb_chunk.chunking_strategy IS '切片策略（7 种枚举，值域由 platform_mcp/kb/chunking.py 把守，架构 §19.6）';
COMMENT ON COLUMN pmcp_kb_chunk.embedding IS '切片语义向量（BGE-M3 / 降级哈希；JSONB 存储 + 内存余弦，同 plaza 惯例）';
ALTER TABLE pmcp_kb_chunk ADD CONSTRAINT uq_pmcp_kb_chunk_doc_idx UNIQUE (doc_id, chunk_index);
ALTER TABLE pmcp_kb_chunk ADD CONSTRAINT ck_pmcp_kb_chunk_strategy_nonempty CHECK (chunking_strategy <> '');

-- ==================== 4. 版本存档（双语同 Skill 版本表惯例）====================
CREATE TABLE pmcp_kb_version (
    kb_id           BIGINT       NOT NULL REFERENCES pmcp_kb (id) ON DELETE CASCADE,
    version         VARCHAR(32)  NOT NULL,
    checksum        VARCHAR(64)  NULL,
    readme_zh       TEXT         NULL,
    readme_en       TEXT         NULL,
    report_zh       TEXT         NULL,
    report_en       TEXT         NULL,
    audit_snapshot  JSONB        NULL,
    generated_by    VARCHAR(16)  NULL,
    id              BIGSERIAL    NOT NULL PRIMARY KEY,
    inserted_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inserted_by     VARCHAR(64)  NULL,
    updated_by      VARCHAR(64)  NULL
);
COMMENT ON TABLE pmcp_kb_version IS '知识库版本化双语存档（V3.0 M6 骨架，同 Skill 版本表惯例）';
COMMENT ON COLUMN pmcp_kb_version.checksum IS '该版本内容 SHA-256';
COMMENT ON COLUMN pmcp_kb_version.audit_snapshot IS '该版本审计快照';
COMMENT ON COLUMN pmcp_kb_version.generated_by IS '产物来源（template/model/external，同 Skill 版本表惯例）';
ALTER TABLE pmcp_kb_version ADD CONSTRAINT uq_pmcp_kb_version_kb_ver UNIQUE (kb_id, version);
ALTER TABLE pmcp_kb_version ADD CONSTRAINT ck_pmcp_kb_version_nonempty CHECK (version <> '');

-- ==================== 5. 分享与审核关联 ====================
CREATE TABLE pmcp_kb_share (
    kb_id            BIGINT      NOT NULL REFERENCES pmcp_kb (id) ON DELETE CASCADE,
    shared_by        BIGINT      NULL REFERENCES pmcp_user (id) ON DELETE SET NULL,
    review_status    VARCHAR(16) NOT NULL,
    merge_target_id  BIGINT      NULL REFERENCES pmcp_kb (id) ON DELETE SET NULL,
    review_comment   TEXT        NULL,
    id               BIGSERIAL   NOT NULL PRIMARY KEY,
    inserted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by      VARCHAR(64) NULL,
    updated_by       VARCHAR(64) NULL
);
COMMENT ON TABLE pmcp_kb_share IS '知识库分享与审核关联（V3.0 M6 骨架，审核流复用 platform_mcp/review/）';
COMMENT ON COLUMN pmcp_kb_share.review_status IS '分享审核状态（PENDING_REVIEW/APPROVED/MERGED/REJECTED/WITHDRAWN 子集，review 服务把守）';
COMMENT ON COLUMN pmcp_kb_share.merge_target_id IS '合并目标知识库 ID（admin 合并到已有 shared 库时填写）';
COMMENT ON COLUMN pmcp_kb_share.review_comment IS '审核意见（拒绝原因/迭代说明）';
ALTER TABLE pmcp_kb_share ADD CONSTRAINT ck_pmcp_kb_share_status_nonempty CHECK (review_status <> '');
CREATE INDEX ix_kb_share_kb_id ON pmcp_kb_share (kb_id);

COMMIT;
