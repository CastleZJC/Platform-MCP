export interface User {
  id: number
  username: string
  nickname: string | null
  email: string | null
  role_code: string
  api_key_prefix: string | null
  status: number
  locale?: string | null
  page_size?: number | null
  created_at?: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  trace_id: string
  timestamp: number
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface Datasource {
  id: number
  datasource_code: string
  datasource_name: string
  db_type: string
  env_code: string
  host: string
  port: number
  instance_name: string | null
  service_name: string | null
  database: string | null
  username: string
  status: number
  max_concurrent: number
  query_timeout: number
  remark: string | null
  created_at: string
  groups?: string[]
}

export interface Server {
  id: number
  server_code: string
  server_name: string
  host: string
  ssh_port: number
  username: string
  env_code: string
  status: number
  max_concurrent: number
  command_timeout: number
  allowed_paths: string | null
  forbidden_paths: string | null
  remark: string | null
  has_password: boolean
  has_ssh_key: boolean
  created_at: string
  groups?: string[]
}

export interface Skill {
  id: number
  skill_code: string
  skill_name: string
  description: string | null
  status: string
  tool_count: number
  tool_names?: string[]
  register_method: string
  submitted_by: string | null
  source_format: string | null
  version: string | null
  audit_status: string | null
  readme_generated: boolean | null
  created_at: string
  // V3.0 M2.7：8 状态生命周期 + 广场分享联动字段（list_skills 返回）
  share_status?: string | null
  origin?: string | null
  plaza_id?: number | null
  review_comment?: string | null
}

// V3.0 M2.7（F-28）：版本化存档条目（双语 README / 审核报告，不可篡改）
// 批次 5.2：readme_extra / report_extra 为其他语言补档（{locale: text}，zh/en 走主列）
export interface SkillVersion {
  version: string
  checksum: string | null
  generated_by: string | null
  readme_zh: string | null
  readme_en: string | null
  readme_extra?: Record<string, string> | null
  report_zh: string | null
  report_en: string | null
  report_extra?: Record<string, string> | null
  audit_snapshot: Record<string, unknown> | null
  created_at: string | null
}

export interface SkillVersionsResponse {
  skill_id: number
  skill_code: string
  current_version: string | null
  versions: SkillVersion[]
}

// V3.0 M4.3（F-30）：分享迭代差异（本地 vs 广场快照 SKILL.md，行级 diff + 语义相似度 + 双语描述）
export interface SkillIterationDiff {
  unified_diff: string
  local_lines: number
  plaza_lines: number
  added_lines: number
  removed_lines: number
  identical: boolean
  similarity: number
  description_zh: string
  description_en: string
  generated_by: string
  performance_hint_zh: string | null
  performance_hint_en: string | null
}

// 批次 7：待审提交（GET /skills/pending，admin 审核工作台视图；name_match 为广场同名/功能相似裁决）
export interface NameMatchItem {
  plaza_id: number
  skill_code: string
  skill_name: string
  version: string | null
  similarity: number
  same_name: boolean
  verdict: "merge" | "reject_ref" | "merge_candidate"
}

export interface PendingSkill {
  id: number
  skill_code: string
  skill_name: string
  description: string | null
  status: string
  register_method: string
  submitted_by: string | null
  created_at: string | null
  version: string | null
  origin: string | null
  plaza_id: number | null
  audit_status: string | null
  review_comment: string | null
  name_match: NameMatchItem[]
}

// 审核文件预览（GET /skills/{id}/files：无 path 清单 / 带 path 单文件内容）
export interface SkillFileEntry {
  path: string
  size: number
}

export interface SkillFilesResponse {
  skill_id: number
  skill_code: string
  files: SkillFileEntry[]
}

export interface SkillFileContent {
  path: string
  size: number
  sha256: string
  encoding: string
  content: string
}

// V3.0 M3.1：Skill 广场公共池（独立于个人库，全角色可见；一般用户不见涉库/涉服务器项，F-23）
export interface PlazaUploader {
  username: string
  nickname: string | null
}

export interface PlazaSkill {
  plaza_id: number
  skill_code: string
  skill_name: string
  description: string | null
  version: string | null
  involve_flags: string[]
  iteration_note: string | null
  status: string
  uploader: PlazaUploader | null
  created_at: string | null
  updated_at: string | null
  similarity?: number
  blocked?: boolean
}

export interface PlazaSearchResponse {
  query: string
  total: number
  items: PlazaSkill[]
}

// 广场 Skill 双语 README（GET /plaza/{id}/readme，前端按 locale 选 zh/en）
export interface PlazaReadme {
  plaza_id: number
  skill_code: string
  skill_name: string
  readme_zh: string | null
  readme_en: string | null
}

// merge 工作台（设计定稿④，2026-09-10）：build 产物与冲突候选（与后端 serialize_merge 同构）
export interface MergeAuditSummary {
  passed?: boolean
  critical_count?: number
  warning_count?: number
  suggestion_count?: number
}

export interface MergeCandidate {
  source_skill_id: number | null // null = 基线（广场当前/历史快照）
  skill_code: string
  role: "primary" | "secondary" | "base"
  sha256: string
  size: number
}

export interface MergeConflict {
  path: string
  candidates: MergeCandidate[]
  default_source_skill_id: number
  resolution?: number | "base" | null
}

export interface MergeSourceSkill {
  skill_id: number
  skill_code: string
  skill_name: string
  role: string
  version: string | null
  submitted_by: string
}

export interface MergeBuildResult {
  merge_token: string
  plaza_id: number
  source_skills: MergeSourceSkill[]
  base_version: string
  new_version: string
  conflicts: MergeConflict[] | null
  audit_summary: MergeAuditSummary | null
  snapshot_path?: string
  status: string
  created_by?: string
  created_at?: string | null
  holders_marked?: number
  message_hint?: string
}

// 广场版本条目（GET /plaza/{id}/versions，批次4 回滚复用）
export interface PlazaVersionItem {
  plaza_id: number
  version: string
  source_version: string | null
  snapshot_path: string
  file_count: number
  checksum: string
  audit_passed: boolean | null
  created_at: string | null
}

// 黑名单条目（GET /plaza/blocked，target_type 区分广场/个人 Skill，F-34）
export interface BlockedSkill {
  id: number
  target_type: "plaza" | "skill"
  target_id: number | null
  skill_code: string | null
  skill_name: string | null
  reason: string | null
  created_at: string | null
}

export interface Group {
  id: number
  group_name: string
  description: string | null
  status: number
  user_count: number
  datasource_count: number
  server_count: number
  user_names?: string[]
  datasource_names?: string[]
  server_names?: string[]
  created_at: string
}

export interface GroupMembers {
  group_id: number
  group_name: string
  users: { id: number; username: string; nickname: string | null; role_code: string }[]
  datasources: { id: number; datasource_code: string; datasource_name: string; db_type: string; env_code: string }[]
  servers: { id: number; server_code: string; server_name: string; host: string; env_code: string }[]
}

export interface SystemConfig {
  id: number
  config_key: string
  config_value: string
  config_type: string
  description: string | null
  status: number
  created_at: string
}

export interface AuditLog {
  id: number
  trace_id: string
  operator: string
  skill_name: string | null
  tool_name: string | null
  resource_type: string | null
  resource_id: string | null
  env_code: string | null
  request_summary: string | null
  risk_level: string | null
  result_status: string
  error_code: string | null
  duration_ms: number | null
  error_message: string | null
  extra_data: Record<string, unknown> | null
  created_at: string
}
