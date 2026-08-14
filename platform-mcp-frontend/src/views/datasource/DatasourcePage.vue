<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import type { FormInstance, FormRules } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Datasource } from "@/types"
import { useUserStore } from "@/stores/user"

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
const rules: FormRules = {
  datasource_code: [{ required: true, whitespace: true, message: "数据源编码不能为空", trigger: "blur" }],
  datasource_name: [{ required: true, whitespace: true, message: "数据源名称不能为空", trigger: "blur" }],
  host: [{ required: true, whitespace: true, message: "主机地址不能为空", trigger: "blur" }],
  username: [{ required: true, whitespace: true, message: "连接用户名不能为空", trigger: "blur" }],
}

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
    ElMessage.error("必填字段不能为空：数据源编码 / 名称 / 主机地址 / 连接用户名")
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (isEdit.value) {
    await request.put(`/datasources/${editId.value}`, form.value)
  } else {
    await request.post("/datasources", form.value)
  }
  ElMessage.success("保存成功")
  dialogVisible.value = false
  fetchDatasources()
}

async function handleStatus(ds: Datasource, status: number) {
  await request.put(`/datasources/${ds.id}/status`, { status })
  ElMessage.success("状态更新成功")
  fetchDatasources()
}

async function handleTest(ds: Datasource) {
  testing.value = true
  try {
    const res = await request.post(`/datasources/${ds.id}/test`)
    if (res.data.success) {
      ElMessage.success(`连接成功 (${res.data.latency_ms}ms)`)
    } else {
      ElMessage.error(`连接失败: ${res.data.message}`)
    }
  } catch { /* handled by interceptor */ }
  finally { testing.value = false }
}

function dbTypeTagClass(t: string) { return t === 'oracle' ? 'tag-warning' : 'tag-info' }
function dbTypeLabel(t: string) { return t === 'oracle' ? 'Oracle 11g' : 'MySQL 5.6' }
function envTagClass(env: string) { return env === 'PROD' ? 'tag-danger' : 'tag-primary' }

onMounted(fetchDatasources)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>数据源管理</h2>
      <p>管理系统接入的目标数据库连接配置，支持 Oracle 11g、MySQL 5.6</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索编码 / 名称 / 主机" @keyup.enter="fetchDatasources">
          <select class="form-select" v-model="dbTypeFilter" @change="fetchDatasources">
            <option value="">全部类型</option>
            <option value="oracle">Oracle 11g</option>
            <option value="mysql">MySQL 5.6</option>
          </select>
          <select class="form-select" v-model="envFilter" @change="fetchDatasources">
            <option value="">全部环境</option>
            <option value="DEV">DEV</option>
            <option value="UAT">UAT</option>
            <option value="PROD">PROD</option>
          </select>
          <select class="form-select" v-model="statusFilter" @change="fetchDatasources">
            <option value="">全部状态</option>
            <option :value="1">已启用</option>
            <option :value="0">已停用</option>
          </select>
          <button class="btn" @click="fetchDatasources">查询</button>
        </div>
        <div class="toolbar-right">
          <button v-if="userStore.isAdmin" class="btn btn-primary" @click="openCreate">+ 新增数据源</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead><tr>
          <th>数据源编码</th><th>数据源名称</th><th>数据库类型</th><th>环境</th><th>主机</th><th>端口</th><th>状态</th><th>备注</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in datasources" :key="row.id">
            <td class="text-mono">{{ row.datasource_code }}</td>
            <td>{{ row.datasource_name }}</td>
            <td><span class="tag" :class="dbTypeTagClass(row.db_type)">{{ dbTypeLabel(row.db_type) }}</span></td>
            <td><span class="tag" :class="envTagClass(row.env_code)">{{ row.env_code }}</span></td>
            <td class="text-mono">{{ row.host }}</td>
            <td class="text-mono">{{ row.port }}</td>
            <td><span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">{{ row.status === 1 ? '已启用' : '已停用' }}</span></td>
            <td>{{ row.remark || '—' }}</td>
            <td class="actions">
              <button class="btn btn-sm btn-success" @click="handleTest(row)" :disabled="testing">测试</button>
              <button v-if="userStore.isAdmin" class="btn btn-sm" @click="openEdit(row)">编辑</button>
              <button v-if="userStore.isAdmin && row.status === 1" class="btn btn-sm btn-danger" @click="handleStatus(row, 0)">停用</button>
              <button v-if="userStore.isAdmin && row.status === 0" class="btn btn-sm btn-primary" @click="handleStatus(row, 1)">启用</button>
            </td>
          </tr>
          <tr v-if="!loading && datasources.length === 0"><td colspan="9" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">暂无数据源，请点击右上角"新增数据源"</td></tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchDatasources" />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑数据源' : '新增数据源'" width="640">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="数据源编码" prop="datasource_code"><el-input v-model="form.datasource_code" :disabled="isEdit" /></el-form-item>
        <el-form-item label="数据源名称" prop="datasource_name"><el-input v-model="form.datasource_name" /></el-form-item>
        <el-form-item label="数据库类型"><el-select v-model="form.db_type"><el-option label="Oracle 11g" value="oracle" /><el-option label="MySQL 5.6" value="mysql" /></el-select></el-form-item>
        <el-form-item label="环境"><el-select v-model="form.env_code"><el-option label="DEV" value="DEV" /><el-option label="UAT" value="UAT" /><el-option label="PROD" value="PROD" /></el-select></el-form-item>
        <el-form-item label="主机地址" prop="host"><el-input v-model="form.host" /></el-form-item>
        <el-form-item label="端口"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="实例名/SID" v-if="form.db_type === 'oracle'"><el-input v-model="form.instance_name" placeholder="Oracle SID，如 ORCL" /></el-form-item>
        <el-form-item label="服务名" v-if="form.db_type === 'oracle'"><el-input v-model="form.service_name" placeholder="Oracle Service Name（与SID二选一）" /></el-form-item>
        <el-form-item label="默认数据库" v-if="form.db_type === 'mysql'"><el-input v-model="form.database" placeholder="MySQL 默认连接数据库" /></el-form-item>
        <el-form-item label="连接用户名" prop="username"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="加密密码"><el-input v-model="form.encrypted_password" placeholder="从密码加密页获取" /></el-form-item>
        <el-form-item label="最大并发"><el-input-number v-model="form.max_concurrent" :min="1" :max="20" /></el-form-item>
        <el-form-item label="查询超时(s)"><el-input-number v-model="form.query_timeout" :min="10" :max="600" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="handleSubmit">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
</style>
