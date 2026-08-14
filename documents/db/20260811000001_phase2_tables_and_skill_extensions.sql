-- =====================================================================
-- 003_phase2_tables_and_skill_extensions — 二期新增 6 表 + pmcp_skill 扩展 7 列
-- 生成方式：基于 alembic/versions/003_phase2_tables_and_skill_extensions.py
-- 适用场景：002 执行完成后追加
-- 前置条件：002 已执行（4 张废弃表已 DROP）
-- =====================================================================

-- ==================== pmcp_skill 扩展字段 ====================

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS source_path TEXT;
COMMENT ON COLUMN pmcp_skill.source_path IS '解压后包存储路径';

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS source_checksum VARCHAR(64);
COMMENT ON COLUMN pmcp_skill.source_checksum IS '上传包 SHA-256';

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS source_format VARCHAR(10);
COMMENT ON COLUMN pmcp_skill.source_format IS '包格式(7z/zip)';

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS version VARCHAR(32);
COMMENT ON COLUMN pmcp_skill.version IS 'Skill 版本';

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS audit_status VARCHAR(16);
COMMENT ON COLUMN pmcp_skill.audit_status IS '审计状态(pending/passed/failed/warning)';

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS audit_result JSONB;
COMMENT ON COLUMN pmcp_skill.audit_result IS '审计摘要（规则命中数、严重级别分布）';

ALTER TABLE pmcp_skill ADD COLUMN IF NOT EXISTS readme_generated BOOLEAN;
COMMENT ON COLUMN pmcp_skill.readme_generated IS '是否自动生成了 README.md';

-- ==================== pmcp_datasource_group ====================

CREATE TABLE IF NOT EXISTS pmcp_datasource_group (
    group_name VARCHAR(128) NOT NULL,
    description VARCHAR(512),
    env_code VARCHAR(32) NOT NULL,
    status SMALLINT DEFAULT '1' NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id)
);
COMMENT ON TABLE pmcp_datasource_group IS '数据源组';

-- ==================== pmcp_server_group ====================

CREATE TABLE IF NOT EXISTS pmcp_server_group (
    group_name VARCHAR(128) NOT NULL,
    description VARCHAR(512),
    env_code VARCHAR(32) NOT NULL,
    status SMALLINT DEFAULT '1' NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id)
);
COMMENT ON TABLE pmcp_server_group IS '服务器组';

-- ==================== pmcp_datasource_group_member ====================

CREATE TABLE IF NOT EXISTS pmcp_datasource_group_member (
    group_id BIGINT NOT NULL,
    datasource_id BIGINT NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT fk_ds_group_member_group_id FOREIGN KEY (group_id) REFERENCES pmcp_datasource_group(id),
    CONSTRAINT fk_ds_group_member_datasource_id FOREIGN KEY (datasource_id) REFERENCES pmcp_datasource(id)
);
COMMENT ON TABLE pmcp_datasource_group_member IS '数据源组成员';

CREATE INDEX IF NOT EXISTS idx_ds_group_member_group_id ON pmcp_datasource_group_member(group_id);
CREATE INDEX IF NOT EXISTS idx_ds_group_member_datasource_id ON pmcp_datasource_group_member(datasource_id);

-- ==================== pmcp_server_group_member ====================

CREATE TABLE IF NOT EXISTS pmcp_server_group_member (
    group_id BIGINT NOT NULL,
    server_id BIGINT NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT fk_srv_group_member_group_id FOREIGN KEY (group_id) REFERENCES pmcp_server_group(id),
    CONSTRAINT fk_srv_group_member_server_id FOREIGN KEY (server_id) REFERENCES pmcp_server(id)
);
COMMENT ON TABLE pmcp_server_group_member IS '服务器组成员';

CREATE INDEX IF NOT EXISTS idx_srv_group_member_group_id ON pmcp_server_group_member(group_id);
CREATE INDEX IF NOT EXISTS idx_srv_group_member_server_id ON pmcp_server_group_member(server_id);

-- ==================== pmcp_user_group ====================

CREATE TABLE IF NOT EXISTS pmcp_user_group (
    user_id BIGINT NOT NULL,
    group_type VARCHAR(32) NOT NULL,
    group_id BIGINT NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT fk_user_group_user_id FOREIGN KEY (user_id) REFERENCES pmcp_user(id)
);
COMMENT ON TABLE pmcp_user_group IS '用户-组关联';

CREATE INDEX IF NOT EXISTS idx_user_group_user_id ON pmcp_user_group(user_id);
CREATE INDEX IF NOT EXISTS idx_user_group_type_id ON pmcp_user_group(group_type, group_id);

-- ==================== pmcp_skill_audit_report ====================

CREATE TABLE IF NOT EXISTS pmcp_skill_audit_report (
    skill_id BIGINT NOT NULL,
    audit_time TIMESTAMP WITH TIME ZONE DEFAULT now(),
    auditor VARCHAR(64) NOT NULL DEFAULT 'system',
    rule_id VARCHAR(10) NOT NULL,
    severity VARCHAR(10) NOT NULL,
    file_path VARCHAR(512),
    line_number INTEGER,
    description TEXT,
    suggestion TEXT,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT fk_audit_report_skill_id FOREIGN KEY (skill_id) REFERENCES pmcp_skill(id)
);
COMMENT ON TABLE pmcp_skill_audit_report IS 'Skill 审计报告';

CREATE INDEX IF NOT EXISTS idx_audit_report_skill_id ON pmcp_skill_audit_report(skill_id);