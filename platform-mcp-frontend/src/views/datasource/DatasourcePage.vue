<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import type { FormInstance, FormRules } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Datasource, Group } from "@/types"
import { useUserStore } from "@/stores/user"

const { t } = useI18n()
const userStore = useUserStore()
const loading = ref(false)
const datasources = ref<Datasource[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")
const dbTypeFilter = ref("")
const envFilter = ref("")
const statusFilter = ref<number | string>("")

const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref(0)
const form = ref({
  datasource_code: "", datasource_name: "", db_type: "oracle", env_code: "DEV",
  host: "", port: 1521, instance_name: "", service_name: "", database: "",
  username: "", encrypted_password: "",
  max_concurrent: 5, query_timeout: 300, remark: "",
})
const testing = ref(false)
const formRef = ref<FormInstance>()
const rules = computed<FormRules>(() => ({
  datasource_code: [{ required: true, whitespace: true, message: t("datasource.ruleCode"), trigger: "blur" }],
  datasource_name: [{ required: true, whitespace: true, message: t("datasource.ruleName"), trigger: "blur" }],
  host: [{ required: true, whitespace: true, message: t("datasource.ruleHost"), trigger: "blur" }],
  username: [{ required: true, whitespace: true, message: t("datasource.ruleUsername"), trigger: "blur" }],
}))

async function fetchDatasources() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (dbTypeFilter.value) params.db_type = dbTypeFilter.value
    if (envFilter.value) params.env_code = envFilter.value
    if (statusFilter.value !== "") params.status = statusFilter.value
    const res = await request.get("/datasources", { params })
    datasources.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

function openCreate() {
  isEdit.value = false
  form.value = { datasource_code: "", datasource_name: "", db_type: "oracle", env_code: "DEV", host: "", port: 1521, instance_name: "", service_name: "", database: "", username: "", encrypted_password: "", max_concurrent: 5, query_timeout: 300, remark: "" }
  dialogVisible.value = true
}

function openEdit(ds: Datasource) {
  isEdit.value = true
  editId.value = ds.id
  form.value = { datasource_code: ds.datasource_code, datasource_name: ds.datasource_name, db_type: ds.db_type, env_code: ds.env_code, host: ds.host, port: ds.port, instance_name: ds.instance_name || "", service_name: ds.service_name || "", database: ds.database || "", username: ds.username, encrypted_password: "", max_concurrent: ds.max_concurrent, query_timeout: ds.query_timeout, remark: ds.remark || "" }
  dialogVisible.value = true
}

const isBlank = (v: string | number | null | undefined) =>
  v === null || v === undefined || String(v).trim() === ""

async function handleSubmit() {
  if (
    isBlank(form.value.datasource_code) || isBlank(form.value.datasource_name) ||
    isBlank(form.value.host) || isBlank(form.value.username)
  ) {
    ElMessage.error(t("datasource.requiredError"))
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (isEdit.value) {
    await request.put(`/datasources/${editId.value}`, form.value)
  } else {
    await request.post("/datasources", form.value)
  }
  ElMessage.success(t("common.saveSuccess"))
  dialogVisible.value = false
  fetchDatasources()
}

async function handleStatus(ds: Datasource, status: number) {
  await request.put(`/datasources/${ds.id}/status`, { status })
  ElMessage.success(t("common.statusUpdated"))
  fetchDatasources()
}

async function handleTest(ds: Datasource) {
  testing.value = true
  try {
    const res = await request.post(`/datasources/${ds.id}/test`)
    if (res.data.success) {
      ElMessage.success(t("datasource.connectSuccess", { ms: res.data.latency_ms }))
    } else {
      ElMessage.error(t("datasource.connectFailed", { message: res.data.message }))
    }
  } catch { /* handled by interceptor */ }
  finally { testing.value = false }
}

function dbTypeTagClass(v: string) { return v === 'oracle' ? 'tag-warning' : 'tag-info' }
function dbTypeLabel(v: string) { return v === 'oracle' ? 'Oracle 11g' : 'MySQL 5.6' }
function envTagClass(env: string) { return env === 'PROD' ? 'tag-danger' : 'tag-primary' }

// V3.0 统一组：所属组列 + admin 行级"新增分组"（幂等 diff 增删，不动组内其他成员）
const groups = ref<Group[]>([])
const groupDialogVisible = ref(false)
const groupTarget = ref<Datasource | null>(null)
const groupSelectIds = ref<number[]>([])

async function openGroupDialog(ds: Datasource) {
  groupTarget.value = ds
  groupDialogVisible.value = true
  const [groupsRes, membershipRes] = await Promise.all([
    request.get("/groups", { params: { page: 1, page_size: 100 } }),
    request.get("/groups/resource-membership", { params: { resource: "datasource", resource_id: ds.id } }),
  ])
  groups.value = groupsRes.data.items || []
  groupSelectIds.value = membershipRes.data.group_ids || []
}

async function handleGroupSubmit() {
  if (!groupTarget.value) return
  await request.put("/groups/resource-membership", {
    resource: "datasource",
    resource_id: groupTarget.value.id,
    group_ids: groupSelectIds.value,
  })
  ElMessage.success(t("common.groupUpdated"))
  groupDialogVisible.value = false
  fetchDatasources()
}

onMounted(fetchDatasources)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("datasource.title") }}</h2>
      <p>{{ t("datasource.subtitle") }}</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" :placeholder="t('datasource.searchPlaceholder')" @keyup.enter="fetchDatasources">
          <select class="form-select" v-model="dbTypeFilter" @change="fetchDatasources">
            <option value="">{{ t("common.allTypes") }}</option>
            <option value="oracle">Oracle 11g</option>
            <option value="mysql">MySQL 5.6</option>
          </select>
          <select class="form-select" v-model="envFilter" @change="fetchDatasources">
            <option value="">{{ t("common.allEnvs") }}</option>
            <option value="DEV">DEV</option>
            <option value="UAT">UAT</option>
            <option value="PROD">PROD</option>
          </select>
          <select class="form-select" v-model="statusFilter" @change="fetchDatasources">
            <option value="">{{ t("common.allStatus") }}</option>
            <option :value="1">{{ t("common.enabled") }}</option>
            <option :value="0">{{ t("common.disabled") }}</option>
          </select>
          <button class="btn" @click="fetchDatasources">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <button v-if="userStore.isAdmin" class="btn btn-primary" @click="openCreate">{{ t("datasource.add") }}</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead><tr>
          <th>{{ t("datasource.colCode") }}</th><th>{{ t("datasource.colName") }}</th><th>{{ t("datasource.colDbType") }}</th><th>{{ t("datasource.colEnv") }}</th><th>{{ t("datasource.colGroups") }}</th><th>{{ t("datasource.colHost") }}</th><th>{{ t("datasource.colPort") }}</th><th>{{ t("datasource.colStatus") }}</th><th>{{ t("datasource.colRemark") }}</th><th>{{ t("datasource.colActions") }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in datasources" :key="row.id">
            <td class="text-mono">{{ row.datasource_code }}</td>
            <td>{{ row.datasource_name }}</td>
            <td><span class="tag" :class="dbTypeTagClass(row.db_type)">{{ dbTypeLabel(row.db_type) }}</span></td>
            <td><span class="tag" :class="envTagClass(row.env_code)">{{ row.env_code }}</span></td>
            <td>
              <span v-for="g in row.groups || []" :key="g" class="tag tag-info" style="margin-right:4px">{{ g }}</span>
              <span v-if="!(row.groups || []).length" style="color:var(--color-text-muted)">—</span>
            </td>
            <td class="text-mono">{{ row.host }}</td>
            <td class="text-mono">{{ row.port }}</td>
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
          <tr v-if="!loading && datasources.length === 0"><td colspan="10" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">{{ t("datasource.empty") }}</td></tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchDatasources" />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? t('datasource.dialogEdit') : t('datasource.dialogCreate')" width="640">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item :label="t('datasource.labelCode')" prop="datasource_code"><el-input v-model="form.datasource_code" :disabled="isEdit" /></el-form-item>
        <el-form-item :label="t('datasource.labelName')" prop="datasource_name"><el-input v-model="form.datasource_name" /></el-form-item>
        <el-form-item :label="t('datasource.labelDbType')"><el-select v-model="form.db_type"><el-option label="Oracle 11g" value="oracle" /><el-option label="MySQL 5.6" value="mysql" /></el-select></el-form-item>
        <el-form-item :label="t('datasource.labelEnv')"><el-select v-model="form.env_code"><el-option label="DEV" value="DEV" /><el-option label="UAT" value="UAT" /><el-option label="PROD" value="PROD" /></el-select></el-form-item>
        <el-form-item :label="t('datasource.labelHost')" prop="host"><el-input v-model="form.host" /></el-form-item>
        <el-form-item :label="t('datasource.labelPort')"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item :label="t('datasource.labelInstance')" v-if="form.db_type === 'oracle'"><el-input v-model="form.instance_name" :placeholder="t('datasource.placeholderInstance')" /></el-form-item>
        <el-form-item :label="t('datasource.labelService')" v-if="form.db_type === 'oracle'"><el-input v-model="form.service_name" :placeholder="t('datasource.placeholderService')" /></el-form-item>
        <el-form-item :label="t('datasource.labelDatabase')" v-if="form.db_type === 'mysql'"><el-input v-model="form.database" :placeholder="t('datasource.placeholderDatabase')" /></el-form-item>
        <el-form-item :label="t('datasource.labelUsername')" prop="username"><el-input v-model="form.username" /></el-form-item>
        <el-form-item :label="t('datasource.labelPassword')"><el-input v-model="form.encrypted_password" :placeholder="t('datasource.placeholderPassword')" /></el-form-item>
        <el-form-item :label="t('datasource.labelMaxConcurrent')"><el-input-number v-model="form.max_concurrent" :min="1" :max="20" /></el-form-item>
        <el-form-item :label="t('datasource.labelTimeout')"><el-input-number v-model="form.query_timeout" :min="10" :max="600" /></el-form-item>
        <el-form-item :label="t('datasource.labelRemark')"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">{{ t("common.cancel") }}</el-button><el-button type="primary" @click="handleSubmit">{{ t("common.save") }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="groupDialogVisible" :title="t('datasource.groupDialogTitle', { code: groupTarget?.datasource_code || '' })" width="520">
      <p style="color:#666;font-size:13px;margin-bottom:8px">{{ t("datasource.groupDialogHint") }}</p>
      <el-select v-model="groupSelectIds" multiple filterable :placeholder="t('common.groupSelectPlaceholder')" style="width:100%">
        <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="t('common.groupOption', { name: g.group_name, env: g.env_code })" />
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
