-- ==================== migration 011 渲染（V3.0 M5 补丁）====================
-- notify 模板参数说明双重编码修复：009 seed 经 alembic 执行的环境（本地/开发），
-- param_descriptions 被写成 JSON 字符串标量（json.dumps + JSONB 绑定类型二次序列化），
-- 前端模板编辑弹窗逐字符遍历显示"参数 = {{0}}，说明 = {"。
-- 发布版 SQL（本目录 20260905000000_notify_tables.sql）seed 本就是对象，执行本脚本为幂等空操作。
-- 应用后：head = 011

BEGIN;

UPDATE pmcp_notify_group
SET param_descriptions = (param_descriptions #>> '{}')::jsonb,
    updated_at = now()
WHERE param_descriptions IS NOT NULL
  AND jsonb_typeof(param_descriptions) = 'string';

COMMIT;
