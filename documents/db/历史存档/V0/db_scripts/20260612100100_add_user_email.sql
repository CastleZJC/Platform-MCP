-- 用户表新增邮箱字段 + 数据源表新增备注字段
ALTER TABLE pmcp_user ADD COLUMN email character varying(128);
COMMENT ON COLUMN pmcp_user.email IS '邮箱地址';

ALTER TABLE pmcp_datasource ADD COLUMN remark character varying(512);
COMMENT ON COLUMN pmcp_datasource.remark IS '备注';
