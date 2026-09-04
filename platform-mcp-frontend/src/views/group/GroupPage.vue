<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Group, GroupMembers, User, Datasource, Server } from "@/types"

const { t } = useI18n()
const loading = ref(false)
const groups = ref<Group[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")

const dialogVisible = ref(false)
const editMode = ref(false)
const form = ref<{ group_name: string; description: string }>({
  group_name: "",
  description: "",
})
const editId = ref<number | null>(null)

// 统一组成员管理：三类成员（组员/数据源/服务器）多选直接调整，选项按名称展示
const memberVisible = ref(false)
const memberTarget = ref<Group | null>(null)
const memberLoading = ref(false)
const memberUserIds = ref<number[]>([])
const memberDsIds = ref<number[]>([])
const memberSvrIds = ref<number[]>([])
const allUsers = ref<User[]>([])
const allDatasources = ref<Datasource[]>([])
const allServers = ref<Server[]>([])
// 打开时的预填快照：仅提交有变化的那一类（避免无差别覆盖与冗余审计）
const originalSnapshot = ref({ user: "", datasource: "", server: "" })

const RESOURCE_LABEL: Record<string, string> = {
  user: "group.memberUsers",
  datasource: "group.memberDatasources",
  server: "group.memberServers",
}

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
  form.value = { group_name: "", description: "" }
  dialogVisible.value = true
}

function openEdit(g: Group) {
  editMode.value = true
  editId.value = g.id
  form.value = {
    group_name: g.group_name,
    description: g.description || "",
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

// 成员列名单展示：三类各一行“类别(数量): 名称, 名称”；全空显示 —
function memberLines(row: Group): string[] {
  const lines: string[] = []
  if (row.user_names?.length) {
    lines.push(`${t("group.memberUsers")}(${row.user_names.length}): ${row.user_names.join(", ")}`)
  }
  if (row.datasource_names?.length) {
    lines.push(`${t("group.memberDatasources")}(${row.datasource_names.length}): ${row.datasource_names.join(", ")}`)
  }
  if (row.server_names?.length) {
    lines.push(`${t("group.memberServers")}(${row.server_names.length}): ${row.server_names.join(", ")}`)
  }
  return lines
}

async function openMembers(g: Group) {
  memberTarget.value = g
  memberLoading.value = true
  memberVisible.value = true
  try {
    // 成员现状 + 三类全量选项（首次打开拉取，之后复用缓存）
    const [memRes, usersRes, dsRes, svrRes] = await Promise.all([
      request.get(`/groups/${g.id}/members`),
      allUsers.value.length ? Promise.resolve(null) : request.get("/users", { params: { page: 1, page_size: 500 } }),
      allDatasources.value.length
        ? Promise.resolve(null)
        : request.get("/datasources", { params: { page: 1, page_size: 500 } }),
      allServers.value.length ? Promise.resolve(null) : request.get("/servers", { params: { page: 1, page_size: 500 } }),
    ])
    const data = memRes.data as GroupMembers
    memberUserIds.value = (data.users || []).map((u) => u.id)
    memberDsIds.value = (data.datasources || []).map((d) => d.id)
    memberSvrIds.value = (data.servers || []).map((s) => s.id)
    originalSnapshot.value = {
      user: memberUserIds.value.join(","),
      datasource: memberDsIds.value.join(","),
      server: memberSvrIds.value.join(","),
    }
    if (usersRes) allUsers.value = usersRes.data.items || []
    if (dsRes) allDatasources.value = dsRes.data.items || []
    if (svrRes) allServers.value = svrRes.data.items || []
  } finally {
    memberLoading.value = false
  }
}

async function saveMembers() {
  if (!memberTarget.value) return
  const gid = memberTarget.value.id
  const pending: { resource: "user" | "datasource" | "server"; ids: number[]; origin: string }[] = [
    { resource: "user", ids: memberUserIds.value, origin: originalSnapshot.value.user },
    { resource: "datasource", ids: memberDsIds.value, origin: originalSnapshot.value.datasource },
    { resource: "server", ids: memberSvrIds.value, origin: originalSnapshot.value.server },
  ]
  const changed = pending.filter((p) => p.ids.join(",") !== p.origin)
  if (changed.length === 0) {
    ElMessage.info(t("group.memberNoChange"))
    memberVisible.value = false
    return
  }
  for (const p of changed) {
    await request.put(`/groups/${gid}/members`, { resource: p.resource, ids: p.ids })
  }
  ElMessage.success(t("group.memberUpdated", { list: changed.map((p) => t(RESOURCE_LABEL[p.resource])).join("、") }))
  memberVisible.value = false
  fetchGroups()
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
          <button class="btn btn-primary" @click="openCreate">{{ t("group.add") }}</button>
        </div>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t("group.colName") }}</th>
            <th>{{ t("group.colDescription") }}</th>
            <th>{{ t("group.colStatus") }}</th>
            <th class="member-col">{{ t("group.colMembers") }}</th>
            <th>{{ t("group.colCreatedAt") }}</th>
            <th>{{ t("group.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in groups" :key="row.id">
            <td>{{ row.group_name }}</td>
            <td>{{ row.description || "-" }}</td>
            <td>
              <span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">
                {{ row.status === 1 ? t("group.statusEnabled") : t("group.statusDisabled") }}
              </span>
            </td>
            <td class="member-cell">
              <template v-if="memberLines(row).length">
                <div v-for="line in memberLines(row)" :key="line" class="member-line">{{ line }}</div>
              </template>
              <span v-else style="color:var(--color-text-muted)">—</span>
            </td>
            <td>{{ row.created_at }}</td>
            <td class="actions">
              <button class="btn btn-sm" @click="openMembers(row)">{{ t("group.members") }}</button>
              <button class="btn btn-sm" @click="openEdit(row)">{{ t("common.edit") }}</button>
              <button class="btn btn-sm" @click="toggleStatus(row)">{{ row.status === 1 ? t("common.disable") : t("common.enable") }}</button>
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
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submitForm">{{ t("common.submit") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberVisible" :title="t('group.memberTitle', { name: memberTarget?.group_name || '' })" width="640">
      <div v-if="memberLoading">{{ t("common.loading") }}</div>
      <div v-else>
        <p class="member-hint">{{ t("group.memberHint") }}</p>
        <el-form label-width="110px">
          <el-form-item :label="t('group.memberUsers')">
            <el-select v-model="memberUserIds" multiple filterable style="width:100%">
              <el-option v-for="u in allUsers" :key="u.id" :value="u.id" :label="u.nickname ? `${u.username}（${u.nickname}）` : u.username" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('group.memberDatasources')">
            <el-select v-model="memberDsIds" multiple filterable style="width:100%">
              <el-option v-for="d in allDatasources" :key="d.id" :value="d.id" :label="`${d.datasource_name}（${d.env_code}）`" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('group.memberServers')">
            <el-select v-model="memberSvrIds" multiple filterable style="width:100%">
              <el-option v-for="s in allServers" :key="s.id" :value="s.id" :label="`${s.server_name}（${s.host}）`" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="memberVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="saveMembers">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.member-col { min-width: 220px; }
.member-cell .member-line { font-size: 12px; line-height: 1.7; color: var(--color-text-secondary, #666); }
.member-hint { color: #666; margin-bottom: 8px; font-size: 13px; }
</style>
