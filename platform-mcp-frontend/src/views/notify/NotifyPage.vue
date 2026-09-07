<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import { useUserStore } from "@/stores/user"

const { t } = useI18n()
const userStore = useUserStore()

// V3.0 M5（F-37/F-38/F-39）：四提醒事项组管理 + 发件箱发送记录审计 + 测试发送
interface NotifyMember {
  member_id: number
  user_id: number
  username: string
  nickname: string | null
  email: string | null
  has_email: boolean
}

interface NotifyGroup {
  notify_type: string
  group_name: string
  subject_template: string
  body_template: string
  param_descriptions: Record<string, string>
  enabled: number
  members: NotifyMember[]
  unsent_count: number
  updated_at: string | null
}

interface OutboxItem {
  id: number
  notify_type: string
  source: string
  recipient: string
  subject: string
  body: string
  status: string
  retry_count: number
  error_message: string | null
  sent_at: string | null
  created_at: string | null
}

const TYPE_KEYS: Record<string, string> = {
  db_high_op: "notify.typeDb",
  server_high_op: "notify.typeServer",
  skill_review: "notify.typeSkill",
  user_mgmt: "notify.typeUser",
}
const STATUS_KEYS: Record<string, string> = {
  pending: "notify.stPending",
  sent: "notify.stSent",
  failed: "notify.stFailed",
}
const STATUS_TAG: Record<string, string> = {
  pending: "tag-warning",
  sent: "tag-success",
  failed: "tag-danger",
}
function typeLabel(ty: string): string {
  return TYPE_KEYS[ty] ? t(TYPE_KEYS[ty]) : ty
}
function statusLabel(s: string): string {
  return STATUS_KEYS[s] ? t(STATUS_KEYS[s]) : s
}
// 模板参数占位符文本（双花括号是 Vue 模板与 vue-i18n 的保留定界符，须在 script 侧拼接）
function paramPlaceholder(key: string): string {
  return "{{" + key + "}}"
}
function fmtTime(s: string | null): string {
  return s ? s.replace("T", " ").slice(0, 19) : "—"
}

// ---- 提醒事项组 ----
const loading = ref(false)
const groups = ref<NotifyGroup[]>([])

async function fetchGroups() {
  loading.value = true
  try {
    const res = await request.get("/notify/groups")
    groups.value = (res.data as NotifyGroup[]) || []
  } finally {
    loading.value = false
  }
}

async function toggleEnabled(g: NotifyGroup) {
  await request.put(`/notify/groups/${g.notify_type}`, { enabled: g.enabled === 1 ? 0 : 1 })
  ElMessage.success(t("common.statusUpdated"))
  fetchGroups()
}

// ---- 成员管理（F-37：仅 admin 角色可入组；无邮箱入组提示但发送时跳过）----
const memberVisible = ref(false)
const memberType = ref("")
const addUserId = ref<number | null>(null)
const allUsers = ref<
  { id: number; username: string; nickname: string | null; email: string | null; role_code: string }[]
>([])

const currentGroup = computed(() => groups.value.find((g) => g.notify_type === memberType.value) || null)

async function openMembers(g: NotifyGroup) {
  memberType.value = g.notify_type
  addUserId.value = null
  memberVisible.value = true
  if (!allUsers.value.length) {
    const res = await request.get("/users", { params: { page: 1, page_size: 500 } })
    allUsers.value = res.data.items || []
  }
}

// 可添加候选：admin 角色且未在组内（后端 13004 二次校验）
const addCandidates = computed(() => {
  const g = currentGroup.value
  if (!g) return []
  const inGroup = new Set(g.members.map((m) => m.user_id))
  return allUsers.value.filter((u) => u.role_code === "admin" && !inGroup.has(u.id))
})

function userOptionLabel(u: { username: string; nickname: string | null; email: string | null }): string {
  const base = u.nickname ? `${u.username}（${u.nickname}）` : u.username
  return u.email ? base : `${base}（${t("notify.noEmail")}）`
}

async function addMember() {
  if (!currentGroup.value || !addUserId.value) return
  const res = await request.post(`/notify/groups/${currentGroup.value.notify_type}/members`, {
    user_id: addUserId.value,
  })
  // 后端 message 可能携带「未配置邮箱」提示（F-37）
  ElMessage.success(String((res as unknown as { message?: string }).message || t("notify.memberAdded")))
  addUserId.value = null
  await fetchGroups()
}

async function removeMember(m: NotifyMember) {
  if (!currentGroup.value) return
  await request.delete(`/notify/groups/${currentGroup.value.notify_type}/members/${m.user_id}`)
  ElMessage.success(t("notify.memberRemoved"))
  await fetchGroups()
}

// ---- 模板编辑（F-39：模板可编辑，参数替换正确）----
const tplVisible = ref(false)
const tplType = ref("")
const tplForm = ref({ group_name: "", subject_template: "", body_template: "" })

const tplGroup = computed(() => groups.value.find((g) => g.notify_type === tplType.value) || null)
const tplParams = computed(() => Object.entries(tplGroup.value?.param_descriptions || {}))

function openTemplate(g: NotifyGroup) {
  tplType.value = g.notify_type
  tplForm.value = {
    group_name: g.group_name,
    subject_template: g.subject_template,
    body_template: g.body_template,
  }
  tplVisible.value = true
}

async function saveTemplate() {
  if (!tplGroup.value) return
  await request.put(`/notify/groups/${tplGroup.value.notify_type}`, { ...tplForm.value })
  ElMessage.success(t("common.saveSuccess"))
  tplVisible.value = false
  fetchGroups()
}

// ---- 测试发送（R-13：SMTP 连通性验证，落 outbox 后立即 flush 一轮）----
const testVisible = ref(false)
const testRecipient = ref("")
const testLoading = ref(false)

async function sendTest() {
  const rcpt = testRecipient.value.trim()
  if (!rcpt) {
    ElMessage.warning(t("notify.testRecipientRequired"))
    return
  }
  testLoading.value = true
  try {
    const res = await request.post("/notify/test", { recipient: rcpt })
    const r = res.data as { sent: number; pending: number }
    if (r.sent > 0) ElMessage.success(t("notify.testSentOk"))
    else if (r.pending > 0) ElMessage.warning(t("notify.testPending"))
    else ElMessage.error(t("notify.testFailed"))
    testVisible.value = false
    fetchGroups()
    fetchOutbox()
  } finally {
    testLoading.value = false
  }
}

// ---- 发件箱发送记录（F-38：失败可重试、全程可审计）----
const obLoading = ref(false)
const outboxRows = ref<OutboxItem[]>([])
const obPage = ref(1)
const obPageSize = ref(userStore.pageSize)
const obTotal = ref(0)
const obStatus = ref("")
const obType = ref("")

async function fetchOutbox() {
  obLoading.value = true
  try {
    const params: Record<string, unknown> = { page: obPage.value, page_size: obPageSize.value }
    if (obStatus.value) params.status = obStatus.value
    if (obType.value) params.notify_type = obType.value
    const res = await request.get("/notify/outbox", { params })
    outboxRows.value = res.data.items || []
    obTotal.value = res.data.total || 0
  } finally {
    obLoading.value = false
  }
}

function obQuery() {
  obPage.value = 1
  fetchOutbox()
}

const detailVisible = ref(false)
const detailRow = ref<OutboxItem | null>(null)

function openDetail(r: OutboxItem) {
  detailRow.value = r
  detailVisible.value = true
}

onMounted(() => {
  fetchGroups()
  fetchOutbox()
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("notify.title") }}</h2>
      <p>{{ t("notify.subtitle") }}</p>
    </div>

    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left"></div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="testVisible = true">{{ t("notify.testSend") }}</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead>
          <tr>
            <th>{{ t("notify.colType") }}</th>
            <th>{{ t("notify.colGroupName") }}</th>
            <th>{{ t("notify.colEnabled") }}</th>
            <th class="member-col">{{ t("notify.colMembers") }}</th>
            <th>{{ t("notify.colUnsent") }}</th>
            <th>{{ t("notify.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in groups" :key="row.notify_type">
            <td><span class="tag tag-primary">{{ typeLabel(row.notify_type) }}</span></td>
            <td>{{ row.group_name }}</td>
            <td>
              <span class="status-dot" :class="row.enabled === 1 ? 'active' : 'inactive'">
                {{ row.enabled === 1 ? t("common.enabled") : t("common.disabled") }}
              </span>
            </td>
            <td class="member-cell">
              <template v-if="row.members.length">
                <div v-for="m in row.members" :key="m.member_id" class="member-line">
                  {{ m.nickname ? `${m.username}（${m.nickname}）` : m.username }}
                  <span v-if="!m.has_email" class="tag tag-warning">{{ t("notify.noEmail") }}</span>
                </div>
              </template>
              <span v-else style="color: var(--color-text-muted)">—</span>
            </td>
            <td>
              <span v-if="row.unsent_count > 0" class="tag tag-warning">{{ row.unsent_count }}</span>
              <span v-else>0</span>
            </td>
            <td class="actions">
              <button class="btn btn-sm" @click="openMembers(row)">{{ t("notify.memberManage") }}</button>
              <button class="btn btn-sm" @click="openTemplate(row)">{{ t("notify.templateEdit") }}</button>
              <button class="btn btn-sm" :class="row.enabled === 1 ? 'btn-danger' : ''" @click="toggleEnabled(row)">
                {{ row.enabled === 1 ? t("common.disable") : t("common.enable") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card mt-16">
      <div class="toolbar">
        <div class="toolbar-left">
          <select class="form-select" v-model="obStatus" @change="obQuery">
            <option value="">{{ t("common.allStatus") }}</option>
            <option value="pending">{{ t("notify.stPending") }}</option>
            <option value="sent">{{ t("notify.stSent") }}</option>
            <option value="failed">{{ t("notify.stFailed") }}</option>
          </select>
          <select class="form-select" v-model="obType" @change="obQuery">
            <option value="">{{ t("common.allTypes") }}</option>
            <option v-for="ty in Object.keys(TYPE_KEYS)" :key="ty" :value="ty">{{ typeLabel(ty) }}</option>
          </select>
          <button class="btn" @click="obQuery">{{ t("common.query") }}</button>
        </div>
      </div>
      <table class="data-table" v-loading="obLoading">
        <thead>
          <tr>
            <th>{{ t("notify.colType") }}</th>
            <th>{{ t("notify.colSource") }}</th>
            <th>{{ t("notify.colRecipient") }}</th>
            <th>{{ t("notify.colSubject") }}</th>
            <th>{{ t("notify.colStatus") }}</th>
            <th>{{ t("notify.colRetry") }}</th>
            <th>{{ t("notify.colTime") }}</th>
            <th>{{ t("notify.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in outboxRows" :key="row.id">
            <td>{{ typeLabel(row.notify_type) }}</td>
            <td>{{ row.source }}</td>
            <td class="text-mono">{{ row.recipient }}</td>
            <td class="subject-cell">{{ row.subject }}</td>
            <td><span class="tag" :class="STATUS_TAG[row.status] || ''">{{ statusLabel(row.status) }}</span></td>
            <td>{{ row.retry_count }}</td>
            <td class="text-mono">{{ fmtTime(row.sent_at || row.created_at) }}</td>
            <td class="actions">
              <button class="btn btn-sm" @click="openDetail(row)">{{ t("common.detail") }}</button>
            </td>
          </tr>
          <tr v-if="!obLoading && outboxRows.length === 0">
            <td colspan="8" style="text-align: center; color: var(--color-text-secondary); padding: 32px 0">
              {{ t("notify.outboxEmpty") }}
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="obPage" v-model:pageSize="obPageSize" :total="obTotal" @change="fetchOutbox" />
    </div>

    <el-dialog v-model="memberVisible" :title="t('notify.memberTitle', { name: currentGroup?.group_name || '' })" width="640">
      <p class="member-hint">{{ t("notify.memberHint") }}</p>
      <div class="member-add-row">
        <el-select v-model="addUserId" filterable :placeholder="t('notify.memberAddPlaceholder')" style="flex: 1">
          <el-option
            v-for="u in addCandidates"
            :key="u.id"
            :value="u.id"
            :label="userOptionLabel(u)"
          />
        </el-select>
        <button class="btn btn-primary" :disabled="!addUserId" @click="addMember">{{ t("notify.memberAdd") }}</button>
      </div>
      <p v-if="currentGroup && addCandidates.length === 0" class="member-hint">
        {{ t("notify.memberNoCandidates") }}
      </p>
      <table class="data-table" v-if="currentGroup && currentGroup.members.length">
        <thead>
          <tr>
            <th>{{ t("notify.memberColUsername") }}</th>
            <th>{{ t("notify.memberColEmail") }}</th>
            <th>{{ t("notify.memberColActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in currentGroup.members" :key="m.member_id">
            <td>{{ m.nickname ? `${m.username}（${m.nickname}）` : m.username }}</td>
            <td class="text-mono">
              <span v-if="m.has_email">{{ m.email }}</span>
              <span v-else class="tag tag-warning">{{ t("notify.noEmail") }}</span>
            </td>
            <td class="actions">
              <button class="btn btn-sm btn-danger" @click="removeMember(m)">{{ t("common.delete") }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="member-hint">{{ t("notify.memberEmpty") }}</p>
    </el-dialog>

    <el-dialog v-model="tplVisible" :title="t('notify.templateTitle', { name: tplGroup?.group_name || '' })" width="680">
      <p class="member-hint">{{ t("notify.templateHint") }}</p>
      <el-form label-width="110px">
        <el-form-item :label="t('notify.labelGroupName')">
          <el-input v-model="tplForm.group_name" />
        </el-form-item>
        <el-form-item :label="t('notify.labelSubject')">
          <el-input v-model="tplForm.subject_template" />
        </el-form-item>
        <el-form-item :label="t('notify.labelBody')">
          <el-input v-model="tplForm.body_template" type="textarea" :rows="6" />
        </el-form-item>
      </el-form>
      <table class="data-table" v-if="tplParams.length">
        <thead>
          <tr>
            <th>{{ t("notify.paramColKey") }}</th>
            <th>{{ t("notify.paramColDesc") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[key, desc] in tplParams" :key="key">
            <td class="text-mono">{{ paramPlaceholder(key) }}</td>
            <td>{{ desc }}</td>
          </tr>
        </tbody>
      </table>
      <template #footer>
        <el-button @click="tplVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="saveTemplate">{{ t("common.save") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="testVisible" :title="t('notify.testTitle')" width="520">
      <p class="member-hint">{{ t("notify.testHint") }}</p>
      <el-form label-width="110px">
        <el-form-item :label="t('notify.testRecipient')">
          <el-input v-model="testRecipient" placeholder="user@example.com" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="testVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" :loading="testLoading" @click="sendTest">{{ t("notify.testSubmit") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="t('notify.detailTitle')" width="640">
      <template v-if="detailRow">
        <div class="detail-grid">
          <div><span class="detail-label">{{ t("notify.colType") }}:</span> {{ typeLabel(detailRow.notify_type) }}</div>
          <div><span class="detail-label">{{ t("notify.colSource") }}:</span> {{ detailRow.source }}</div>
          <div><span class="detail-label">{{ t("notify.colRecipient") }}:</span> {{ detailRow.recipient }}</div>
          <div>
            <span class="detail-label">{{ t("notify.colStatus") }}:</span>
            <span class="tag" :class="STATUS_TAG[detailRow.status] || ''">{{ statusLabel(detailRow.status) }}</span>
            <span v-if="detailRow.retry_count > 0" style="margin-left: 8px; color: var(--color-text-secondary)">
              {{ t("notify.colRetry") }}: {{ detailRow.retry_count }}
            </span>
          </div>
          <div><span class="detail-label">{{ t("notify.colSubject") }}:</span> {{ detailRow.subject }}</div>
          <div v-if="detailRow.sent_at">
            <span class="detail-label">{{ t("notify.sentAt") }}:</span> {{ fmtTime(detailRow.sent_at) }}
          </div>
        </div>
        <div class="detail-label" style="margin: 12px 0 4px">{{ t("notify.detailBody") }}</div>
        <pre class="detail-body">{{ detailRow.body }}</pre>
        <template v-if="detailRow.error_message">
          <div class="detail-label" style="margin: 12px 0 4px">{{ t("notify.detailError") }}</div>
          <pre class="detail-body error">{{ detailRow.error_message }}</pre>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.member-col { min-width: 200px; }
.member-cell .member-line { font-size: 12px; line-height: 1.9; color: var(--color-text-secondary, #666); }
.member-hint { color: #666; margin-bottom: 8px; font-size: 13px; }
.member-add-row { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.subject-cell { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; font-size: 13px; }
.detail-label { color: var(--color-text-secondary, #666); font-weight: 500; }
.detail-body {
  background: var(--color-background, #f5f7fa); border-radius: 6px; padding: 10px 12px;
  font-size: 12px; white-space: pre-wrap; word-break: break-all; margin: 0;
  max-height: 260px; overflow-y: auto; font-family: monospace;
}
.detail-body.error { color: var(--color-danger, #dc2626); }
</style>
