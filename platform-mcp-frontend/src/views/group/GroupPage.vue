<script setup lang="ts">
import { ref, onMounted, computed } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Group } from "@/types"

type GroupType = "datasource" | "server"

const loading = ref(false)
const groups = ref<Group[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")

const activeTab = ref<GroupType>("datasource")

const dialogVisible = ref(false)
const editMode = ref(false)
const form = ref<{ group_name: string; description: string; env_code: string }>({
  group_name: "",
  description: "",
  env_code: "DEV",
})
const editId = ref<number | null>(null)

const memberVisible = ref(false)
const memberTarget = ref<Group | null>(null)
const memberInput = ref("")
const memberLoading = ref(false)

const userVisible = ref(false)
const userTarget = ref<{ id: number; username: string } | null>(null)
const userGroupIdsInput = ref("")
const userInput = ref("")

const endpoint = computed(() => (activeTab.value === "datasource" ? "/groups/datasources" : "/groups/servers"))
const memberLabel = computed(() => (activeTab.value === "datasource" ? "数据源 ID" : "服务器 ID"))

async function fetchGroups() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    const res = await request.get(endpoint.value, { params })
    groups.value = res.data.items || []
    total.value = res.data.total || 0
  } finally {
    loading.value = false
  }
}

function switchTab() {
  page.value = 1
  search.value = ""
  fetchGroups()
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
    await request.put(`${endpoint.value}/${editId.value}`, form.value)
    ElMessage.success("更新成功")
  } else {
    await request.post(endpoint.value, form.value)
    ElMessage.success("创建成功")
  }
  dialogVisible.value = false
  fetchGroups()
}

async function deleteGroup(g: Group) {
  await request.delete(`${endpoint.value}/${g.id}`)
  ElMessage.success("删除成功")
  fetchGroups()
}

async function openMembers(g: Group) {
  memberTarget.value = g
  memberInput.value = ""
  memberLoading.value = true
  memberVisible.value = true
  try {
    const res = await request.get(`${endpoint.value}/${g.id}/members`)
    const data = res.data as { items?: number[]; ids?: number[]; members?: { id: number }[] }
    const ids = data.items || data.ids || (data.members || []).map((m) => m.id)
    memberInput.value = ids.join(",")
  } finally {
    memberLoading.value = false
  }
}

async function saveMembers() {
  if (!memberTarget.value) return
  const ids = memberInput.value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s !== "")
    .map(Number)
    .filter((n) => !isNaN(n) && n > 0)
  await request.put(`${endpoint.value}/${memberTarget.value.id}/members`, { ids })
  ElMessage.success("成员更新成功")
  memberVisible.value = false
}

async function openUserGroups(u: { id: number; username: string }) {
  userTarget.value = u
  userGroupIdsInput.value = ""
  userVisible.value = true
  request.get(`/groups/users/${u.id}`).then((res) => {
    const data = res.data as Record<string, number[]>
    const key = activeTab.value === "datasource" ? "datasource_groups" : "server_groups"
    userGroupIdsInput.value = (data[key] || []).join(",")
  }).catch(() => {
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
  const ids = userGroupIdsInput.value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s !== "")
    .map(Number)
    .filter((n) => !isNaN(n) && n > 0)
  await request.put(`/groups/users/${userTarget.value.id}`, {
    group_type: activeTab.value,
    group_ids: ids,
  })
  ElMessage.success("用户组关联更新成功")
  userVisible.value = false
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
      <p>管理数据源组与服务器组（多对多关联，admin 管理分配，developer 只读）</p>
    </div>

    <el-tabs v-model="activeTab" @tab-change="switchTab" class="group-tabs">
      <el-tab-pane label="数据源组" name="datasource" />
      <el-tab-pane label="服务器组" name="server" />
    </el-tabs>

    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索组名" @keyup.enter="fetchGroups">
          <button class="btn" @click="fetchGroups">查询</button>
        </div>
        <div class="toolbar-right">
          <input type="number" class="search-input user-id-input" v-model="userInput" placeholder="用户 ID" />
          <button class="btn" @click="submitUserGroups">用户分配</button>
          <button class="btn btn-primary" @click="openCreate">+ 新建 {{ activeTab === "datasource" ? "数据源组" : "服务器组" }}</button>
        </div>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>组名</th>
            <th>描述</th>
            <th>环境</th>
            <th>状态</th>
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
            <td>{{ row.created_at }}</td>
            <td class="actions">
              <button class="btn btn-sm btn-primary" @click="openMembers(row)">成员</button>
              <button class="btn btn-sm" @click="openEdit(row)">编辑</button>
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

    <el-dialog v-model="memberVisible" :title="`成员管理 - ${memberTarget?.group_name || ''}`" width="500">
      <div v-if="memberLoading">加载中...</div>
      <div v-else>
        <p class="member-hint">输入 {{ memberLabel }}（逗号分隔，例如: 1,2,3）</p>
        <el-input v-model="memberInput" type="textarea" :rows="3" :placeholder="memberLabel" />
      </div>
      <template #footer>
        <el-button @click="memberVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMembers">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="userVisible" :title="`用户组关联 - ${userTarget?.username || ''}`" width="500">
      <p class="member-hint">输入组 ID（逗号分隔）</p>
      <el-input v-model="userGroupIdsInput" type="textarea" :rows="3" placeholder="组 ID" />
      <template #footer>
        <el-button @click="userVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUserGroups">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.group-tabs { margin-bottom: 8px; }
.member-hint { color: #666; margin-bottom: 8px; font-size: 13px; }
.user-id-input { width: 100px; }
</style>