<script setup lang="ts">
import { ref, computed, onMounted, reactive } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import { maskApiKey } from "@/utils/format"
import Pagination from "@/components/Pagination.vue"
import DataTable, { type DataColumn } from "@/components/DataTable.vue"
import { copyToClipboard } from "@/utils/clipboard"
import type { Group, User } from "@/types"
import { useUserStore } from "@/stores/user"

const { t } = useI18n()
const userStore = useUserStore()
const loading = ref(false)
const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(userStore.pageSize)
const search = ref("")
const roleFilter = ref("")

// ===== 列定义（DataTable 公共组件；computed 保持语言切换响应）=====
const userColumns = computed<DataColumn[]>(() => [
  { key: "username", label: t("user.colUsername"), cls: "text-mono" },
  { key: "nickname", label: t("user.colNickname") },
  { key: "role_code", label: t("user.colRole") },
  { key: "groups", label: t("user.colGroups") },
  { key: "api_key", label: t("user.colApiKey") },
  { key: "status", label: t("user.colStatus") },
  { key: "created_at", label: t("user.colCreatedAt") },
  { key: "actions", label: t("user.colActions") },
])

const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref(0)
const form = ref({ username: "", password: "", nickname: "", role_code: "developer" })
const resetVisible = ref(false)
const resetId = ref(0)
const newPassword = ref("")
const confirmPassword = ref("")

// V3.0 统一组：所属组列 + 用户分组分配（仅 dev 角色用户涉及分组，admin/一般用户显示 -）
const groups = ref<Group[]>([])
const userGroupIds = reactive<Record<number, number[]>>({})
const groupDialogVisible = ref(false)
const groupTarget = ref<User | null>(null)
const groupSelectIds = ref<number[]>([])

async function fetchGroups() {
  const res = await request.get("/groups", { params: { page: 1, page_size: 100 } })
  groups.value = res.data.items || []
}

async function fetchUserGroupIds(userId: number) {
  try {
    const res = await request.get(`/groups/users/${userId}`)
    const data = res.data as { group_ids?: number[] }
    userGroupIds[userId] = data.group_ids || []
  } catch {
    userGroupIds[userId] = []
  }
}

async function fetchUsers() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (roleFilter.value) params.role = roleFilter.value
    const res = await request.get("/users", { params })
    users.value = res.data.items
    total.value = res.data.total
    // 内部系统用户量小：逐用户取所属组 id（admin/一般用户也取但仅 dev 行展示）
    await Promise.all(users.value.map((u) => fetchUserGroupIds(u.id)))
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
      ElMessage[ok ? "success" : "error"](ok ? t("user.createdWithKey") : t("user.createdKeyCopyFailed"))
    } else {
      ElMessage.success(t("common.saveSuccess"))
    }
  }
  dialogVisible.value = false
  await fetchUsers()
}

async function handleStatus(user: User, status: number) {
  await request.put(`/users/${user.id}/status`, { status })
  ElMessage.success(t("common.statusUpdated"))
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
    ElMessage.warning(t("user.resetPwdEmpty"))
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.error(t("user.resetPwdMismatch"))
    return
  }
  await request.post(`/users/${resetId.value}/reset-password`, { new_password: newPassword.value })
  ElMessage.success(t("user.resetPwdSuccess"))
  resetVisible.value = false
}

function roleTagClass(role: string) {
  if (role === 'admin') return 'tag-danger'
  if (role === 'user') return 'tag-success'
  return 'tag-primary'
}
function roleLabel(role: string) {
  if (role === 'admin') return t("user.roleAdmin")
  if (role === 'user') return t("user.roleUser")
  return t("user.roleDeveloper")
}

function groupNamesOf(userId: number): string[] {
  const ids = userGroupIds[userId] || []
  return ids
    .map((gid) => groups.value.find((g) => g.id === gid)?.group_name)
    .filter((n): n is string => !!n)
}

function openGroupAssign(user: User) {
  if (user.role_code !== 'developer') return
  groupTarget.value = user
  groupSelectIds.value = [...(userGroupIds[user.id] || [])]
  groupDialogVisible.value = true
}

async function handleGroupAssign() {
  if (!groupTarget.value) return
  await request.put(`/groups/users/${groupTarget.value.id}`, { group_ids: groupSelectIds.value })
  ElMessage.success(t("user.groupAssignUpdated"))
  groupDialogVisible.value = false
  await fetchUserGroupIds(groupTarget.value.id)
}

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
      ElMessage.success(t("user.revealed"))
    } else {
      ElMessage.warning(t("user.noKeyOrLegacy"))
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
    ElMessage[ok ? "success" : "error"](ok ? (key ? t("common.copiedKey") : t("user.copiedMasked")) : t("common.copyFailed"))
  }
}

async function handleResetKey(user: User) {
  try {
    const res = await request.post(`/api-keys/reset/${user.id}`)
    const data = res.data as any
    if (data?.key) {
      revealedKeys.value[user.id] = data.key
      ElMessage.success(t("user.resetKeySuccess", { username: user.username, key: data.key }))
    } else {
      ElMessage.success(t("user.resetKeySuccessNoKey", { username: user.username }))
    }
    await fetchUsers()
  } catch { /* handled by interceptor */ }
}

onMounted(() => {
  fetchUsers()
  fetchGroups()
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("user.title") }}</h2>
      <p>{{ t("user.subtitle") }}</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" :placeholder="t('user.searchPlaceholder')" @keyup.enter="fetchUsers">
          <select class="form-select" v-model="roleFilter" @change="fetchUsers">
            <option value="">{{ t("user.allRoles") }}</option>
            <option value="admin">{{ t("user.roleAdmin") }}</option>
            <option value="developer">{{ t("user.roleDeveloper") }}</option>
            <option value="user">{{ t("user.roleUser") }}</option>
          </select>
          <button class="btn" @click="fetchUsers">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openCreate">{{ t("user.add") }}</button>
        </div>
      </div>
      <DataTable
        :columns="userColumns"
        :rows="users"
        :loading="loading"
        :empty-text="t('user.empty')"
        row-key="id"
      >
        <template #nickname="{ row }">{{ row.nickname || '—' }}</template>
        <template #role_code="{ row }">
          <span class="tag" :class="roleTagClass(row.role_code)">{{ roleLabel(row.role_code) }}</span>
        </template>
        <template #groups="{ row }">
          <template v-if="row.role_code === 'developer'">
            <span v-for="name in groupNamesOf(row.id)" :key="name" class="tag tag-info" style="margin-right:4px">{{ name }}</span>
            <span v-if="groupNamesOf(row.id).length === 0" style="color:var(--color-text-muted)">—</span>
          </template>
          <span v-else style="color:var(--color-text-muted)">—</span>
        </template>
        <template #api_key="{ row }">
          <span v-if="row.api_key_prefix" class="text-mono" style="font-size:12px">{{ revealedKeys[row.id] ? revealedKeys[row.id] : maskApiKey(row.api_key_prefix) }}</span>
          <span v-else style="color:var(--color-text-muted)">—</span>
          <span v-if="row.api_key_prefix" class="key-action" :title="revealedKeys[row.id] ? t('user.titleHide') : t('user.titleShow')" @click="toggleReveal(row.id)">&#128065;</span>
          <span v-if="row.api_key_prefix" class="key-action" :title="t('user.titleCopyKey')" @click="copyUserKey(row.id, maskApiKey(row.api_key_prefix))">&#128203;</span>
          <span v-if="row.api_key_prefix" class="key-action" :title="t('user.titleResetKey')" @click="handleResetKey(row)">&#8635;</span>
        </template>
        <template #status="{ row }">
          <span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">{{ row.status === 1 ? t("common.enabled") : t("common.disabled") }}</span>
        </template>
        <template #created_at="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</template>
        <template #actions="{ row }">
          <button class="btn btn-sm" @click="openEdit(row)">{{ t("common.edit") }}</button>
          <button class="btn btn-sm" @click="openReset(row)">{{ t("user.resetTitle") }}</button>
          <button class="btn btn-sm" :disabled="row.role_code !== 'developer'"
                  :title="row.role_code !== 'developer' ? t('user.groupOnlyDevDisabled') : t('user.groupAssignAction')"
                  @click="openGroupAssign(row)">{{ t("common.assignGroup") }}</button>
          <button v-if="row.status === 1" class="btn btn-sm btn-danger" @click="handleStatus(row, 0)">{{ t("common.disable") }}</button>
          <button v-if="row.status === 0" class="btn btn-sm btn-primary" @click="handleStatus(row, 1)">{{ t("common.enable") }}</button>
        </template>
      </DataTable>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchUsers" />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? t('user.dialogEdit') : t('user.dialogCreate')" width="500">
      <el-form label-width="100px" autocomplete="off">
        <input type="text" name="fake-username" style="display:none" autocomplete="off" />
        <input type="password" name="fake-password" style="display:none" autocomplete="off" />
        <el-form-item :label="t('user.labelUsername')"><el-input v-model="form.username" :disabled="isEdit" autocomplete="off" name="new-username" /></el-form-item>
        <el-form-item v-if="!isEdit" :label="t('user.labelInitialPassword')"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" name="new-password" /></el-form-item>
        <el-form-item :label="t('user.labelNickname')"><el-input v-model="form.nickname" autocomplete="off" /></el-form-item>
        <el-form-item :label="t('user.labelRole')"><el-select v-model="form.role_code"><el-option :label="t('user.roleAdmin')" value="admin" /><el-option :label="t('user.roleDeveloper')" value="developer" /><el-option :label="t('user.roleUser')" value="user" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">{{ t("common.cancel") }}</el-button><el-button type="primary" @click="handleSubmit">{{ t("common.save") }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="resetVisible" :title="t('user.resetTitle')" width="400">
      <el-form label-width="100px" autocomplete="off">
        <input type="password" name="fake-reset" style="display:none" autocomplete="off" />
        <el-form-item :label="t('user.resetNewPassword')"><el-input v-model="newPassword" type="password" show-password autocomplete="new-password" name="reset-new-password" /></el-form-item>
        <el-form-item :label="t('user.resetConfirmPassword')"><el-input v-model="confirmPassword" type="password" show-password autocomplete="new-password" name="reset-confirm-password" :placeholder="t('user.resetConfirmPlaceholder')" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resetVisible = false">{{ t("common.cancel") }}</el-button><el-button type="primary" @click="handleReset">{{ t("user.resetSubmit") }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="groupDialogVisible" :title="t('user.groupAssignTitle', { name: groupTarget?.username || '' })" width="520">
      <p style="color:#666;font-size:13px;margin-bottom:8px">{{ t("user.groupAssignHint") }}</p>
      <el-select v-model="groupSelectIds" multiple filterable :placeholder="t('common.groupSelectPlaceholder')" style="width:100%">
        <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="t('common.groupOption', { name: g.group_name })" />
      </el-select>
      <template #footer>
        <el-button @click="groupDialogVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="handleGroupAssign">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
</style>
