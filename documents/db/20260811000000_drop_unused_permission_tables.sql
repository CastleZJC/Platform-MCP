-- =====================================================================
-- 002_drop_unused_permission_tables — 二期清理：DROP 4 张 V1.0 遗留空表
-- 生成方式：基于 alembic/versions/002_drop_unused_permission_tables.py
-- 适用场景：从 V1.0 升级到 V2.0（在 003 之前执行）
-- 前置条件：001 初始 schema 已部署
-- =====================================================================

-- 1. pmcp_server_permission（依赖 pmcp_server, pmcp_user, pmcp_role）
DROP INDEX IF EXISTS idx_pmcp_server_permission_server_id;
DROP TABLE IF EXISTS pmcp_server_permission;

-- 2. pmcp_datasource_permission（依赖 pmcp_datasource, pmcp_user, pmcp_role）
DROP INDEX IF EXISTS idx_pmcp_datasource_permission_datasource_id;
DROP INDEX IF EXISTS idx_pmcp_datasource_permission_user_id;
DROP INDEX IF EXISTS idx_pmcp_datasource_permission_role_id;
DROP TABLE IF EXISTS pmcp_datasource_permission;

-- 3. pmcp_role_permission（依赖 pmcp_role, pmcp_permission）
DROP INDEX IF EXISTS idx_pmcp_role_permission_role_id;
DROP INDEX IF EXISTS idx_pmcp_role_permission_permission_id;
DROP TABLE IF EXISTS pmcp_role_permission;

-- 4. pmcp_permission（无外键依赖，子表已删）
-- un_pmcp_permission_permission_code 是 UNIQUE 约束索引，DROP TABLE 会级联删除
DROP TABLE IF EXISTS pmcp_permission;