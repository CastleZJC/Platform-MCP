-- =====================================================================
-- Platform-MCP V3.0 M5 — migration 009 渲染产物（fresh-install raw SQL）
-- 对应 alembic/versions/009_notify_tables.py
-- 内容：邮件组提醒（架构 §19.5.5 / 计划 5.1）
--   1. pmcp_notify_group      —— 四提醒事项组（notify_type 唯一 + 参数化模板 + enabled）
--   2. pmcp_notify_group_member —— 组成员（仅 admin 角色可入组，服务层录入校验）
--   3. pmcp_notify_outbox     —— 发件箱（pending/sent/failed + retry_count，F-38）
--   4. pmcp_user 加 failed_attempts / locked_until —— 连续登录失败锁定（5 次锁 15 分钟）
--   5. seed 四组默认中文模板（幂等：ON CONFLICT (notify_type) DO NOTHING，F-39）
--   迁移编号：原拆分口径 008=notify / 009=KB，因 008 被组去环境维度占用而顺延
--   （notify→009，KB→010，架构 §19.5.8 于 M6.3/F-42 终核）。
-- =====================================================================

BEGIN;

-- ==================== 1. 提醒事项组 ====================
CREATE TABLE pmcp_notify_group (
    notify_type        VARCHAR(32)  NOT NULL UNIQUE,
    group_name         VARCHAR(64)  NOT NULL,
    subject_template   TEXT         NOT NULL,
    body_template      TEXT         NOT NULL,
    param_descriptions JSONB        NULL,
    enabled            SMALLINT     NOT NULL DEFAULT 1,
    id                 BIGINT       NOT NULL PRIMARY KEY,
    inserted_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inserted_by        VARCHAR(64)  NULL,
    updated_by         VARCHAR(64)  NULL
);
COMMENT ON TABLE pmcp_notify_group IS '邮件提醒事项组（V3.0 M5）';
COMMENT ON COLUMN pmcp_notify_group.notify_type IS '提醒事项类型（db_high_op/server_high_op/skill_review/user_mgmt，架构 §19.5.5）';
COMMENT ON COLUMN pmcp_notify_group.group_name IS '组显示名';
COMMENT ON COLUMN pmcp_notify_group.subject_template IS '邮件主题模板（{{param}} 参数化）';
COMMENT ON COLUMN pmcp_notify_group.body_template IS '邮件正文模板（{{param}} 参数化）';
COMMENT ON COLUMN pmcp_notify_group.param_descriptions IS '模板参数说明（key→描述，可改）';
COMMENT ON COLUMN pmcp_notify_group.enabled IS '1-启用 0-停用（停用组静默，F-37）';

-- ==================== 2. 组成员（仅 admin 可入组——服务层录入校验；发送时 join 取当前邮箱）====================
CREATE TABLE pmcp_notify_group_member (
    group_id     BIGINT      NOT NULL REFERENCES pmcp_notify_group (id) ON DELETE CASCADE,
    user_id      BIGINT      NOT NULL REFERENCES pmcp_user (id) ON DELETE CASCADE,
    id           BIGINT      NOT NULL PRIMARY KEY,
    inserted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by  VARCHAR(64) NULL,
    updated_by   VARCHAR(64) NULL,
    CONSTRAINT uq_notify_group_member UNIQUE (group_id, user_id)
);
COMMENT ON TABLE pmcp_notify_group_member IS '邮件提醒组成员（仅 admin 角色用户，架构 §19.5.5）';

-- ==================== 3. 发件箱（outbox 模式：先落库后发送，失败可重试、全程可审计，F-38）====================
CREATE TABLE pmcp_notify_outbox (
    notify_type       VARCHAR(32)  NOT NULL,
    source            VARCHAR(32)  NOT NULL,
    recipient         VARCHAR(128) NOT NULL,
    recipient_user_id BIGINT       NULL,
    subject           TEXT         NOT NULL,
    body              TEXT         NOT NULL,
    status            VARCHAR(16)  NOT NULL DEFAULT 'pending',
    retry_count       INTEGER      NOT NULL DEFAULT 0,
    error_message     TEXT         NULL,
    sent_at           TIMESTAMPTZ  NULL,
    trace_id          VARCHAR(64)  NULL,
    id                BIGINT       NOT NULL PRIMARY KEY,
    inserted_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inserted_by       VARCHAR(64)  NULL,
    updated_by        VARCHAR(64)  NULL
);
COMMENT ON TABLE pmcp_notify_outbox IS '邮件发件箱（outbox 模式，V3.0 M5，F-38）';
COMMENT ON COLUMN pmcp_notify_outbox.notify_type IS '提醒事项类型';
COMMENT ON COLUMN pmcp_notify_outbox.source IS '捕捉点来源（audit_route/review/user_mgmt/lockout/test）';
COMMENT ON COLUMN pmcp_notify_outbox.recipient IS '收件人邮箱';
COMMENT ON COLUMN pmcp_notify_outbox.recipient_user_id IS '收件人用户 id（本人直发类可追溯）';
COMMENT ON COLUMN pmcp_notify_outbox.subject IS '渲染后主题';
COMMENT ON COLUMN pmcp_notify_outbox.body IS '渲染后正文';
COMMENT ON COLUMN pmcp_notify_outbox.status IS 'pending-待发 sent-已发 failed-失败可重试';
COMMENT ON COLUMN pmcp_notify_outbox.retry_count IS '已重试次数';
COMMENT ON COLUMN pmcp_notify_outbox.error_message IS '最近一次发送错误';
COMMENT ON COLUMN pmcp_notify_outbox.sent_at IS '发送成功时间';
COMMENT ON COLUMN pmcp_notify_outbox.trace_id IS '审计链 trace_id';
CREATE INDEX ix_notify_outbox_status ON pmcp_notify_outbox (status);

-- ==================== 4. 连续登录失败锁定字段（F-37 user_mgmt 捕捉点功能前提）====================
ALTER TABLE pmcp_user ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pmcp_user ADD COLUMN locked_until TIMESTAMPTZ NULL;
COMMENT ON COLUMN pmcp_user.failed_attempts IS '连续登录失败次数（成功登录清零）';
COMMENT ON COLUMN pmcp_user.locked_until IS '锁定截止时间（NULL=未锁定；5 次失败锁 15 分钟）';

-- ==================== 5. seed 四组默认模板（幂等）====================
INSERT INTO pmcp_notify_group (notify_type, group_name, subject_template, body_template, param_descriptions, enabled, inserted_by)
VALUES ('db_high_op', '生产高危数据库操作提醒组',
        '【Platform-MCP】生产高危数据库操作：{{resource}}（{{env}}）',
        E'操作人：{{user}}\n目标资源：{{resource}}\n环境：{{env}}\n风险等级：{{risk}}\n时间：{{time}}\n概要：{{summary}}\n\n-- Platform-MCP 审计路由（PROD + HIGH/CRITICAL 自动触达）',
        '{"user": "操作人用户名", "resource": "目标资源（数据源/服务器编码或 Skill 名/用户名）", "env": "环境编码（DEV/UAT/PROD）", "risk": "风险等级（LOW/MEDIUM/HIGH/CRITICAL）", "time": "事件时间", "summary": "请求概要", "reason": "说明 / 拒绝原因", "iteration_note": "迭代说明（merge）", "action": "动作（提交/通过/合并/拒绝/撤回/创建/停用/角色变更/Key 重置/锁定等）"}'::jsonb,
        1, 'system')
ON CONFLICT (notify_type) DO NOTHING;

INSERT INTO pmcp_notify_group (notify_type, group_name, subject_template, body_template, param_descriptions, enabled, inserted_by)
VALUES ('server_high_op', '生产高危服务器操作提醒组',
        '【Platform-MCP】生产高危服务器操作：{{resource}}（{{env}}）',
        E'操作人：{{user}}\n目标资源：{{resource}}\n环境：{{env}}\n风险等级：{{risk}}\n时间：{{time}}\n概要：{{summary}}\n\n-- Platform-MCP 审计路由（PROD + HIGH/CRITICAL 自动触达）',
        '{"user": "操作人用户名", "resource": "目标资源（数据源/服务器编码或 Skill 名/用户名）", "env": "环境编码（DEV/UAT/PROD）", "risk": "风险等级（LOW/MEDIUM/HIGH/CRITICAL）", "time": "事件时间", "summary": "请求概要", "reason": "说明 / 拒绝原因", "iteration_note": "迭代说明（merge）", "action": "动作（提交/通过/合并/拒绝/撤回/创建/停用/角色变更/Key 重置/锁定等）"}'::jsonb,
        1, 'system')
ON CONFLICT (notify_type) DO NOTHING;

INSERT INTO pmcp_notify_group (notify_type, group_name, subject_template, body_template, param_descriptions, enabled, inserted_by)
VALUES ('skill_review', 'Skill 审核提醒组',
        '【Platform-MCP】Skill 审核事件：{{resource}}（{{action}}）',
        E'操作人：{{user}}\nSkill：{{resource}}\n动作：{{action}}\n时间：{{time}}\n说明：{{reason}}{{iteration_note}}\n\n-- Platform-MCP Skill 审核流（提审/审核结果/撤回自动触达）',
        '{"user": "操作人用户名", "resource": "目标资源（数据源/服务器编码或 Skill 名/用户名）", "env": "环境编码（DEV/UAT/PROD）", "risk": "风险等级（LOW/MEDIUM/HIGH/CRITICAL）", "time": "事件时间", "summary": "请求概要", "reason": "说明 / 拒绝原因", "iteration_note": "迭代说明（merge）", "action": "动作（提交/通过/合并/拒绝/撤回/创建/停用/角色变更/Key 重置/锁定等）"}'::jsonb,
        1, 'system')
ON CONFLICT (notify_type) DO NOTHING;

INSERT INTO pmcp_notify_group (notify_type, group_name, subject_template, body_template, param_descriptions, enabled, inserted_by)
VALUES ('user_mgmt', '用户管理安全事件提醒组',
        '【Platform-MCP】用户管理安全事件：{{action}}',
        E'操作人：{{user}}\n相关用户：{{resource}}\n动作：{{action}}\n时间：{{time}}\n说明：{{reason}}\n\n-- Platform-MCP 用户管理安全事件（创建/停用/角色变更/Key 重置/锁定自动触达）',
        '{"user": "操作人用户名", "resource": "目标资源（数据源/服务器编码或 Skill 名/用户名）", "env": "环境编码（DEV/UAT/PROD）", "risk": "风险等级（LOW/MEDIUM/HIGH/CRITICAL）", "time": "事件时间", "summary": "请求概要", "reason": "说明 / 拒绝原因", "iteration_note": "迭代说明（merge）", "action": "动作（提交/通过/合并/拒绝/撤回/创建/停用/角色变更/Key 重置/锁定等）"}'::jsonb,
        1, 'system')
ON CONFLICT (notify_type) DO NOTHING;

COMMIT;
