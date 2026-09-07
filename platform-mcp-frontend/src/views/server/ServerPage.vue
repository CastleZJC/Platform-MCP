<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import type { FormInstance, FormRules } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Group, Server } from "@/types"
import { useUserStore } from "@/stores/user"

const { t } = useI18n()
const userStore = useUserStore()
const loading = ref(false)
const servers = ref<Server[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(userStore.pageSize)
const search = ref("")
const envFilter = ref("")
const statusFilter = ref<number | string>("")

const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref(0)
const form = ref({
  server_code: "",
  server_name: "",
  host: "",
  ssh_port: 22,
  username: "",
  encrypted_password: "",
  encrypted_ssh_key: "",
  env_code: "DEV",
  max_concurrent: 3,
  command_timeout: 300,
  allowed_paths_text: "",
  forbidden_paths_text: "",
  remark: "",
})
const testing = ref(false)
const formRef = ref<FormInstance>()
const rules = computed<FormRules>(() => ({
  server_code: [{ required: true, whitespace: true, message: t("server.ruleCode"), trigger: "blur" }],
  server_name: [{ required: true, whitespace: true, message: t("server.ruleName"), trigger: "blur" }],
  host: [{ required: true, whitespace: true, message: t("server.ruleHost"), trigger: "blur" }],
  username: [{ required: true, whitespace: true, message: t("server.ruleUsername"), trigger: "blur" }],
}))

function pathsToText(p: string | null): string {
  if (!p) return ""
  try {
    const arr = JSON.parse(p)
    return Array.isArray(arr) ? arr.join("\n") : ""
  } catch {
    return ""
  }
}

function textToPaths(text: string): string | null {
  const arr = text.split("\n").map(s => s.trim()).filter(Boolean)
  return arr.length ? JSON.stringify(arr) : null
}

async function fetchServers() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (envFilter.value) params.env_code = envFilter.value
    if (statusFilter.value !== "") params.status = statusFilter.value
    const res = await request.get("/servers", { params })
    servers.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  form.value = {
    server_code: "", server_name: "", host: "", ssh_port: 22, username: "",
    encrypted_password: "", encrypted_ssh_key: "", env_code: "DEV",
    max_concurrent: 3, command_timeout: 300,
    allowed_paths_text: "", forbidden_paths_text: "", remark: "",
  }
  dialogVisible.value = true
}

function openEdit(srv: Server) {
  isEdit.value = true
  editId.value = srv.id
  form.value = {
    server_code: srv.server_code,
    server_name: srv.server_name,
    host: srv.host,
    ssh_port: srv.ssh_port,
    username: srv.username,
    encrypted_password: "",
    encrypted_ssh_key: "",
    env_code: srv.env_code,
    max_concurrent: srv.max_concurrent,
    command_timeout: srv.command_timeout,
    allowed_paths_text: pathsToText(srv.allowed_paths),
    forbidden_paths_text: pathsToText(srv.forbidden_paths),
    remark: srv.remark || "",
  }
  dialogVisible.value = true
}

const isBlank = (v: string | number | null | undefined) =>
  v === null || v === undefined || String(v).trim() === ""

async function handleSubmit() {
  if (
    isBlank(form.value.server_code) || isBlank(form.value.server_name) ||
    isBlank(form.value.host) || isBlank(form.value.username)
  ) {
    ElMessage.error(t("server.requiredError"))
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const payload: Record<string, unknown> = {
    server_code: form.value.server_code,
    server_name: form.value.server_name,
    host: form.value.host,
    ssh_port: form.value.ssh_port,
    username: form.value.username,
    env_code: form.value.env_code,
    max_concurrent: form.value.max_concurrent,
    command_timeout: form.value.command_timeout,
    allowed_paths: textToPaths(form.value.allowed_paths_text),
    forbidden_paths: textToPaths(form.value.forbidden_paths_text),
    remark: form.value.remark || null,
  }
  if (form.value.encrypted_password) payload.encrypted_password = form.value.encrypted_password
  if (form.value.encrypted_ssh_key) payload.encrypted_ssh_key = form.value.encrypted_ssh_key

  if (isEdit.value) {
    await request.put(`/servers/${editId.value}`, payload)
  } else {
    await request.post("/servers", payload)
  }
  ElMessage.success(t("common.saveSuccess"))
  dialogVisible.value = false
  fetchServers()
}

async function handleStatus(srv: Server, status: number) {
  await request.put(`/servers/${srv.id}/status`, { status })
  ElMessage.success(t("common.statusUpdated"))
  fetchServers()
}

async function handleTest(srv: Server) {
  testing.value = true
  try {
    const res = await request.post(`/servers/${srv.id}/test`)
    if (res.data.success) {
      ElMessage.success(t("server.connectSuccess", { ms: res.data.latency_ms }))
    } else {
      ElMessage.error(t("server.connectFailed", { message: res.data.message }))
    }
  } catch {
    /* handled by interceptor */
  } finally {
    testing.value = false
  }
}

function envTagClass(env: string) {
  return env === "PROD" ? "tag-danger" : "tag-primary"
}

function authBadge(srv: Server) {
  if (srv.has_ssh_key) return "SSH Key"
  if (srv.has_password) return "Password"
  return "—"
}

// V3.0 统一组：所属组列 + admin 行级"新增分组"（幂等 diff 增删，不动组内其他成员）
const groups = ref<Group[]>([])
const groupDialogVisible = ref(false)
const groupTarget = ref<Server | null>(null)
const groupSelectIds = ref<number[]>([])

async function openGroupDialog(srv: Server) {
  groupTarget.value = srv
  groupDialogVisible.value = true
  const [groupsRes, membershipRes] = await Promise.all([
    request.get("/groups", { params: { page: 1, page_size: 100 } }),
    request.get("/groups/resource-membership", { params: { resource: "server", resource_id: srv.id } }),
  ])
  groups.value = groupsRes.data.items || []
  groupSelectIds.value = membershipRes.data.group_ids || []
}

async function handleGroupSubmit() {
  if (!groupTarget.value) return
  await request.put("/groups/resource-membership", {
    resource: "server",
    resource_id: groupTarget.value.id,
    group_ids: groupSelectIds.value,
  })
  ElMessage.success(t("common.groupUpdated"))
  groupDialogVisible.value = false
  fetchServers()
}

onMounted(fetchServers)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("server.title") }}</h2>
      <p>{{ t("server.subtitle") }}</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" :placeholder="t('server.searchPlaceholder')" @keyup.enter="fetchServers">
          <select class="form-select" v-model="envFilter" @change="fetchServers">
            <option value="">{{ t("common.allEnvs") }}</option>
            <option value="DEV">DEV</option>
            <option value="UAT">UAT</option>
            <option value="PROD">PROD</option>
          </select>
          <select class="form-select" v-model="statusFilter" @change="fetchServers">
            <option value="">{{ t("common.allStatus") }}</option>
            <option :value="1">{{ t("common.enabled") }}</option>
            <option :value="0">{{ t("common.disabled") }}</option>
          </select>
          <button class="btn" @click="fetchServers">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <button v-if="userStore.isAdmin" class="btn btn-primary" @click="openCreate">{{ t("server.add") }}</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead>
          <tr>
            <th>{{ t("server.colCode") }}</th>
            <th>{{ t("server.colName") }}</th>
            <th>{{ t("server.colEnv") }}</th>
            <th>{{ t("server.colGroups") }}</th>
            <th>{{ t("server.colHost") }}</th>
            <th>{{ t("server.colSshPort") }}</th>
            <th>{{ t("server.colUser") }}</th>
            <th>{{ t("server.colAuth") }}</th>
            <th>{{ t("server.colStatus") }}</th>
            <th>{{ t("server.colRemark") }}</th>
            <th>{{ t("server.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in servers" :key="row.id">
            <td class="text-mono">{{ row.server_code }}</td>
            <td>{{ row.server_name }}</td>
            <td><span class="tag" :class="envTagClass(row.env_code)">{{ row.env_code }}</span></td>
            <td>
              <span v-for="g in row.groups || []" :key="g" class="tag tag-info" style="margin-right:4px">{{ g }}</span>
              <span v-if="!(row.groups || []).length" style="color:var(--color-text-muted)">—</span>
            </td>
            <td class="text-mono">{{ row.host }}</td>
            <td class="text-mono">{{ row.ssh_port }}</td>
            <td class="text-mono">{{ row.username }}</td>
            <td>{{ authBadge(row) }}</td>
            <td><span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">{{ row.status === 1 ? t("common.enabled") : t("common.disabled") }}</span></td>
            <td>{{ row.remark || '—' }}</td>
            <td class="actions">
              <button class="btn btn-sm btn-success" @click="handleTest(row)" :disabled="testing">{{ t("common.test") }}</button>
              <button v-if="userStore.isAdmin" class="btn btn-sm" @click="openEdit(row)">{{ t("common.edit") }}</button>
              <button v-if="userStore.isAdmin" class="btn btn-sm" @click="openGroupDialog(row)">{{ t("common.assignGroup") }}</button>
              <button v-if="userStore.isAdmin && row.status === 1" class="btn btn-sm btn-danger" @click="handleStatus(row, 0)">{{ t("common.disable") }}</button>
              <button v-if="userStore.isAdmin && row.status === 0" class="btn btn-sm btn-primary" @click="handleStatus(row, 1)">{{ t("common.enable") }}</button>
            </td>
          </tr>
          <tr v-if="!loading && servers.length === 0">
            <td colspan="11" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">{{ t("server.empty") }}</td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchServers" />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? t('server.dialogEdit') : t('server.dialogCreate')" width="640">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item :label="t('server.labelCode')" prop="server_code"><el-input v-model="form.server_code" :disabled="isEdit" :placeholder="t('server.placeholderCode')" /></el-form-item>
        <el-form-item :label="t('server.labelName')" prop="server_name"><el-input v-model="form.server_name" /></el-form-item>
        <el-form-item :label="t('server.labelEnv')">
          <el-select v-model="form.env_code">
            <el-option label="DEV" value="DEV" />
            <el-option label="UAT" value="UAT" />
            <el-option label="PROD" value="PROD" :disabled="!userStore.isAdmin" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('server.labelHost')" prop="host"><el-input v-model="form.host" :placeholder="t('server.placeholderHost')" /></el-form-item>
        <el-form-item :label="t('server.labelSshPort')"><el-input-number v-model="form.ssh_port" :min="1" :max="65535" /></el-form-item>
        <el-form-item :label="t('server.labelUsername')" prop="username"><el-input v-model="form.username" /></el-form-item>
        <el-form-item :label="t('server.labelPassword')"><el-input v-model="form.encrypted_password" :placeholder="t('server.placeholderPassword')" /></el-form-item>
        <el-form-item :label="t('server.labelSshKey')"><el-input v-model="form.encrypted_ssh_key" type="textarea" :rows="3" :placeholder="t('server.placeholderSshKey')" /></el-form-item>
        <el-form-item :label="t('server.labelMaxConcurrent')"><el-input-number v-model="form.max_concurrent" :min="1" :max="20" /></el-form-item>
        <el-form-item :label="t('server.labelTimeout')"><el-input-number v-model="form.command_timeout" :min="10" :max="3600" /></el-form-item>
        <el-form-item :label="t('server.labelAllowedPaths')"><el-input v-model="form.allowed_paths_text" type="textarea" :rows="3" :placeholder="t('server.placeholderAllowedPaths')" /></el-form-item>
        <el-form-item :label="t('server.labelForbiddenPaths')"><el-input v-model="form.forbidden_paths_text" type="textarea" :rows="2" :placeholder="t('server.placeholderForbiddenPaths')" /></el-form-item>
        <el-form-item :label="t('server.labelRemark')"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="handleSubmit">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="groupDialogVisible" :title="t('server.groupDialogTitle', { code: groupTarget?.server_code || '' })" width="520">
      <p style="color:#666;font-size:13px;margin-bottom:8px">{{ t("server.groupDialogHint") }}</p>
      <el-select v-model="groupSelectIds" multiple filterable :placeholder="t('common.groupSelectPlaceholder')" style="width:100%">
        <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="t('common.groupOption', { name: g.group_name })" />
      </el-select>
      <template #footer>
        <el-button @click="groupDialogVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="handleGroupSubmit">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
</style>
