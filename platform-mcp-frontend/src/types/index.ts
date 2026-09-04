export interface User {
  id: number
  username: string
  nickname: string | null
  email: string | null
  role_code: string
  api_key_prefix: string | null
  status: number
  locale?: string | null
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

export interface SkillAuditRule {
  rule_id: string
  severity: string
  file_path: string | null
  line_number: number | null
  description: string
  suggestion: string | null
}

// V3.0 M2.7（F-28）：版本化存档条目（双语 README / 审核报告，不可篡改）
export interface SkillVersion {
  version: string
  checksum: string | null
  generated_by: string | null
  readme_zh: string | null
  readme_en: string | null
  report_zh: string | null
  report_en: string | null
  audit_snapshot: Record<string, unknown> | null
  created_at: string | null
}

export interface SkillVersionsResponse {
  skill_id: number
  skill_code: string
  current_version: string | null
  versions: SkillVersion[]
}

export interface SkillAuditReportResponse {
  skill_id: number
  skill_code: string
  audit_status: string | null
  audit_summary: Record<string, unknown> | null
  reports: SkillAuditRule[]
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
  users: { id: number; username: string; nickname: string | null }[]
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
