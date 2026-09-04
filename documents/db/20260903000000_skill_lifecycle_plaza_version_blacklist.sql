-- =====================================================================
-- Platform-MCP V3.0 M2 — migration 006 渲染产物（fresh-install raw SQL）
-- 对应 alembic/versions/006_skill_lifecycle_plaza_version_blacklist.py
-- 内容：Skill 生命周期三表（plaza 广场公共池 / version 版本化双语存档 / blacklist 黑名单）
--       + pmcp_skill 加列 plaza_id / origin / share_status / review_comment
-- 说明：plaza.embedding 列（BGE-M3 语义搜索）按架构 §19.5.8 留待 migration 007 追加，本脚本不建。
-- =====================================================================

BEGIN;

-- ==================== 1. 广场公共池 ====================
CREATE TABLE pmcp_skill_plaza (
    skill_code VARCHAR(64) NOT NULL,
    skill_name VARCHAR(128) NOT NULL,
    description TEXT,
    version VARCHAR(32),
    uploader_id BIGINT REFERENCES pmcp_user(id) ON DELETE SET NULL,
    involve_flags JSONB,
    iteration_note TEXT,
    source_path TEXT,
    source_checksum VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'PUBLISHED',
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_skill_plaza_skill_code UNIQUE (skill_code)
);
COMMENT ON TABLE pmcp_skill_plaza IS 'Skill 广场公共池（独立于个人库，V3.0）';
COMMENT ON COLUMN pmcp_skill_plaza.skill_code IS '广场 Skill 编码';
COMMENT ON COLUMN pmcp_skill_plaza.version IS '当前发布版本（独立 version 链）';
COMMENT ON COLUMN pmcp_skill_plaza.uploader_id IS '分享者用户 ID';
COMMENT ON COLUMN pmcp_skill_plaza.involve_flags IS '涉库/涉服务器标记（audit R2/R3 派生，M3）';
COMMENT ON COLUMN pmcp_skill_plaza.iteration_note IS 'admin 合并迭代说明';
COMMENT ON COLUMN pmcp_skill_plaza.status IS '广场状态(PUBLISHED/DISABLED)';

-- ==================== 2. 版本化双语存档 ====================
CREATE TABLE pmcp_skill_version (
    skill_id BIGINT NOT NULL REFERENCES pmcp_skill(id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    checksum VARCHAR(64),
    readme_zh TEXT,
    readme_en TEXT,
    report_zh TEXT,
    report_en TEXT,
    audit_snapshot JSONB,
    generated_by VARCHAR(16),
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_skill_version_skill_ver UNIQUE (skill_id, version),
    CONSTRAINT ck_pmcp_skill_version_nonempty CHECK (version <> '')
);
COMMENT ON TABLE pmcp_skill_version IS 'Skill 版本化双语存档（README/审核报告/审计快照，V3.0 M2）';
COMMENT ON COLUMN pmcp_skill_version.version IS '版本号（如 0.1.0）';
COMMENT ON COLUMN pmcp_skill_version.checksum IS '该版本源码包 SHA-256';
COMMENT ON COLUMN pmcp_skill_version.readme_zh IS '中文 README（存档不可篡改）';
COMMENT ON COLUMN pmcp_skill_version.report_zh IS '中文审核报告（合规规则命中 + 广场比对结论）';
COMMENT ON COLUMN pmcp_skill_version.audit_snapshot IS '该版本审计快照（规则命中摘要）';
COMMENT ON COLUMN pmcp_skill_version.generated_by IS '产物来源(template/model，架构 §19.5.6)';
CREATE INDEX idx_pmcp_skill_version_skill_id ON pmcp_skill_version (skill_id);

-- ==================== 3. 黑名单 ====================
CREATE TABLE pmcp_skill_blacklist (
    user_id BIGINT NOT NULL REFERENCES pmcp_user(id) ON DELETE CASCADE,
    target_plaza_id BIGINT REFERENCES pmcp_skill_plaza(id) ON DELETE CASCADE,
    target_skill_id BIGINT REFERENCES pmcp_skill(id) ON DELETE CASCADE,
    reason VARCHAR(512),
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_skill_blacklist_plaza UNIQUE (user_id, target_plaza_id),
    CONSTRAINT uq_pmcp_skill_blacklist_skill UNIQUE (user_id, target_skill_id),
    CONSTRAINT ck_pmcp_skill_blacklist_has_target CHECK (target_plaza_id IS NOT NULL OR target_skill_id IS NOT NULL)
);
COMMENT ON TABLE pmcp_skill_blacklist IS 'Skill 黑名单（用户屏蔽，双端不可见仅黑名单页可见，V3.0 M2）';
COMMENT ON COLUMN pmcp_skill_blacklist.user_id IS '屏蔽发起用户 ID';
COMMENT ON COLUMN pmcp_skill_blacklist.target_plaza_id IS '屏蔽的广场 Skill ID';
COMMENT ON COLUMN pmcp_skill_blacklist.target_skill_id IS '屏蔽的个人 Skill ID';
CREATE INDEX idx_pmcp_skill_blacklist_user_id ON pmcp_skill_blacklist (user_id);

-- ==================== 4. pmcp_skill 加列：plaza_id / origin / share_status / review_comment ====================
ALTER TABLE pmcp_skill ADD COLUMN plaza_id BIGINT REFERENCES pmcp_skill_plaza(id) ON DELETE SET NULL;
COMMENT ON COLUMN pmcp_skill.plaza_id IS '关联广场副本 ID';
ALTER TABLE pmcp_skill ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'ORIGINAL';
COMMENT ON COLUMN pmcp_skill.origin IS '来源(ORIGINAL 原创/PLAZA 广场复制)';
ALTER TABLE pmcp_skill ADD COLUMN share_status VARCHAR(16) NOT NULL DEFAULT 'unshared';
COMMENT ON COLUMN pmcp_skill.share_status IS '分享状态(unshared 未分享/shared 已入广场)';
ALTER TABLE pmcp_skill ADD COLUMN review_comment TEXT;
COMMENT ON COLUMN pmcp_skill.review_comment IS '最近一次审核意见(admin approve/merge/reject 决策，owner 可见)';
ALTER TABLE pmcp_skill ADD CONSTRAINT ck_pmcp_skill_origin CHECK (origin IN ('ORIGINAL', 'PLAZA'));
ALTER TABLE pmcp_skill ADD CONSTRAINT ck_pmcp_skill_share_status CHECK (share_status IN ('unshared', 'shared'));
CREATE INDEX idx_pmcp_skill_plaza_id ON pmcp_skill (plaza_id);

COMMIT;
