-- =====================================================================
-- Platform-MCP V3.0 M0 — migration 005 渲染产物（fresh-install raw SQL）
-- 对应 alembic/versions/005_unified_group_roles_locale_skill_status.py
-- 内容：统一组模型（4 表 + 存量回填 + DROP 旧组 5 表）
--       + pmcp_user.locale + pmcp_role seed 'user' + pmcp_skill.status 转 varchar
-- 回滚前数据备份：documents/db/backup/（本地专用，不入库）
-- =====================================================================

BEGIN;

-- ==================== 1. 统一组 4 表 ====================
CREATE TABLE pmcp_group (
    group_name VARCHAR(128) NOT NULL,
    description VARCHAR(512),
    env_code VARCHAR(32) NOT NULL,
    status SMALLINT NOT NULL DEFAULT 1,
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_group_env_name UNIQUE (env_code, group_name)
);
COMMENT ON TABLE pmcp_group IS '统一组（组员+数据源+服务器多对多，V3.0）';

CREATE TABLE pmcp_group_user (
    group_id BIGINT NOT NULL REFERENCES pmcp_group(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES pmcp_user(id) ON DELETE CASCADE,
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_group_user_pair UNIQUE (group_id, user_id)
);
COMMENT ON TABLE pmcp_group_user IS '统一组组员（用户）关联';
CREATE INDEX idx_pmcp_group_user_group_id ON pmcp_group_user (group_id);
CREATE INDEX idx_pmcp_group_user_user_id ON pmcp_group_user (user_id);

CREATE TABLE pmcp_group_datasource (
    group_id BIGINT NOT NULL REFERENCES pmcp_group(id) ON DELETE CASCADE,
    datasource_id BIGINT NOT NULL REFERENCES pmcp_datasource(id) ON DELETE CASCADE,
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_group_datasource_pair UNIQUE (group_id, datasource_id)
);
COMMENT ON TABLE pmcp_group_datasource IS '统一组成员（数据源）关联';
CREATE INDEX idx_pmcp_group_datasource_group_id ON pmcp_group_datasource (group_id);
CREATE INDEX idx_pmcp_group_datasource_datasource_id ON pmcp_group_datasource (datasource_id);

CREATE TABLE pmcp_group_server (
    group_id BIGINT NOT NULL REFERENCES pmcp_group(id) ON DELETE CASCADE,
    server_id BIGINT NOT NULL REFERENCES pmcp_server(id) ON DELETE CASCADE,
    id BIGSERIAL NOT NULL PRIMARY KEY,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_group_server_pair UNIQUE (group_id, server_id)
);
COMMENT ON TABLE pmcp_group_server IS '统一组成员（服务器）关联';
CREATE INDEX idx_pmcp_group_server_group_id ON pmcp_group_server (group_id);
CREATE INDEX idx_pmcp_group_server_server_id ON pmcp_group_server (server_id);

-- ==================== 2. 存量回填（同 env 同名合并） ====================
-- 数据源组先入统一组
INSERT INTO pmcp_group (group_name, description, env_code, status, inserted_by, inserted_at, updated_at)
SELECT g.group_name, g.description, g.env_code, g.status, g.inserted_by, now(), now()
FROM pmcp_datasource_group g
ON CONFLICT (env_code, group_name) DO NOTHING;

INSERT INTO pmcp_group_datasource (group_id, datasource_id, inserted_by)
SELECT ng.id, m.datasource_id, ng.inserted_by
FROM pmcp_datasource_group g
JOIN pmcp_group ng ON ng.group_name = g.group_name AND ng.env_code = g.env_code
JOIN pmcp_datasource_group_member m ON m.group_id = g.id
ON CONFLICT (group_id, datasource_id) DO NOTHING;

-- 服务器组按"同 env 同名合并"：已存在则复用，否则新建
INSERT INTO pmcp_group (group_name, description, env_code, status, inserted_by, inserted_at, updated_at)
SELECT s.group_name, s.description, s.env_code, s.status, s.inserted_by, now(), now()
FROM pmcp_server_group s
ON CONFLICT (env_code, group_name) DO NOTHING;

INSERT INTO pmcp_group_server (group_id, server_id, inserted_by)
SELECT ng.id, m.server_id, ng.inserted_by
FROM pmcp_server_group s
JOIN pmcp_group ng ON ng.group_name = s.group_name AND ng.env_code = s.env_code
JOIN pmcp_server_group_member m ON m.group_id = s.id
ON CONFLICT (group_id, server_id) DO NOTHING;

-- 用户-组关联（两类合并去重）
INSERT INTO pmcp_group_user (user_id, group_id, inserted_by)
SELECT ug.user_id, ng.id, ug.inserted_by FROM pmcp_user_group ug
JOIN pmcp_datasource_group dg ON ug.group_type = 'datasource' AND ug.group_id = dg.id
JOIN pmcp_group ng ON ng.group_name = dg.group_name AND ng.env_code = dg.env_code
ON CONFLICT (group_id, user_id) DO NOTHING;

INSERT INTO pmcp_group_user (user_id, group_id, inserted_by)
SELECT ug.user_id, ng.id, ug.inserted_by FROM pmcp_user_group ug
JOIN pmcp_server_group sg ON ug.group_type = 'server' AND ug.group_id = sg.id
JOIN pmcp_group ng ON ng.group_name = sg.group_name AND ng.env_code = sg.env_code
ON CONFLICT (group_id, user_id) DO NOTHING;

-- ==================== 3. DROP 旧组 5 表 ====================
DROP TABLE pmcp_datasource_group_member;
DROP TABLE pmcp_server_group_member;
DROP TABLE pmcp_user_group;
DROP TABLE pmcp_datasource_group;
DROP TABLE pmcp_server_group;

-- ==================== 4. pmcp_user.locale ====================
ALTER TABLE pmcp_user ADD COLUMN locale VARCHAR(8);
COMMENT ON COLUMN pmcp_user.locale IS '界面语言(zh-CN/en-US，空=跟随系统默认)';

-- ==================== 5. pmcp_role seed 第三角色 ====================
INSERT INTO pmcp_role (role_name, role_code, status, remark) VALUES
('一般用户', 'user', 1, 'V3.0：无 database/server 权限，有 Skill 创建分享与广场权限')
ON CONFLICT (role_code) DO NOTHING;

-- ==================== 6. pmcp_skill.status SMALLINT → VARCHAR(16) ====================
ALTER TABLE pmcp_skill ALTER COLUMN status DROP DEFAULT;
ALTER TABLE pmcp_skill ALTER COLUMN status TYPE VARCHAR(16)
    USING CASE status WHEN 1 THEN 'ENABLED' WHEN 2 THEN 'PENDING_REVIEW'
        WHEN 3 THEN 'REJECTED' ELSE 'DISABLED' END;
COMMENT ON COLUMN pmcp_skill.status IS 'Skill 状态(ENABLED/PENDING_REVIEW/REJECTED/DISABLED，V3.0 M2 扩展 8 状态)';
ALTER TABLE pmcp_skill ALTER COLUMN status SET DEFAULT 'ENABLED';

COMMIT;
