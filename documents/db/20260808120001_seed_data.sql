-- =====================================================================
-- pmcp-mcp 发布版初始 seed 数据 — DML（幂等）
-- 适用场景：fresh PG 部署，紧随 20260808120000_initial_schema.sql 执行
-- 命名规范：db/<yyyymmddHHMMSS>_<snake_case_desc>.sql（时间戳前缀）
-- 幂等性：所有 INSERT 使用 ON CONFLICT DO NOTHING，重复执行不报错
-- =====================================================================

-- 角色：admin / developer
INSERT INTO pmcp_role (role_name, role_code, status, remark)
VALUES ('系统管理员', 'admin', 1, NULL),
       ('开发人员', 'developer', 1, NULL)
ON CONFLICT (role_code) DO NOTHING;

-- 默认管理员用户：admin / admin123（bcrypt hash）
INSERT INTO pmcp_user (username, password, nickname, email, status)
VALUES ('admin', '$2b$12$BbcnlpLG9XY1tSJoTX75IOl6mFz1PWKven0kAE8ufaOZCs/gcD6XS', '系统管理员', NULL, 1)
ON CONFLICT (username) DO NOTHING;

-- admin → admin 角色映射
INSERT INTO pmcp_user_role (user_id, role_id)
SELECT u.id, r.id
FROM pmcp_user u, pmcp_role r
WHERE u.username = 'admin'
  AND r.role_code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM pmcp_user_role ur
    WHERE ur.user_id = u.id AND ur.role_id = r.id
  );
