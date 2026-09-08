-- migration 013 渲染：pmcp_plaza_version 广场版本归档（仅广场 Skill 文件级版本管理，head=013）
CREATE TABLE pmcp_plaza_version (
    id BIGSERIAL PRIMARY KEY,
    plaza_id BIGINT NOT NULL REFERENCES pmcp_skill_plaza(id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    snapshot_path TEXT,
    file_manifest JSONB,
    checksum VARCHAR(64),
    audit_snapshot JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_plaza_version_plaza_ver UNIQUE (plaza_id, version)
);
COMMENT ON TABLE pmcp_plaza_version IS 'Skill 广场版本归档（仅广场 Skill 版本管理；个人/系统 Skill 仅最新版）';
COMMENT ON COLUMN pmcp_plaza_version.snapshot_path IS '版本快照目录（{upload_dir}/_plaza_versions/{plaza_id}/{version}）';
COMMENT ON COLUMN pmcp_plaza_version.file_manifest IS '文件清单 [{path,size,sha256}]';
CREATE INDEX ix_pmcp_plaza_version_plaza_id ON pmcp_plaza_version (plaza_id);
