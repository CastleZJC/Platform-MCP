-- migration 012 渲染：pmcp_user 个人每页条数（V3.0 分页统一，head=012）
ALTER TABLE pmcp_user ADD COLUMN page_size INTEGER;
COMMENT ON COLUMN pmcp_user.page_size IS '个人每页条数(5/10/20/50/75/100，空=创建时系统默认)';

-- 存量用户回填默认 20：此后 sys.default_page_size 调整仅影响新创建用户
UPDATE pmcp_user SET page_size = 20 WHERE page_size IS NULL;
