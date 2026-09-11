-- migration 014 渲染：Skill 生命周期增强（版本链 / merge 工作台 / 多语言补足，head=014）

-- 1. 个人 Skill 记录复制来源广场版本（3-way merge base）+ 存量回填
ALTER TABLE pmcp_skill ADD COLUMN copied_from_plaza_version VARCHAR(64);
COMMENT ON COLUMN pmcp_skill.copied_from_plaza_version IS '复制来源广场版本（add-to-my 记录，3-way merge base）';
UPDATE pmcp_skill s SET copied_from_plaza_version = p.version
FROM pmcp_skill_plaza p WHERE s.plaza_id = p.id AND s.origin = 'PLAZA';

-- 2. 版本存档多语言补足产物
ALTER TABLE pmcp_skill_version ADD COLUMN readme_extra JSONB;
COMMENT ON COLUMN pmcp_skill_version.readme_extra IS '多语言 README 补足（{locale: text}，tier template<model<external）';
ALTER TABLE pmcp_skill_version ADD COLUMN report_extra JSONB;
COMMENT ON COLUMN pmcp_skill_version.report_extra IS '多语言审核报告补足（{locale: text}，tier template<model<external）';

-- 3. 广场版本归档记提交人来源版本
ALTER TABLE pmcp_plaza_version ADD COLUMN source_version VARCHAR(64);
COMMENT ON COLUMN pmcp_plaza_version.source_version IS '提交人版本（来源版本，不透传为广场版本）';

-- 4. merge 工作台 slim 表
CREATE TABLE pmcp_plaza_merge (
    id BIGSERIAL PRIMARY KEY,
    merge_token VARCHAR(64) NOT NULL,
    plaza_id BIGINT NOT NULL REFERENCES pmcp_skill_plaza(id) ON DELETE CASCADE,
    source_skills JSONB NOT NULL,
    base_version VARCHAR(64),
    new_version VARCHAR(64),
    conflicts JSONB,
    audit_summary JSONB,
    snapshot_path VARCHAR(512),
    status VARCHAR(16) NOT NULL DEFAULT 'BUILT',
    created_by VARCHAR(64) NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_by VARCHAR(64),
    updated_by VARCHAR(64),
    CONSTRAINT uq_pmcp_plaza_merge_token UNIQUE (merge_token)
);
COMMENT ON TABLE pmcp_plaza_merge IS '广场 merge 工作台（文件级并集 + admin 裁决，2026-09-10）';
COMMENT ON COLUMN pmcp_plaza_merge.merge_token IS '合并工作台令牌（build 返回，get_skill_file/publish 引用）';
COMMENT ON COLUMN pmcp_plaza_merge.source_skills IS '来源个人 Skill [{skill_id, role: primary|secondary}]';
COMMENT ON COLUMN pmcp_plaza_merge.conflicts IS '冲突清单 [{path, candidates, resolution}]';
COMMENT ON COLUMN pmcp_plaza_merge.status IS '状态(BUILT 已构建/PUBLISHED 已发布/DISCARDED 已丢弃)';
CREATE INDEX ix_pmcp_plaza_merge_plaza_id ON pmcp_plaza_merge (plaza_id);

-- 5. skill_review 默认模板补参数（仅默认文案行；param_descriptions 增量合并）
UPDATE pmcp_notify_group SET body_template =
    '操作人：{{user}}' || chr(10) ||
    '提交人：{{submitter}}' || chr(10) ||
    'Skill ID：{{skill_id}}' || chr(10) ||
    'Skill：{{resource}}' || chr(10) ||
    '版本：{{version}}' || chr(10) ||
    '动作：{{action}}' || chr(10) ||
    '时间：{{time}}' || chr(10) ||
    '说明：{{reason}}{{iteration_note}}' || chr(10) || chr(10) ||
    '-- Platform-MCP Skill 审核流（提审/审核结果/撤回自动触达）',
    param_descriptions = COALESCE(param_descriptions, '{}'::jsonb) || '{"skill_id": "Skill ID（个人库行）", "submitter": "提交人用户名", "version": "Skill 版本"}'::jsonb
WHERE notify_type = 'skill_review'
  AND subject_template = '【Platform-MCP】Skill 审核事件：{{resource}}（{{action}}）'
  AND body_template =
    '操作人：{{user}}' || chr(10) ||
    'Skill：{{resource}}' || chr(10) ||
    '动作：{{action}}' || chr(10) ||
    '时间：{{time}}' || chr(10) ||
    '说明：{{reason}}{{iteration_note}}' || chr(10) || chr(10) ||
    '-- Platform-MCP Skill 审核流（提审/审核结果/撤回自动触达）';
