-- =====================================================================
-- 004_code_nonempty_check_constraints — 编码列非空串 CHECK 约束
-- 生成方式：基于 alembic/versions/004_code_nonempty_check_constraints.py
-- 适用场景：003 执行完成后追加
-- BUG20260814134000 修复：server_code / datasource_code 仅 NOT NULL 无法拦截空串
-- =====================================================================

-- 上线前置检查（预期 0 行，否则约束创建失败需先清洗）：
-- SELECT id FROM pmcp_server WHERE server_code = '';
-- SELECT id FROM pmcp_datasource WHERE datasource_code = '';

ALTER TABLE pmcp_server ADD CONSTRAINT ck_pmcp_server_server_code_nonempty CHECK (server_code <> '');
ALTER TABLE pmcp_datasource ADD CONSTRAINT ck_pmcp_datasource_datasource_code_nonempty CHECK (datasource_code <> '');