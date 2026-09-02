<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Group, GroupMembers } from "@/types"

const { t } = useI18n()
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
    ElMessage.warning(t("group.nameRequired"))
    return
  }
  if (editMode.value && editId.value !== null) {
    await request.put(`/groups/${editId.value}`, form.value)
    ElMessage.success(t("group.updated"))
  } else {
    await request.post("/groups", form.value)
    ElMessage.success(t("group.created"))
  }
  dialogVisible.value = false
  fetchGroups()
}

async function toggleStatus(g: Group) {
  await request.put(`/groups/${g.id}`, { status: g.status === 1 ? 0 : 1 })
  ElMessage.success(g.status === 1 ? t("common.disabled") : t("common.enabled"))
  fetchGroups()
}

async function deleteGroup(g: Group) {
  await request.delete(`/groups/${g.id}`)
  ElMessage.success(t("group.deleted"))
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
    ElMessage.info(t("group.memberNoChange"))
    memberVisible.value = false
    return
  }
  for (const p of changed) {
    await request.put(`/groups/${gid}/members`, { resource: p.resource, ids: parseIds(p.input) })
  }
  ElMessage.success(t("group.memberUpdated", { list: changed.map((p) => p.resource).join("、") }))
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
    ElMessage.warning(t("group.userIdInvalid"))
    return
  }
  await openUserGroups({ id, username: `#${id}` })
  userInput.value = ""
}

async function saveUserGroups() {
  if (!userTarget.value) return
  await request.put(`/groups/users/${userTarget.value.id}`, { group_ids: parseIds(userGroupIdsInput.value) })
  ElMessage.success(t("group.userGroupsUpdated"))
  userVisible.value = false
  fetchGroups()
}

function envLabel(env: string) {
  if (env === "DEV") return t("group.envDev")
  if (env === "UAT") return t("group.envUat")
  if (env === "PROD") return t("group.envProd")
  return env
}

onMounted(fetchGroups)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("group.title") }}</h2>
      <p>{{ t("group.subtitle") }}</p>
    </div>

    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" :placeholder="t('group.searchPlaceholder')" @keyup.enter="fetchGroups">
          <button class="btn" @click="fetchGroups">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <input type="number" class="search-input user-id-input" v-model="userInput" :placeholder="t('group.userIdPlaceholder')" />
          <button class="btn" @click="submitUserGroups">{{ t("group.userAssign") }}</button>
          <button class="btn btn-primary" @click="openCreate">{{ t("group.add") }}</button>
        </div>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t("group.colName") }}</th>
            <th>{{ t("group.colDescription") }}</th>
            <th>{{ t("group.colEnv") }}</th>
            <th>{{ t("group.colStatus") }}</th>
            <th>{{ t("group.colUserCount") }}</th>
            <th>{{ t("group.colDatasourceCount") }}</th>
            <th>{{ t("group.colServerCount") }}</th>
            <th>{{ t("group.colCreatedAt") }}</th>
            <th>{{ t("group.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in groups" :key="row.id">
            <td>{{ row.group_name }}</td>
            <td>{{ row.description || "-" }}</td>
            <td><span class="tag tag-info">{{ envLabel(row.env_code) }}</span></td>
            <td>
              <span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">
                {{ row.status === 1 ? t("group.statusEnabled") : t("group.statusDisabled") }}
              </span>
            </td>
            <td>{{ row.user_count }}</td>
            <td>{{ row.datasource_count }}</td>
            <td>{{ row.server_count }}</td>
            <td>{{ row.created_at }}</td>
            <td class="actions">
              <button class="btn btn-sm btn-primary" @click="openMembers(row)">{{ t("group.members") }}</button>
              <button class="btn btn-sm" @click="openEdit(row)">{{ t("common.edit") }}</button>
              <button class="btn btn-sm" @click="toggleStatus(row)">{{ row.status === 1 ? t("common.disable") : t("common.enable") }}</button>
              <button class="btn btn-sm btn-danger" @click="deleteGroup(row)">{{ t("common.delete") }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchGroups" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editMode ? t('group.dialogEdit') : t('group.dialogCreate')" width="480">
      <el-form label-width="80px">
        <el-form-item :label="t('group.labelName')"><el-input v-model="form.group_name" /></el-form-item>
        <el-form-item :label="t('group.labelDescription')"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item :label="t('group.labelEnv')">
          <select class="form-select" v-model="form.env_code">
            <option value="DEV">DEV</option>
            <option value="UAT">UAT</option>
            <option value="PROD">PROD</option>
          </select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submitForm">{{ t("common.submit") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberVisible" :title="t('group.memberTitle', { name: memberTarget?.group_name || '' })" width="560">
      <div v-if="memberLoading">{{ t("common.loading") }}</div>
      <div v-else>
        <p class="member-hint">{{ t("group.memberHint") }}</p>
        <el-form label-width="90px">
          <el-form-item :label="t('group.memberUsers')"><el-input v-model="userIdsInput" :placeholder="t('group.memberUsersPlaceholder')" /></el-form-item>
          <el-form-item :label="t('group.memberDatasources')"><el-input v-model="dsIdsInput" :placeholder="t('group.memberDatasourcesPlaceholder')" /></el-form-item>
          <el-form-item :label="t('group.memberServers')"><el-input v-model="svrIdsInput" :placeholder="t('group.memberServersPlaceholder')" /></el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="memberVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="saveMembers">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="userVisible" :title="t('group.userGroupsTitle', { name: userTarget?.username || '' })" width="500">
      <p class="member-hint">{{ t("group.userGroupsHint") }}</p>
      <el-input v-model="userGroupIdsInput" type="textarea" :rows="3" :placeholder="t('group.userGroupsPlaceholder')" />
      <template #footer>
        <el-button @click="userVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="saveUserGroups">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.member-hint { color: #666; margin-bottom: 8px; font-size: 13px; }
.user-id-input { width: 100px; }
</style>
