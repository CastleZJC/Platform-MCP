-- =====================================================================
-- Platform-MCP V3.0 M3R — migration 008 渲染产物（fresh-install raw SQL）
-- 对应 alembic/versions/008_group_drop_env.py
-- 内容：pmcp_group 去环境维度（组与环境正交）
-- 说明：
--   1. 跨环境同名组合并：三类成员并入 id 最小的保留组（ON CONFLICT 去重），
--      再删除多余组行。
--   2. DROP UNIQUE(env_code, group_name) + DROP env_code → 新增 UNIQUE(group_name)。
--   背景：组只挂资源集合（一个组可同时含 DEV/UAT/PROD 资源），环境管控走资源
--   自身 env_code + 角色双项控制（developer 禁 PROD 等仍由 permission 层执行）。
--   迁移编号：本迁移为 M3R 后插入（占用原拆分口径的 notify 位），
--   notify→009，KB→010（架构 §19.5.8 编号于 M6.3/F-42 终核）。
-- =====================================================================

BEGIN;

-- ==================== 1. 跨环境同名组合并（成员并入 + 删多余组行）====================
INSERT INTO pmcp_group_user (group_id, user_id, inserted_by)
SELECT keep.id, dup_m.user_id, 'migration_008'
FROM pmcp_group_user dup_m
JOIN pmcp_group dup_g ON dup_g.id = dup_m.group_id
JOIN pmcp_group keep ON keep.group_name = dup_g.group_name AND keep.id < dup_g.id
ON CONFLICT (group_id, user_id) DO NOTHING;

INSERT INTO pmcp_group_datasource (group_id, datasource_id, inserted_by)
SELECT keep.id, dup_m.datasource_id, 'migration_008'
FROM pmcp_group_datasource dup_m
JOIN pmcp_group dup_g ON dup_g.id = dup_m.group_id
JOIN pmcp_group keep ON keep.group_name = dup_g.group_name AND keep.id < dup_g.id
ON CONFLICT (group_id, datasource_id) DO NOTHING;

INSERT INTO pmcp_group_server (group_id, server_id, inserted_by)
SELECT keep.id, dup_m.server_id, 'migration_008'
FROM pmcp_group_server dup_m
JOIN pmcp_group dup_g ON dup_g.id = dup_m.group_id
JOIN pmcp_group keep ON keep.group_name = dup_g.group_name AND keep.id < dup_g.id
ON CONFLICT (group_id, server_id) DO NOTHING;

DELETE FROM pmcp_group g WHERE EXISTS (
  SELECT 1 FROM pmcp_group k WHERE k.group_name = g.group_name AND k.id < g.id);

-- ==================== 2. 约束与列调整（组与环境正交）====================
ALTER TABLE pmcp_group DROP CONSTRAINT uq_pmcp_group_env_name;
ALTER TABLE pmcp_group DROP COLUMN env_code;
ALTER TABLE pmcp_group ADD CONSTRAINT uq_pmcp_group_name UNIQUE (group_name);

COMMIT;
