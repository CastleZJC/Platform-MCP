<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Group, GroupMembers } from "@/types"

const loading = ref(false)
const groups = ref<Group[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")

const dialogVisible = ref(false)
const editMode = ref(false)
const form = ref<{ group_name: string; description: string; env_code: string }>({
  group_name: "",
  description: "",
  env_code: "DEV",
})
const editId = ref<number | null>(null)

// 统一组成员管理：三类成员（组员/数据源/服务器）ID 列表编辑
const memberVisible = ref(false)
const memberTarget = ref<Group | null>(null)
const memberLoading = ref(false)
const userIdsInput = ref("")
const dsIdsInput = ref("")
const svrIdsInput = ref("")
// 打开时的预填快照：仅提交有变化的那一类（避免无差别覆盖与冗余审计）
const originalSnapshot = ref({ user: "", datasource: "", server: "" })

const userVisible = ref(false)
const userTarget = ref<{ id: number; username: string } | null>(null)
const userGroupIdsInput = ref("")
const userInput = ref("")

async function fetchGroups() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    const res = await request.get("/groups", { params })
    groups.value = res.data.items || []
    total.value = res.data.total || 0
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editMode.value = false
  editId.value = null
  form.value = { group_name: "", description: "", env_code: "DEV" }
  dialogVisible.value = true
}

function openEdit(g: Group) {
  editMode.value = true
  editId.value = g.id
  form.value = {
    group_name: g.group_name,
    description: g.description || "",
    env_code: g.env_code,
  }
  dialogVisible.value = true
}

async function submitForm() {
  if (!form.value.group_name) {
    ElMessage.warning("请填写组名")
    return
  }
  if (editMode.value && editId.value !== null) {
    await request.put(`/groups/${editId.value}`, form.value)
    ElMessage.success("更新成功")
  } else {
    await request.post("/groups", form.value)
    ElMessage.success("创建成功")
  }
  dialogVisible.value = false
  fetchGroups()
}

async function toggleStatus(g: Group) {
  await request.put(`/groups/${g.id}`, { status: g.status === 1 ? 0 : 1 })
  ElMessage.success(g.status === 1 ? "已停用" : "已启用")
  fetchGroups()
}

async function deleteGroup(g: Group) {
  await request.delete(`/groups/${g.id}`)
  ElMessage.success("删除成功")
  fetchGroups()
}

function parseIds(input: string): number[] {
  return input
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s !== "")
    .map(Number)
    .filter((n) => !isNaN(n) && n > 0)
}

async function openMembers(g: Group) {
  memberTarget.value = g
  memberLoading.value = true
  memberVisible.value = true
  try {
    const res = await request.get(`/groups/${g.id}/members`)
    const data = res.data as GroupMembers
    userIdsInput.value = (data.users || []).map((u) => u.id).join(",")
    dsIdsInput.value = (data.datasources || []).map((d) => d.id).join(",")
    svrIdsInput.value = (data.servers || []).map((s) => s.id).join(",")
    originalSnapshot.value = {
      user: userIdsInput.value,
      datasource: dsIdsInput.value,
      server: svrIdsInput.value,
    }
  } finally {
    memberLoading.value = false
  }
}

async function saveMembers() {
  if (!memberTarget.value) return
  const gid = memberTarget.value.id
  const pending: { resource: "user" | "datasource" | "server"; input: string; origin: string }[] = [
    { resource: "user", input: userIdsInput.value, origin: originalSnapshot.value.user },
    { resource: "datasource", input: dsIdsInput.value, origin: originalSnapshot.value.datasource },
    { resource: "server", input: svrIdsInput.value, origin: originalSnapshot.value.server },
  ]
  const changed = pending.filter((p) => p.input !== p.origin)
  if (changed.length === 0) {
    ElMessage.info("未修改任何成员")
    memberVisible.value = false
    return
  }
  for (const p of changed) {
    await request.put(`/groups/${gid}/members`, { resource: p.resource, ids: parseIds(p.input) })
  }
  ElMessage.success(`已更新 ${changed.map((p) => p.resource).join("、")} 成员`)
  memberVisible.value = false
  fetchGroups()
}

async function openUserGroups(u: { id: number; username: string }) {
  userTarget.value = u
  userGroupIdsInput.value = ""
  userVisible.value = true
  await request
    .get(`/groups/users/${u.id}`)
    .then((res) => {
      const data = res.data as { group_ids?: number[] }
      userGroupIdsInput.value = (data.group_ids || []).join(",")
    })
    .catch(() => {
      // 没有数据不报错
    })
}

async function submitUserGroups() {
  const id = parseInt(userInput.value, 10)
  if (!id || id <= 0) {
    ElMessage.warning("请输入有效的用户 ID")
    return
  }
  await openUserGroups({ id, username: `#${id}` })
  userInput.value = ""
}

async function saveUserGroups() {
  if (!userTarget.value) return
  await request.put(`/groups/users/${userTarget.value.id}`, { group_ids: parseIds(userGroupIdsInput.value) })
  ElMessage.success("用户所属组更新成功")
  userVisible.value = false
  fetchGroups()
}

function envLabel(env: string) {
  const map: Record<string, string> = { DEV: "开发", UAT: "测试", PROD: "生产" }
  return map[env] || env
}

onMounted(fetchGroups)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>分组管理</h2>
      <p>统一组管理：一个组同时挂组员、数据源与服务器（仅 admin）</p>
    </div>

    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索组名" @keyup.enter="fetchGroups">
          <button class="btn" @click="fetchGroups">查询</button>
        </div>
        <div class="toolbar-right">
          <input type="number" class="search-input user-id-input" v-model="userInput" placeholder="用户 ID" />
          <button class="btn" @click="submitUserGroups">用户分配</button>
          <button class="btn btn-primary" @click="openCreate">+ 新建组</button>
        </div>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>组名</th>
            <th>描述</th>
            <th>环境</th>
            <th>状态</th>
            <th>组员数</th>
            <th>数据源数</th>
            <th>服务器数</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in groups" :key="row.id">
            <td>{{ row.group_name }}</td>
            <td>{{ row.description || "-" }}</td>
            <td><span class="tag tag-info">{{ envLabel(row.env_code) }}</span></td>
            <td>
              <span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">
                {{ row.status === 1 ? "启用" : "停用" }}
              </span>
            </td>
            <td>{{ row.user_count }}</td>
            <td>{{ row.datasource_count }}</td>
            <td>{{ row.server_count }}</td>
            <td>{{ row.created_at }}</td>
            <td class="actions">
              <button class="btn btn-sm btn-primary" @click="openMembers(row)">成员</button>
              <button class="btn btn-sm" @click="openEdit(row)">编辑</button>
              <button class="btn btn-sm" @click="toggleStatus(row)">{{ row.status === 1 ? "停用" : "启用" }}</button>
              <button class="btn btn-sm btn-danger" @click="deleteGroup(row)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchGroups" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editMode ? '编辑组' : '新建组'" width="480">
      <el-form label-width="80px">
        <el-form-item label="组名"><el-input v-model="form.group_name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="环境">
          <select class="form-select" v-model="form.env_code">
            <option value="DEV">DEV</option>
            <option value="UAT">UAT</option>
            <option value="PROD">PROD</option>
          </select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberVisible" :title="`成员管理 - ${memberTarget?.group_name || ''}`" width="560">
      <div v-if="memberLoading">加载中...</div>
      <div v-else>
        <p class="member-hint">各列输入对象 ID（逗号分隔）；仅提交有变化的一类</p>
        <el-form label-width="90px">
          <el-form-item label="组员(用户)"><el-input v-model="userIdsInput" placeholder="例如: 1,2" /></el-form-item>
          <el-form-item label="数据源"><el-input v-model="dsIdsInput" placeholder="例如: 10,11" /></el-form-item>
          <el-form-item label="服务器"><el-input v-model="svrIdsInput" placeholder="例如: 20" /></el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="memberVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMembers">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="userVisible" :title="`用户所属组 - ${userTarget?.username || ''}`" width="500">
      <p class="member-hint">输入组 ID（逗号分隔，覆盖式设置该用户全部所属组）</p>
      <el-input v-model="userGroupIdsInput" type="textarea" :rows="3" placeholder="组 ID" />
      <template #footer>
        <el-button @click="userVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUserGroups">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.member-hint { color: #666; margin-bottom: 8px; font-size: 13px; }
.user-id-input { width: 100px; }
</style>
