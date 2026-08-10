-- 修正唯一约束命名 + 补充缺失索引
-- 遵循数据库脚本规范: un_表名_字段名 / idx_表名_字段名
-- 外键列必须建立索引

BEGIN;

-- ========================================
-- 1. 重命名唯一约束为规范格式
-- ========================================

ALTER TABLE pmcp_datasource
    RENAME CONSTRAINT pmcp_datasource_datasource_code_key TO un_pmcp_datasource_datasource_code;

ALTER TABLE pmcp_user
    RENAME CONSTRAINT pmcp_user_username_key TO un_pmcp_user_username;

ALTER TABLE pmcp_role
    RENAME CONSTRAINT pmcp_role_role_code_key TO un_pmcp_role_role_code;

ALTER TABLE pmcp_permission
    RENAME CONSTRAINT pmcp_permission_permission_code_key TO un_pmcp_permission_permission_code;

ALTER TABLE pmcp_skill
    RENAME CONSTRAINT pmcp_skill_skill_code_key TO un_pmcp_skill_skill_code;

ALTER TABLE pmcp_system_config
    RENAME CONSTRAINT pmcp_system_config_config_key_key TO un_pmcp_system_config_config_key;

-- ========================================
-- 2. 补充 pmcp_audit_log 索引
-- ========================================

CREATE INDEX idx_pmcp_audit_log_inserted_at ON pmcp_audit_log USING brin (inserted_at);
CREATE INDEX idx_pmcp_audit_log_operator ON pmcp_audit_log (operator);
CREATE INDEX idx_pmcp_audit_log_result_status ON pmcp_audit_log (result_status);
CREATE INDEX idx_pmcp_audit_log_trace_id ON pmcp_audit_log (trace_id);

-- ========================================
-- 3. 补充外键列索引
-- ========================================

CREATE INDEX idx_pmcp_user_role_user_id ON pmcp_user_role (user_id);
CREATE INDEX idx_pmcp_user_role_role_id ON pmcp_user_role (role_id);

CREATE INDEX idx_pmcp_role_permission_role_id ON pmcp_role_permission (role_id);
CREATE INDEX idx_pmcp_role_permission_permission_id ON pmcp_role_permission (permission_id);

CREATE INDEX idx_pmcp_datasource_permission_datasource_id ON pmcp_datasource_permission (datasource_id);
CREATE INDEX idx_pmcp_datasource_permission_user_id ON pmcp_datasource_permission (user_id);
CREATE INDEX idx_pmcp_datasource_permission_role_id ON pmcp_datasource_permission (role_id);

COMMIT;
