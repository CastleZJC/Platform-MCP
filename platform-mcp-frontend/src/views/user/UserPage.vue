<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import { maskApiKey } from "@/utils/format"
import Pagination from "@/components/Pagination.vue"
import { copyToClipboard } from "@/utils/clipboard"
import type { User } from "@/types"

const loading = ref(false)
const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")
const roleFilter = ref("")

const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref(0)
const form = ref({ username: "", password: "", nickname: "", role_code: "developer" })
const resetVisible = ref(false)
const resetId = ref(0)
const newPassword = ref("")
const confirmPassword = ref("")

async function fetchUsers() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (roleFilter.value) params.role = roleFilter.value
    const res = await request.get("/users", { params })
    users.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

function openCreate() {
  isEdit.value = false
  form.value = { username: "", password: "", nickname: "", role_code: "developer" }
  dialogVisible.value = true
}

function openEdit(user: User) {
  isEdit.value = true
  editId.value = user.id
  form.value = { username: user.username, password: "", nickname: user.nickname || "", role_code: user.role_code }
  dialogVisible.value = true
}

async function handleSubmit() {
  if (isEdit.value) {
    await request.put(`/users/${editId.value}`, { nickname: form.value.nickname, role_code: form.value.role_code })
  } else {
    const res = await request.post("/users", form.value)
    const data = res.data as any
    if (data?.api_key) {
      const ok = await copyToClipboard(data.api_key)
      ElMessage[ok ? "success" : "error"](ok ? `用户创建成功，API Key 已复制到剪贴板` : `用户创建成功，但复制失败，请到个人设置查看 Key`)
    } else {
      ElMessage.success("保存成功")
    }
  }
  dialogVisible.value = false
  await fetchUsers()
}

async function handleStatus(user: User, status: number) {
  await request.put(`/users/${user.id}/status`, { status })
  ElMessage.success("状态更新成功")
  await fetchUsers()
}

function openReset(user: User) {
  resetId.value = user.id
  newPassword.value = ""
  confirmPassword.value = ""
  resetVisible.value = true
}

async function handleReset() {
  if (!newPassword.value) {
    ElMessage.warning("请输入新密码")
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.error("两次输入的密码不一致")
    return
  }
  await request.post(`/users/${resetId.value}/reset-password`, { new_password: newPassword.value })
  ElMessage.success("密码重置成功")
  resetVisible.value = false
}

function roleTagClass(role: string) { return role === 'admin' ? 'tag-danger' : 'tag-primary' }
function roleLabel(role: string) { return role === 'admin' ? '系统管理员' : '开发人员' }

const revealedKeys = ref<Record<number, string>>({})

async function toggleReveal(userId: number) {
  if (revealedKeys.value[userId]) {
    delete revealedKeys.value[userId]
    return
  }
  try {
    const res = await request.get(`/api-keys/full/${userId}`)
    const data = res.data as any
    if (data?.key) {
      revealedKeys.value[userId] = data.key
      ElMessage.success('已显示明文 Key')
    } else {
      ElMessage.warning('该用户当前无活跃 Key 或 Key 在新机制前生成，请点击重置生成新 Key')
    }
  } catch { /* handled by interceptor */ }
}

async function copyUserKey(userId: number, maskedFallback: string) {
  let key = revealedKeys.value[userId]
  if (!key) {
    try {
      const res = await request.get(`/api-keys/full/${userId}`)
      const data = res.data as any
      if (data?.key) {
        key = data.key
      }
    } catch { /* fallback to masked */ }
  }
  const finalKey = key || maskedFallback
  if (finalKey) {
    const ok = await copyToClipboard(finalKey)
    ElMessage[ok ? "success" : "error"](ok ? (key ? "已复制明文 Key" : "已复制掩码（点击眼睛可显示明文）") : "复制失败，请手动选中复制")
  }
}

async function handleResetKey(user: User) {
  try {
    const res = await request.post(`/api-keys/reset/${user.id}`)
    const data = res.data as any
    if (data?.key) {
      revealedKeys.value[user.id] = data.key
      ElMessage.success(`${user.username} Key 已重置: ${data.key}`)
    } else {
      ElMessage.success(`${user.username} 的 API Key 已重置`)
    }
    await fetchUsers()
  } catch { /* handled by interceptor */ }
}

onMounted(fetchUsers)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>用户管理</h2>
      <p>系统用户与角色管理，一期支持 admin / developer 两种角色</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索用户名 / 姓名" @keyup.enter="fetchUsers">
          <select class="form-select" v-model="roleFilter" @change="fetchUsers">
            <option value="">全部角色</option>
            <option value="admin">系统管理员</option>
            <option value="developer">开发人员</option>
          </select>
          <button class="btn" @click="fetchUsers">查询</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openCreate">+ 新增用户</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead><tr>
          <th>用户名</th><th>姓名</th><th>角色</th><th>API Key</th><th>状态</th><th>创建时间</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in users" :key="row.id">
            <td class="text-mono">{{ row.username }}</td>
            <td>{{ row.nickname || '—' }}</td>
            <td><span class="tag" :class="roleTagClass(row.role_code)">{{ roleLabel(row.role_code) }}</span></td>
            <td class="text-mono" style="font-size:12px">
              <span v-if="row.api_key_prefix">{{ revealedKeys[row.id] ? revealedKeys[row.id] : maskApiKey(row.api_key_prefix) }}</span>
              <span v-else style="color:var(--color-text-muted)">—</span>
              <span v-if="row.api_key_prefix" class="key-action" :title="revealedKeys[row.id] ? '隐藏' : '显示明文'" @click="toggleReveal(row.id)">&#128065;</span>
              <span v-if="row.api_key_prefix" class="key-action" title="复制 Key" @click="copyUserKey(row.id, maskApiKey(row.api_key_prefix))">&#128203;</span>
              <span v-if="row.api_key_prefix" class="key-action" title="重置 Key（旧 Key 立即失效）" @click="handleResetKey(row)">&#8635;</span>
            </td>
            <td><span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">{{ row.status === 1 ? '已启用' : '已停用' }}</span></td>
            <td>{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</td>
            <td class="actions">
              <button class="btn btn-sm" @click="openEdit(row)">编辑</button>
              <button class="btn btn-sm" @click="openReset(row)">重置密码</button>
              <button v-if="row.status === 1" class="btn btn-sm btn-danger" @click="handleStatus(row, 0)">停用</button>
              <button v-if="row.status === 0" class="btn btn-sm btn-primary" @click="handleStatus(row, 1)">启用</button>
            </td>
          </tr>
          <tr v-if="!loading && users.length === 0"><td colspan="7" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">暂无用户</td></tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchUsers" />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑用户' : '新增用户'" width="500">
      <el-form label-width="100px" autocomplete="off">
        <input type="text" name="fake-username" style="display:none" autocomplete="off" />
        <input type="password" name="fake-password" style="display:none" autocomplete="off" />
        <el-form-item label="用户名"><el-input v-model="form.username" :disabled="isEdit" autocomplete="off" name="new-username" /></el-form-item>
        <el-form-item v-if="!isEdit" label="初始密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" name="new-password" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.nickname" autocomplete="off" /></el-form-item>
        <el-form-item label="角色"><el-select v-model="form.role_code"><el-option label="系统管理员" value="admin" /><el-option label="开发人员" value="developer" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="handleSubmit">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置密码" width="400">
      <el-form label-width="100px" autocomplete="off">
        <input type="password" name="fake-reset" style="display:none" autocomplete="off" />
        <el-form-item label="新密码"><el-input v-model="newPassword" type="password" show-password autocomplete="new-password" name="reset-new-password" /></el-form-item>
        <el-form-item label="确认密码"><el-input v-model="confirmPassword" type="password" show-password autocomplete="new-password" name="reset-confirm-password" placeholder="请再次输入新密码" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resetVisible = false">取消</el-button><el-button type="primary" @click="handleReset">确认重置</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
</style>
