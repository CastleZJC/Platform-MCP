<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import request from "@/utils/request"
import { useUserStore } from "@/stores/user"
import Pagination from "@/components/Pagination.vue"
import type { AuditLog } from "@/types"

const { t } = useI18n()
const userStore = useUserStore()
const loading = ref(false)
const logs = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// 长字段内联样式 — inline style 优先级最高，绕过 Element Plus teleport/specificity 问题
const longFieldStyle = {
  margin: '0',
  padding: '8px 10px',
  background: '#f5f7fa',
  border: '1px solid #e4e7ed',
  borderRadius: '4px',
  fontSize: '13px',
  lineHeight: '1.6',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
  overflowWrap: 'anywhere',
  wordWrap: 'break-word',
  width: '100%',
  maxWidth: '100%',
  minWidth: '0',
  boxSizing: 'border-box',
  maxHeight: '280px',
  overflowY: 'auto',
  display: 'block',
} as const
const stats = ref({ total_operations: 0, mcp_calls: 0, sql_executions: 0, high_risk_blocks: 0, trends: { total_operations_vs_yesterday: null as number | null, mcp_calls_vs_yesterday: null as number | null, sql_executions_vs_yesterday: null as number | null, high_risk_blocks_vs_yesterday: null as number | null } })

const riskLevel = ref("")
const resultStatus = ref("")
const resourceType = ref("")
const resourceIdFilter = ref("")
const requestSummaryFilter = ref("")
const operatorFilter = ref("")
const dateRange = ref<string[]>(["", ""])
const datasourceOptions = ref<{datasource_code: string, datasource_name: string}[]>([])
const serverOptions = ref<{server_code: string, server_name: string}[]>([])

const detailVisible = ref(false)
const detailLog = ref<AuditLog | null>(null)

async function fetchStats() {
  const res = await request.get("/audit/stats")
  stats.value = res.data
}

async function fetchDatasources() {
  try {
    const res = await request.get("/datasources", { params: { page: 1, page_size: 200 } })
    datasourceOptions.value = (res.data.items || []).map((d: any) => ({
      datasource_code: d.datasource_code,
      datasource_name: d.datasource_name,
    }))
  } catch { /* ignore */ }
}

async function fetchServers() {
  try {
    const res = await request.get("/servers", { params: { page: 1, page_size: 200 } })
    serverOptions.value = (res.data.items || []).map((s: any) => ({
      server_code: s.server_code,
      server_name: s.server_name,
    }))
  } catch { /* ignore */ }
}

async function fetchLogs() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (resourceType.value) params.resource_type = resourceType.value
    if (resourceIdFilter.value) params.resource_id = resourceIdFilter.value
    if (requestSummaryFilter.value) params.request_summary = requestSummaryFilter.value
    if (riskLevel.value) params.risk_level = riskLevel.value
    if (resultStatus.value) params.result_status = resultStatus.value
    if (userStore.isAdmin && operatorFilter.value) params.operator = operatorFilter.value
    if (dateRange.value?.[0]) params.start_time = dateRange.value[0]
    if (dateRange.value?.[1]) params.end_time = dateRange.value[1]
    const res = await request.get("/audit/logs", { params })
    logs.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

function showDetail(log: AuditLog) {
  detailLog.value = log
  detailVisible.value = true
  fetchDetail(log.id)
}

async function fetchDetail(logId: number) {
  try {
    const res = await request.get(`/audit/logs/${logId}`)
    if (res.data) {
      detailLog.value = { ...detailLog.value, ...res.data }
    }
  } catch { /* use list data as fallback */ }
}

function riskTagClass(level: string | null) {
  const map: Record<string, string> = { LOW: "tag-success", MEDIUM: "tag-warning", HIGH: "tag-danger", CRITICAL: "tag-danger" }
  return map[level || ""] || "tag-info"
}
function statusTagClass(s: string | null) {
  return s === 'success' ? 'tag-success' : 'tag-danger'
}
function statusLabel(s: string | null) {
  if (s === 'success') return t("audit.statusSuccess")
  if (s === 'error' || s === 'fail') return t("audit.statusFailed")
  return s || '—'
}
function resourceTypeLabel(v: string | null) {
  const map: Record<string, string> = {
    auth: t("audit.typeAuth"),
    sql: t("audit.typeSql"), sql_exec: t("audit.typeSql"),
    shell: t("audit.typeShell"),
    datasource: t("audit.typeDatasource"),
    server: t("audit.typeServer"),
    user: t("audit.typeUser"), role: t("audit.typeUser"), permission: t("audit.typeUser"),
    crypto: t("audit.typeCrypto"),
    config: t("audit.typeConfig"), system: t("audit.typeConfig"),
    group: t("audit.typeGroup"),
    skill: t("audit.typeSkill"),
    notify: t("audit.typeNotify"),
  }
  return map[v || ""] || (v || "—")
}
function resourceTypeTagClass(v: string | null) {
  const map: Record<string, string> = {
    auth: "tag-primary",
    sql: "tag-info", sql_exec: "tag-info",
    shell: "tag-warning",
    datasource: "tag-success",
    server: "tag-info",
    user: "tag-info", role: "tag-info", permission: "tag-info",
    crypto: "tag-warning",
    config: "tag-info", system: "tag-info",
    group: "tag-success",
  }
  return map[v || ""] || "tag-info"
}
function trendClass(v: number | null | undefined): string {
  if (v == null || v === 0) return "flat"
  return v > 0 ? "up" : "down"
}
function trendText(v: number | null | undefined): string {
  if (v == null) return t("audit.trendNull")
  if (v === 0) return t("audit.trendZero")
  return t("audit.trendValue", { arrow: v > 0 ? "▲" : "▼", value: Math.abs(v) })
}

onMounted(() => { fetchStats(); fetchLogs(); fetchDatasources(); fetchServers() })
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("audit.title") }}</h2>
      <p>{{ t("audit.subtitle") }}</p>
    </div>
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-label">{{ t("audit.statMcp") }}</div>
        <div class="stat-value">{{ stats.mcp_calls }}</div>
        <div class="stat-trend" :class="trendClass(stats.trends.mcp_calls_vs_yesterday)">{{ trendText(stats.trends.mcp_calls_vs_yesterday) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t("audit.statSql") }}</div>
        <div class="stat-value">{{ stats.sql_executions }}</div>
        <div class="stat-trend" :class="trendClass(stats.trends.sql_executions_vs_yesterday)">{{ trendText(stats.trends.sql_executions_vs_yesterday) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t("audit.statHighRisk") }}</div>
        <div class="stat-value">{{ stats.high_risk_blocks }}</div>
        <div class="stat-trend" :class="trendClass(stats.trends.high_risk_blocks_vs_yesterday)">{{ trendText(stats.trends.high_risk_blocks_vs_yesterday) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">{{ t("audit.statTotal") }}</div>
        <div class="stat-value">{{ stats.total_operations }}</div>
        <div class="stat-trend" :class="trendClass(stats.trends.total_operations_vs_yesterday)">{{ trendText(stats.trends.total_operations_vs_yesterday) }}</div>
      </div>
    </div>
    <div class="card">
      <div class="filter-row">
        <label>{{ t("audit.filterTime") }}</label>
        <input type="date" class="form-input" style="width:150px;height:34px" v-model="dateRange[0]">
        <span style="color:var(--color-text-muted)">~</span>
        <input type="date" class="form-input" style="width:150px;height:34px" v-model="dateRange[1]">
        <template v-if="userStore.isAdmin">
          <label style="margin-left:8px">{{ t("audit.filterOperator") }}</label>
          <input type="text" class="search-input" style="width:140px" v-model="operatorFilter" :placeholder="t('audit.filterOperatorPlaceholder')" @keyup.enter="fetchLogs">
        </template>
        <label style="margin-left:8px">{{ t("audit.filterSummary") }}</label>
        <input type="text" class="search-input" style="width:200px" v-model="requestSummaryFilter" :placeholder="t('audit.filterSummaryPlaceholder')" @keyup.enter="fetchLogs">
      </div>
      <div class="filter-row" style="margin-top:8px">
        <label>{{ t("audit.filterType") }}</label>
        <select class="form-select" v-model="resourceType" @change="fetchLogs">
          <option value="">{{ t("common.allTypes") }}</option>
          <option value="auth">{{ t("audit.typeAuth") }}</option>
          <option value="sql">{{ t("audit.typeSql") }}</option>
          <option value="shell">{{ t("audit.typeShell") }}</option>
          <option value="datasource">{{ t("audit.typeDatasource") }}</option>
          <option value="server">{{ t("audit.typeServer") }}</option>
          <option value="permission">{{ t("audit.typeUser") }}</option>
          <option value="crypto">{{ t("audit.typeCrypto") }}</option>
          <option value="config">{{ t("audit.typeSkill") }}</option>
        </select>
        <label style="margin-left:8px">{{ t("audit.filterResource") }}</label>
        <select class="form-select" v-model="resourceIdFilter" @change="fetchLogs">
          <option value="">{{ t("audit.allResources") }}</option>
          <optgroup :label="t('audit.optgroupDatasources')">
            <option v-for="d in datasourceOptions" :key="d.datasource_code" :value="d.datasource_code">
              {{ d.datasource_code }} ({{ d.datasource_name }})
            </option>
          </optgroup>
          <optgroup :label="t('audit.optgroupServers')">
            <option v-for="s in serverOptions" :key="s.server_code" :value="s.server_code">
              {{ s.server_code }} ({{ s.server_name }})
            </option>
          </optgroup>
        </select>
        <label style="margin-left:8px">{{ t("audit.filterRisk") }}</label>
        <select class="form-select" v-model="riskLevel" @change="fetchLogs">
          <option value="">{{ t("audit.allLevels") }}</option><option value="LOW">LOW</option><option value="MEDIUM">MEDIUM</option><option value="HIGH">HIGH</option><option value="CRITICAL">CRITICAL</option>
        </select>
        <label style="margin-left:8px">{{ t("audit.filterStatus") }}</label>
        <select class="form-select" v-model="resultStatus" @change="fetchLogs">
          <option value="">{{ t("common.allStatus") }}</option><option value="success">{{ t("audit.statusSuccess") }}</option><option value="error">{{ t("audit.statusFailed") }}</option>
        </select>
        <button class="btn" style="margin-left:8px" @click="fetchLogs">{{ t("common.query") }}</button>
      </div>
      <table class="data-table" v-loading="loading">
        <thead><tr>
          <th>{{ t("audit.colTrace") }}</th><th>{{ t("audit.colOperator") }}</th><th>{{ t("audit.colType") }}</th><th>{{ t("audit.colSkillTool") }}</th><th>{{ t("audit.colResource") }}</th><th>{{ t("audit.colRisk") }}</th><th>{{ t("audit.colStatus") }}</th><th>{{ t("audit.colDuration") }}</th><th>{{ t("audit.colTime") }}</th><th>{{ t("audit.colActions") }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in logs" :key="row.id">
            <td class="text-mono" style="font-size:12px">{{ row.trace_id || '—' }}</td>
            <td>{{ row.operator }}</td>
            <td><span v-if="row.resource_type" class="tag" :class="resourceTypeTagClass(row.resource_type)">{{ resourceTypeLabel(row.resource_type) }}</span><span v-else>—</span></td>
            <td>{{ row.skill_name || '—' }} / {{ row.tool_name || '—' }}</td>
            <td>{{ row.resource_id || (row as any).env_code || '—' }}</td>
            <td><span v-if="row.risk_level" class="tag" :class="riskTagClass(row.risk_level)">{{ row.risk_level }}</span><span v-else>—</span></td>
            <td><span class="tag" :class="statusTagClass(row.result_status)">{{ statusLabel(row.result_status) }}</span></td>
            <td class="text-mono">{{ row.duration_ms }}ms</td>
            <td>{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</td>
            <td><button class="btn btn-sm" @click="showDetail(row)">{{ t("common.detail") }}</button></td>
          </tr>
          <tr v-if="!loading && logs.length === 0"><td colspan="10" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">{{ t("audit.empty") }}</td></tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchLogs" />
    </div>

    <el-dialog v-model="detailVisible" :title="t('audit.detailTitle')" width="640">
      <el-descriptions v-if="detailLog" :column="2" border>
        <el-descriptions-item label="Trace ID">{{ detailLog.trace_id }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.colOperator')">{{ detailLog.operator }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailSkill')">{{ detailLog.skill_name }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailTool')">{{ detailLog.tool_name }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailEnv')">{{ (detailLog as any).env_code || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.colRisk')">{{ detailLog.risk_level }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.colStatus')">{{ detailLog.result_status }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.colDuration')">{{ detailLog.duration_ms }} ms</el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailSummary')" :span="2"><span :style="longFieldStyle">{{ (detailLog as any).request_summary || '-' }}</span></el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailTime')">{{ detailLog.created_at }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailErrorCode')">{{ (detailLog as any).error_code || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('audit.detailError')" :span="2"><span :style="longFieldStyle">{{ detailLog.error_message || '-' }}</span></el-descriptions-item>
        <el-descriptions-item v-if="detailLog.extra_data" :label="t('audit.detailExtra')" :span="2"><span :style="longFieldStyle">{{ detailLog.extra_data }}</span></el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-trend.flat {
  color: var(--color-text-muted);
}
</style>
