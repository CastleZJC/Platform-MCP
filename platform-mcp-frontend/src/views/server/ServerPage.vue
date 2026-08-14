<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import type { FormInstance, FormRules } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Server } from "@/types"
import { useUserStore } from "@/stores/user"

const userStore = useUserStore()
const loading = ref(false)
const servers = ref<Server[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
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
const rules: FormRules = {
  server_code: [{ required: true, whitespace: true, message: "服务器编码不能为空", trigger: "blur" }],
  server_name: [{ required: true, whitespace: true, message: "服务器名称不能为空", trigger: "blur" }],
  host: [{ required: true, whitespace: true, message: "主机地址不能为空", trigger: "blur" }],
  username: [{ required: true, whitespace: true, message: "登录用户名不能为空", trigger: "blur" }],
}

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
    ElMessage.error("必填字段不能为空：服务器编码 / 名称 / 主机地址 / 登录用户名")
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
  ElMessage.success("保存成功")
  dialogVisible.value = false
  fetchServers()
}

async function handleStatus(srv: Server, status: number) {
  await request.put(`/servers/${srv.id}/status`, { status })
  ElMessage.success("状态更新成功")
  fetchServers()
}

async function handleTest(srv: Server) {
  testing.value = true
  try {
    const res = await request.post(`/servers/${srv.id}/test`)
    if (res.data.success) {
      ElMessage.success(`连接成功 (${res.data.latency_ms}ms)`)
    } else {
      ElMessage.error(`连接失败: ${res.data.message}`)
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

onMounted(fetchServers)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>服务器管理</h2>
      <p>管理 Linux 远端服务器配置，支持 Claude Code 通过 skill server 执行 SSH 命令与 SFTP 文件传输</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索编码 / 名称 / 主机" @keyup.enter="fetchServers">
          <select class="form-select" v-model="envFilter" @change="fetchServers">
            <option value="">全部环境</option>
            <option value="DEV">DEV</option>
            <option value="UAT">UAT</option>
            <option value="PROD">PROD</option>
          </select>
          <select class="form-select" v-model="statusFilter" @change="fetchServers">
            <option value="">全部状态</option>
            <option :value="1">已启用</option>
            <option :value="0">已停用</option>
          </select>
          <button class="btn" @click="fetchServers">查询</button>
        </div>
        <div class="toolbar-right">
          <button v-if="userStore.isAdmin" class="btn btn-primary" @click="openCreate">+ 新增服务器</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead>
          <tr>
            <th>服务器编码</th>
            <th>名称</th>
            <th>环境</th>
            <th>主机</th>
            <th>SSH 端口</th>
            <th>用户</th>
            <th>认证</th>
            <th>状态</th>
            <th>备注</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in servers" :key="row.id">
            <td class="text-mono">{{ row.server_code }}</td>
            <td>{{ row.server_name }}</td>
            <td><span class="tag" :class="envTagClass(row.env_code)">{{ row.env_code }}</span></td>
            <td class="text-mono">{{ row.host }}</td>
            <td class="text-mono">{{ row.ssh_port }}</td>
            <td class="text-mono">{{ row.username }}</td>
            <td>{{ authBadge(row) }}</td>
            <td><span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">{{ row.status === 1 ? '已启用' : '已停用' }}</span></td>
            <td>{{ row.remark || '—' }}</td>
            <td class="actions">
              <button class="btn btn-sm btn-success" @click="handleTest(row)" :disabled="testing">测试</button>
              <button v-if="userStore.isAdmin" class="btn btn-sm" @click="openEdit(row)">编辑</button>
              <button v-if="userStore.isAdmin && row.status === 1" class="btn btn-sm btn-danger" @click="handleStatus(row, 0)">停用</button>
              <button v-if="userStore.isAdmin && row.status === 0" class="btn btn-sm btn-primary" @click="handleStatus(row, 1)">启用</button>
            </td>
          </tr>
          <tr v-if="!loading && servers.length === 0">
            <td colspan="10" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">暂无服务器，请点击右上角"新增服务器"</td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchServers" />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑服务器' : '新增服务器'" width="640">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="服务器编码" prop="server_code"><el-input v-model="form.server_code" :disabled="isEdit" placeholder="如 APP-SAMPLE-1" /></el-form-item>
        <el-form-item label="服务器名称" prop="server_name"><el-input v-model="form.server_name" /></el-form-item>
        <el-form-item label="环境">
          <el-select v-model="form.env_code">
            <el-option label="DEV" value="DEV" />
            <el-option label="UAT" value="UAT" />
            <el-option label="PROD" value="PROD" :disabled="!userStore.isAdmin" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机地址" prop="host"><el-input v-model="form.host" placeholder="如 192.168.1.100" /></el-form-item>
        <el-form-item label="SSH 端口"><el-input-number v-model="form.ssh_port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="登录用户名" prop="username"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="加密密码"><el-input v-model="form.encrypted_password" placeholder="从密码加密页获取 AES 密文（与 SSH Key 二选一）" /></el-form-item>
        <el-form-item label="加密 SSH Key"><el-input v-model="form.encrypted_ssh_key" type="textarea" :rows="3" placeholder="从密码加密页获取 PEM 私钥 AES 密文（与密码二选一）" /></el-form-item>
        <el-form-item label="最大并发"><el-input-number v-model="form.max_concurrent" :min="1" :max="20" /></el-form-item>
        <el-form-item label="命令超时(s)"><el-input-number v-model="form.command_timeout" :min="10" :max="3600" /></el-form-item>
        <el-form-item label="远端白名单"><el-input v-model="form.allowed_paths_text" type="textarea" :rows="3" placeholder="每行一个绝对路径，如 /tmp" /></el-form-item>
        <el-form-item label="远端黑名单"><el-input v-model="form.forbidden_paths_text" type="textarea" :rows="2" placeholder="每行一个绝对路径，禁止操作的路径前缀" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
</style>
