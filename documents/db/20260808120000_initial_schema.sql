-- =====================================================================
-- pmcp-mcp 发布版初始 schema — DDL
-- 生成方式：基于 alembic/versions/001_initial_tables.py（手写对齐 pg_dump 输出）
-- 验证方式：pg_dump diff vs 本地 pmcp_mcp 库（DIFF EMPTY，2026-08-08）
-- 适用场景：fresh PG 部署，可直接 `psql -f` 执行
-- 命名规范：db/<yyyymmddHHMMSS>_<snake_case_desc>.sql（时间戳前缀）
-- =====================================================================

CREATE TABLE pmcp_user (
    username VARCHAR(64) NOT NULL,
    password VARCHAR(128) NOT NULL,
    nickname VARCHAR(64),
    status SMALLINT DEFAULT '1' NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    email VARCHAR(128),
    PRIMARY KEY (id),
    CONSTRAINT un_pmcp_user_username UNIQUE (username)
);

CREATE TABLE pmcp_role (
    role_name VARCHAR(64) NOT NULL,
    role_code VARCHAR(64) NOT NULL,
    status SMALLINT DEFAULT '1' NOT NULL,
    remark VARCHAR(512),
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT un_pmcp_role_role_code UNIQUE (role_code)
);

CREATE TABLE pmcp_permission (
    permission_name VARCHAR(128) NOT NULL,
    permission_code VARCHAR(128) NOT NULL,
    resource_type VARCHAR(64),
    resource_path VARCHAR(256),
    parent_id BIGINT,
    status SMALLINT DEFAULT '1' NOT NULL,
    sort_order SMALLINT DEFAULT '0',
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT un_pmcp_permission_permission_code UNIQUE (permission_code)
);

CREATE TABLE pmcp_skill (
    skill_code VARCHAR(64) NOT NULL,
    skill_name VARCHAR(128) NOT NULL,
    description TEXT,
    status SMALLINT DEFAULT '1' NOT NULL,
    register_method VARCHAR(32),
    tool_count SMALLINT DEFAULT '0' NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT un_pmcp_skill_skill_code UNIQUE (skill_code)
);

CREATE TABLE pmcp_system_config (
    config_key VARCHAR(128) NOT NULL,
    config_value TEXT,
    config_type VARCHAR(32),
    description VARCHAR(512),
    status SMALLINT DEFAULT '1' NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT un_pmcp_system_config_config_key UNIQUE (config_key)
);

CREATE TABLE pmcp_datasource (
    datasource_code VARCHAR(64) NOT NULL,
    datasource_name VARCHAR(128) NOT NULL,
    db_type VARCHAR(32) NOT NULL,
    host VARCHAR(256) NOT NULL,
    port SMALLINT NOT NULL,
    instance_name VARCHAR(128),
    username VARCHAR(128) NOT NULL,
    encrypted_password VARCHAR(512),
    env_code VARCHAR(32) NOT NULL,
    status SMALLINT DEFAULT '1' NOT NULL,
    max_concurrent SMALLINT DEFAULT '5' NOT NULL,
    query_timeout SMALLINT DEFAULT '300' NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    remark VARCHAR(512),
    service_name VARCHAR(128),
    database VARCHAR(128),
    PRIMARY KEY (id),
    CONSTRAINT un_pmcp_datasource_datasource_code UNIQUE (datasource_code)
);

CREATE TABLE pmcp_server (
    server_code VARCHAR(64) NOT NULL,
    server_name VARCHAR(128) NOT NULL,
    host VARCHAR(256) NOT NULL,
    ssh_port SMALLINT DEFAULT '22' NOT NULL,
    username VARCHAR(128) NOT NULL,
    encrypted_password VARCHAR(512),
    encrypted_ssh_key TEXT,
    env_code VARCHAR(32) NOT NULL,
    status SMALLINT DEFAULT '1' NOT NULL,
    max_concurrent SMALLINT DEFAULT '3' NOT NULL,
    command_timeout SMALLINT DEFAULT '300' NOT NULL,
    allowed_paths TEXT,
    forbidden_paths TEXT,
    remark VARCHAR(512),
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT pmcp_server_server_code_key UNIQUE (server_code)
);
CREATE INDEX idx_pmcp_server_env_code ON pmcp_server (env_code);

CREATE TABLE pmcp_api_key (
    id BIGSERIAL NOT NULL,
    user_id BIGINT NOT NULL,
    key_hash VARCHAR(128) NOT NULL,
    key_prefix VARCHAR(16) NOT NULL,
    description VARCHAR(255),
    status INTEGER DEFAULT '1' NOT NULL,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    key_encrypted VARCHAR(512),
    FOREIGN KEY (user_id) REFERENCES pmcp_user (id) ON DELETE CASCADE,
    PRIMARY KEY (id)
);
CREATE INDEX idx_pmcp_api_key_user_id ON pmcp_api_key (user_id);
ALTER TABLE pmcp_api_key ADD CONSTRAINT un_pmcp_api_key_key_hash UNIQUE (key_hash);

CREATE TABLE pmcp_audit_log (
    trace_id VARCHAR(64),
    request_id VARCHAR(64),
    operator VARCHAR(64),
    skill_name VARCHAR(64),
    tool_name VARCHAR(64),
    resource_type VARCHAR(64),
    resource_id VARCHAR(128),
    env_code VARCHAR(32),
    request_summary TEXT,
    result_status VARCHAR(32),
    risk_level VARCHAR(16),
    error_code VARCHAR(32),
    error_message TEXT,
    duration_ms BIGINT,
    extra_data JSONB,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id)
);
CREATE INDEX idx_pmcp_audit_log_inserted_at ON pmcp_audit_log USING brin (inserted_at);
CREATE INDEX idx_pmcp_audit_log_operator ON pmcp_audit_log (operator);
CREATE INDEX idx_pmcp_audit_log_result_status ON pmcp_audit_log (result_status);
CREATE INDEX idx_pmcp_audit_log_trace_id ON pmcp_audit_log (trace_id);

CREATE TABLE pmcp_mcp_call_log (
    trace_id VARCHAR(64),
    tool_name VARCHAR(64),
    caller VARCHAR(128),
    datasource_code VARCHAR(64),
    env_code VARCHAR(32),
    input_summary TEXT,
    output_summary TEXT,
    result_status VARCHAR(32),
    error_code VARCHAR(32),
    error_message TEXT,
    duration_ms BIGINT,
    confirm_token VARCHAR(128),
    extra_data JSONB,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id)
);

CREATE TABLE pmcp_crypto_operation_log (
    operator VARCHAR(64),
    operation_type VARCHAR(32),
    datasource_code VARCHAR(64),
    algorithm VARCHAR(32),
    result_status VARCHAR(32),
    error_message TEXT,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    PRIMARY KEY (id)
);

CREATE TABLE pmcp_user_role (
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    FOREIGN KEY (role_id) REFERENCES pmcp_role (id),
    FOREIGN KEY (user_id) REFERENCES pmcp_user (id),
    PRIMARY KEY (id)
);
CREATE INDEX idx_pmcp_user_role_user_id ON pmcp_user_role (user_id);
CREATE INDEX idx_pmcp_user_role_role_id ON pmcp_user_role (role_id);

CREATE TABLE pmcp_role_permission (
    role_id BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    FOREIGN KEY (permission_id) REFERENCES pmcp_permission (id),
    FOREIGN KEY (role_id) REFERENCES pmcp_role (id),
    PRIMARY KEY (id)
);
CREATE INDEX idx_pmcp_role_permission_role_id ON pmcp_role_permission (role_id);
CREATE INDEX idx_pmcp_role_permission_permission_id ON pmcp_role_permission (permission_id);

CREATE TABLE pmcp_datasource_permission (
    datasource_id BIGINT NOT NULL,
    user_id BIGINT,
    role_id BIGINT,
    permission_type VARCHAR(32) NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    FOREIGN KEY (datasource_id) REFERENCES pmcp_datasource (id),
    FOREIGN KEY (role_id) REFERENCES pmcp_role (id),
    FOREIGN KEY (user_id) REFERENCES pmcp_user (id),
    PRIMARY KEY (id)
);
CREATE INDEX idx_pmcp_datasource_permission_datasource_id ON pmcp_datasource_permission (datasource_id);
CREATE INDEX idx_pmcp_datasource_permission_user_id ON pmcp_datasource_permission (user_id);
CREATE INDEX idx_pmcp_datasource_permission_role_id ON pmcp_datasource_permission (role_id);

CREATE TABLE pmcp_server_permission (
    server_id BIGINT NOT NULL,
    user_id BIGINT,
    role_id BIGINT,
    permission_type VARCHAR(32) NOT NULL,
    id BIGSERIAL NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    FOREIGN KEY (server_id) REFERENCES pmcp_server (id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES pmcp_role (id),
    FOREIGN KEY (user_id) REFERENCES pmcp_user (id),
    PRIMARY KEY (id)
);
CREATE INDEX idx_pmcp_server_permission_server_id ON pmcp_server_permission (server_id);

-- Alembic 版本表（标识当前 schema 在 alembic 链中的位置）
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO alembic_version (version_num) VALUES ('001');
