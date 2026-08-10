export interface User {
  id: number
  username: string
  nickname: string | null
  email: string | null
  role_code: string
  api_key_prefix: string | null
  status: number
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
}

export interface Skill {
  id: number
  skill_code: string
  skill_name: string
  description: string | null
  status: string
  tool_count: number
  register_method: string
  submitted_by: string | null
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
