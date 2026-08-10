-- 删除未使用的死字段
ALTER TABLE pmcp_datasource DROP COLUMN IF EXISTS connection_string;
ALTER TABLE pmcp_datasource DROP COLUMN IF EXISTS extra_config;
ALTER TABLE pmcp_user DROP COLUMN IF EXISTS remark;
