<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage, ElMessageBox } from "element-plus"
import request, { ApiError } from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import DataTable, { type DataColumn } from "@/components/DataTable.vue"
import { useUserStore } from "@/stores/user"
import { currentLocale } from "@/i18n"
import type { PlazaSkill, PlazaReadme, PlazaSearchResponse, BlockedSkill, SkillVersionsResponse, PlazaVersionItem } from "@/types"

const { t } = useI18n()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)

const activeTab = ref<"plaza" | "blocked">("plaza")

// ===== Skill 广场页签 =====
const loading = ref(false)
const plazas = ref<PlazaSkill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(userStore.pageSize)
const search = ref("")
// 语义搜索模式：命中 /plaza/search 时展示 similarity 列且不分页
const searchMode = ref(false)

// ===== 黑名单页签 =====
const blockedLoading = ref(false)
const blocked = ref<BlockedSkill[]>([])
const blockedPage = ref(1)
const blockedPageSize = ref(userStore.pageSize)
const blockedTotal = ref(0)

// ===== 列定义（DataTable 公共组件；computed 保持语言切换响应）=====
const plazaColumns = computed<DataColumn[]>(() => {
  const cols: DataColumn[] = [
    { key: "skill_code", label: t("common.skillCode"), cls: "text-mono" },
    { key: "skill_name", label: t("common.skillName") },
    { key: "involve", label: t("plaza.colInvolve") },
  ]
  if (searchMode.value) {
    cols.push({ key: "similarity", label: t("plaza.colSimilarity"), align: "center", cls: "text-mono" })
  }
  cols.push(
    { key: "status", label: t("common.colStatus") },
    { key: "actions", label: t("common.colActions") },
  )
  return cols
})
const blockedColumns = computed<DataColumn[]>(() => [
  { key: "skill_code", label: t("common.skillCode"), cls: "text-mono" },
  { key: "skill_name", label: t("common.skillName") },
  { key: "reason", label: t("plaza.blockedColReason") },
  { key: "created_at", label: t("plaza.blockedColCreatedAt") },
  { key: "actions", label: t("common.colActions") },
])

// ===== 详情 / README 弹窗 =====
const detailVisible = ref(false)
const detailTarget = ref<PlazaSkill | null>(null)
const readmeVisible = ref(false)
const readmeLoading = ref(false)
const readmeContent = ref("")
const readmeName = ref("")

// 选取当前 locale 的存档文本（批次 5.2 分级取值：zh/en 主列 → extra 补档命中 → 回退）
function localeText(
  zh: string | null | undefined,
  en: string | null | undefined,
  extra?: Record<string, string> | null,
): string {
  const loc = currentLocale().toLowerCase()
  if (loc.startsWith("zh")) return zh || en || ""
  if (loc.startsWith("en")) return en || zh || ""
  if (extra) {
    const lang = loc.split("-")[0]
    const hit = Object.keys(extra).find(
      (k) => (k.toLowerCase() === loc || k.toLowerCase() === lang) && extra[k],
    )
    if (hit) return extra[hit]
  }
  return zh || en || ""
}

async function fetchPlaza() {
  loading.value = true
  try {
    if (search.value.trim()) {
      // F-33：语义搜索（BGE-M3 / 降级哈希向量 + 关键词兜底），返回含 similarity
      const res = await request.get("/plaza/search", { params: { q: search.value.trim(), top_k: 50 } })
      const data = res.data as PlazaSearchResponse
      plazas.value = data.items || []
      total.value = data.total || 0
      searchMode.value = true
    } else {
      const res = await request.get("/plaza", { params: { page: page.value, page_size: pageSize.value } })
      plazas.value = res.data.items || []
      total.value = res.data.total || 0
      searchMode.value = false
    }
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  search.value = ""
  page.value = 1
  fetchPlaza()
}

async function fetchBlocked() {
  blockedLoading.value = true
  try {
    const res = await request.get("/plaza/blocked", {
      params: { page: blockedPage.value, page_size: blockedPageSize.value },
    })
    blocked.value = res.data.items || []
    blockedTotal.value = res.data.total || 0
  } finally {
    blockedLoading.value = false
  }
}

function onTabChange(name: string | number) {
  if (name === "blocked") fetchBlocked()
  else fetchPlaza()
}

function openDetail(row: PlazaSkill) {
  detailTarget.value = row
  detailVisible.value = true
}

// README 弹窗：读广场副本双语 README（GET /plaza/{id}/readme），按 locale 选取
async function openReadme(row: PlazaSkill) {
  readmeName.value = row.skill_name
  readmeContent.value = ""
  readmeLoading.value = true
  readmeVisible.value = true
  try {
    const res = await request.get(`/plaza/${row.plaza_id}/readme`)
    const data = res.data as PlazaReadme
    readmeContent.value = localeText(data.readme_zh, data.readme_en)
  } finally {
    readmeLoading.value = false
  }
}

// 添加至我的：复制广场副本到个人库（origin=PLAZA，status=ENABLED 可直接使用）
// 拦截器已对 code!=0 统一弹错并 reject；批次 6.2：code=10006 编码冲突不弹通用错，
// 转二选一弹窗（覆盖本人已有副本 / 换码重试），其余错误由拦截器提示
interface CopyConflictData {
  conflict_skill_id?: number
  conflict_code?: string
  overwrite_available?: boolean
}
const conflictVisible = ref(false)
const conflictRow = ref<PlazaSkill | null>(null)
const conflictData = ref<CopyConflictData>({})
const conflictNewCode = ref("")
const conflictLoading = ref(false)

function openConflictDialog(row: PlazaSkill, data: unknown) {
  conflictRow.value = row
  conflictData.value = (data as CopyConflictData) || {}
  conflictNewCode.value = ""
  conflictVisible.value = true
}

// 冲突后再提交（overwrite / retry）：再次 10006 时刷新冲突数据保持弹窗打开
async function submitConflictCopy(body: Record<string, unknown>) {
  const row = conflictRow.value
  if (!row) return
  conflictLoading.value = true
  try {
    await request.post(`/plaza/${row.plaza_id}/copy`, body)
    ElMessage.success(t("plaza.copySuccess"))
    conflictVisible.value = false
    detailVisible.value = false
  } catch (err) {
    if (err instanceof ApiError && err.code === 10006) {
      conflictData.value = (err.data as CopyConflictData) || conflictData.value
    }
  } finally {
    conflictLoading.value = false
  }
}

function confirmOverwrite() {
  void submitConflictCopy({ conflict_resolution: "overwrite" })
}

async function confirmRetry() {
  const code = conflictNewCode.value.trim()
  if (!code) {
    ElMessage.warning(t("plaza.conflictNewCodeRequired"))
    return
  }
  await submitConflictCopy({ conflict_resolution: "retry", new_code: code })
}

async function copyToMy(row: PlazaSkill) {
  try {
    await ElMessageBox.confirm(
      t("plaza.copyConfirmMsg", { name: row.skill_name }),
      t("plaza.copyConfirmTitle"),
      { type: "warning" },
    )
  } catch {
    return
  }
  try {
    await request.post(`/plaza/${row.plaza_id}/copy`)
    ElMessage.success(t("plaza.copySuccess"))
    detailVisible.value = false
  } catch (err) {
    if (err instanceof ApiError && err.code === 10006) openConflictDialog(row, err.data)
  }
}

// 屏蔽：二次确认 + 可选原因（F-34，屏蔽后双端不可见，仅黑名单页可见，可撤销）
async function blockSkill(row: PlazaSkill) {
  let reason = ""
  try {
    const r = await ElMessageBox.prompt(
      t("plaza.blockConfirmMsg"),
      t("plaza.blockConfirmTitle"),
      { inputPlaceholder: t("plaza.blockReasonPlaceholder"), inputValidator: () => true },
    )
    reason = r.value || ""
  } catch {
    return
  }
  await request.post("/plaza/block", { plaza_id: row.plaza_id, reason: reason || null })
  ElMessage.success(t("plaza.blockSuccess"))
  fetchPlaza()
}

// 撤销屏蔽（黑名单页签）
async function unblock(entry: BlockedSkill) {
  const payload =
    entry.target_type === "plaza" ? { plaza_id: entry.target_id } : { skill_id: entry.target_id }
  await request.post("/plaza/unblock", payload)
  ElMessage.success(t("plaza.unblockSuccess"))
  fetchBlocked()
}

// 停用广场 Skill（仅 admin）：停用后双端不可见，版本存档与审计保留，可经重新分享恢复
async function disablePlaza(row: PlazaSkill) {
  try {
    await ElMessageBox.confirm(
      t("plaza.disableConfirmMsg", { name: row.skill_name }),
      t("plaza.disableConfirmTitle"),
      { type: "warning" },
    )
  } catch {
    return
  }
  await request.post(`/plaza/${row.plaza_id}/disable`)
  ElMessage.success(t("common.disabled"))
  fetchPlaza()
}

// 黑名单 RM：广场项读 /plaza/{id}/readme，个人项读 /skills/{id}/versions 最新存档
async function openBlockedReadme(entry: BlockedSkill) {
  readmeName.value = entry.skill_name || entry.skill_code || ""
  readmeContent.value = ""
  readmeLoading.value = true
  readmeVisible.value = true
  try {
    if (entry.target_type === "plaza" && entry.target_id != null) {
      const res = await request.get(`/plaza/${entry.target_id}/readme`)
      const data = res.data as PlazaReadme
      readmeContent.value = localeText(data.readme_zh, data.readme_en)
    } else if (entry.target_id != null) {
      const res = await request.get(`/skills/${entry.target_id}/versions`)
      const data = res.data as SkillVersionsResponse
      const latest = data.versions?.[0]
      readmeContent.value = latest ? localeText(latest.readme_zh, latest.readme_en, latest.readme_extra) : ""
    }
  } finally {
    readmeLoading.value = false
  }
}

function involveLabels(flags: string[]): string[] {
  const out: string[] = []
  if (flags.includes("database")) out.push(t("plaza.involveDatabase"))
  if (flags.includes("server")) out.push(t("plaza.involveServer"))
  return out
}

// ===== 版本历史弹窗（admin，批次4 回滚开放）=====
const versionsVisible = ref(false)
const versionsTarget = ref<PlazaSkill | null>(null)
const versionsLoading = ref(false)
const versions = ref<PlazaVersionItem[]>([])
const currentVersion = ref("")
const rollingBack = ref(false)

const versionColumns = computed<DataColumn[]>(() => [
  { key: "version", label: t("plaza.versionColVersion"), cls: "text-mono" },
  { key: "source_version", label: t("plaza.versionColSourceVersion"), cls: "text-mono" },
  { key: "file_count", label: t("plaza.versionColFiles"), align: "center" },
  { key: "audit_passed", label: t("plaza.versionColAudit"), align: "center" },
  { key: "created_at", label: t("plaza.versionColCreatedAt") },
  { key: "actions", label: t("common.colActions") },
])

// 打开版本历史：GET /plaza/{id}/versions（含当前生效版本）
async function openVersions(row: PlazaSkill) {
  versionsTarget.value = row
  versions.value = []
  currentVersion.value = ""
  versionsVisible.value = true
  versionsLoading.value = true
  try {
    const res = await request.get(`/plaza/${row.plaza_id}/versions`)
    versions.value = res.data.versions || []
    currentVersion.value = res.data.current_version || ""
  } finally {
    versionsLoading.value = false
  }
}

// 回滚到此版（admin，二次确认）：归档内容生效 + 持有者标记迭代，不新建版本行
async function rollbackVersion(v: PlazaVersionItem) {
  const row = versionsTarget.value
  if (!row) return
  try {
    await ElMessageBox.confirm(
      t("plaza.rollbackConfirmMsg", { name: row.skill_name, version: v.version }),
      t("plaza.rollbackConfirmTitle"),
      { type: "warning" },
    )
  } catch {
    return
  }
  rollingBack.value = true
  try {
    const res = await request.post(`/plaza/${row.plaza_id}/versions/${v.version}/rollback`)
    ElMessage.success(t("plaza.rollbackSuccess", {
      version: res.data?.to_version ?? v.version,
      count: res.data?.holders_marked ?? 0,
    }))
    versionsVisible.value = false
    fetchPlaza()
  } finally {
    rollingBack.value = false
  }
}

onMounted(fetchPlaza)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("plaza.title") }}</h2>
      <p>{{ t("plaza.subtitle") }}</p>
    </div>

    <el-tabs v-model="activeTab" class="plaza-tabs" @tab-change="onTabChange">
      <!-- ===== Skill 广场 ===== -->
      <el-tab-pane :label="t('plaza.tabPlaza')" name="plaza">
        <div class="card">
          <div class="toolbar">
            <div class="toolbar-left">
              <input
                type="text"
                class="search-input"
                v-model="search"
                :placeholder="t('plaza.searchPlaceholder')"
                @keyup.enter="fetchPlaza"
              />
              <button class="btn btn-primary" @click="fetchPlaza">{{ t("plaza.searchBtn") }}</button>
              <button class="btn" @click="resetSearch">{{ t("common.reset") }}</button>
            </div>
          </div>
          <DataTable
            :columns="plazaColumns"
            :rows="plazas"
            :loading="loading"
            :empty-text="t('plaza.emptyPlaza')"
            row-key="plaza_id"
            table-class="plaza-table"
          >
            <template #involve="{ row }">
              <template v-if="involveLabels(row.involve_flags).length">
                <span
                  v-for="lbl in involveLabels(row.involve_flags)"
                  :key="lbl"
                  class="tag tag-warning involve-tag"
                >{{ lbl }}</span>
              </template>
              <span v-else>{{ t("plaza.involveNone") }}</span>
            </template>
            <template #similarity="{ row }">
              {{ row.similarity != null ? row.similarity.toFixed(3) : "-" }}
            </template>
            <template #status="{ row }">
              <span class="status-dot" :class="row.status === 'PUBLISHED' ? 'active' : 'inactive'">
                {{ row.status === "PUBLISHED" ? t("plaza.statusPublished") : t("common.disabled") }}
              </span>
            </template>
            <!-- 已停用项：双端不可见口径，仅保留状态标记（恢复经重新分享链路） -->
            <template #actions="{ row }">
              <template v-if="row.status === 'PUBLISHED'">
                <button class="btn btn-sm" @click="openDetail(row)">{{ t("common.detail") }}</button>
                <button class="btn btn-sm" @click="openReadme(row)">{{ t("common.readmeAction") }}</button>
                <button class="btn btn-sm btn-primary" @click="copyToMy(row)">{{ t("plaza.copyAction") }}</button>
                <button class="btn btn-sm btn-danger" @click="blockSkill(row)">{{ t("plaza.blockAction") }}</button>
                <button v-if="isAdmin" class="btn btn-sm" @click="openVersions(row)">{{ t("plaza.versionAction") }}</button>
                <button v-if="isAdmin" class="btn btn-sm btn-danger" @click="disablePlaza(row)">{{ t("common.disable") }}</button>
              </template>
              <span v-else>-</span>
            </template>
          </DataTable>
          <Pagination
            v-if="!searchMode"
            v-model:page="page"
            v-model:pageSize="pageSize"
            :total="total"
            @change="fetchPlaza"
          />
        </div>
      </el-tab-pane>

      <!-- ===== Skill 黑名单 ===== -->
      <el-tab-pane :label="t('plaza.tabBlocked')" name="blocked">
        <div class="card">
          <DataTable
            :columns="blockedColumns"
            :rows="blocked"
            :loading="blockedLoading"
            :empty-text="t('plaza.emptyBlocked')"
            row-key="id"
            table-class="blocked-table"
          >
            <template #created_at="{ row }">{{ row.created_at?.replace("T", " ").slice(0, 19) || "—" }}</template>
            <template #actions="{ row }">
              <button class="btn btn-sm" @click="openBlockedReadme(row)">{{ t("common.readmeAction") }}</button>
              <button class="btn btn-sm btn-primary" @click="unblock(row)">{{ t("plaza.unblockAction") }}</button>
            </template>
          </DataTable>
          <Pagination
            v-model:page="blockedPage"
            v-model:pageSize="blockedPageSize"
            :total="blockedTotal"
            @change="fetchBlocked"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="t('plaza.detailTitle', { name: detailTarget?.skill_name ?? '' })" width="600">
      <div v-if="detailTarget" class="detail-body">
        <p><b>{{ t("common.skillCode") }}</b> {{ detailTarget.skill_code }}</p>
        <p><b>{{ t("common.skillName") }}</b> {{ detailTarget.skill_name }}</p>
        <p><b>{{ t("plaza.detailInvolve") }}</b>
          <template v-if="involveLabels(detailTarget.involve_flags).length">
            <span
              v-for="lbl in involveLabels(detailTarget.involve_flags)"
              :key="lbl"
              class="tag tag-warning involve-tag"
            >{{ lbl }}</span>
          </template>
          <span v-else>{{ t("plaza.involveNone") }}</span>
        </p>
        <p><b>{{ t("plaza.detailStatus") }}</b> {{ t("plaza.statusPublished") }}</p>
        <p v-if="detailTarget.iteration_note"><b>{{ t("plaza.detailIterationNote") }}</b> {{ detailTarget.iteration_note }}</p>
        <p><b>{{ t("plaza.detailCreatedAt") }}</b> {{ detailTarget.created_at?.replace("T", " ").slice(0, 19) || "-" }}</p>
        <p><b>{{ t("plaza.detailUpdatedAt") }}</b> {{ detailTarget.updated_at?.replace("T", " ").slice(0, 19) || "-" }}</p>
      </div>
      <template #footer>
        <button class="btn" @click="detailVisible = false">{{ t("common.cancel") }}</button>
        <button class="btn btn-primary" @click="copyToMy(detailTarget!)">{{ t("plaza.copyAction") }}</button>
      </template>
    </el-dialog>

    <!-- README 弹窗（按 locale 取双语 README） -->
    <el-dialog v-model="readmeVisible" :title="t('plaza.readmeTitle', { name: readmeName })" width="700">
      <div v-if="readmeLoading">{{ t("common.loading") }}</div>
      <pre v-else-if="readmeContent" class="readme-body">{{ readmeContent }}</pre>
      <p v-else>{{ t("plaza.readmeEmpty") }}</p>
    </el-dialog>

    <!-- 复制冲突弹窗（批次 6.2：10006 编码冲突二选一——覆盖本人已有副本 / 换码重试） -->
    <el-dialog v-model="conflictVisible" :title="t('plaza.conflictTitle')" width="480">
      <p class="conflict-msg">{{ t("plaza.conflictMsg", { code: conflictData.conflict_code ?? conflictRow?.skill_code ?? "" }) }}</p>
      <label class="conflict-label">{{ t("plaza.conflictNewCodeLabel") }}</label>
      <input type="text" class="form-input" v-model="conflictNewCode" :placeholder="t('plaza.conflictNewCodePlaceholder')">
      <template #footer>
        <button class="btn" @click="conflictVisible = false">{{ t("common.cancel") }}</button>
        <button
          v-if="conflictData.overwrite_available"
          class="btn btn-warning"
          :disabled="conflictLoading"
          @click="confirmOverwrite"
        >{{ t("plaza.conflictOverwrite") }}</button>
        <button class="btn btn-primary" :disabled="conflictLoading" @click="confirmRetry">{{ t("plaza.conflictRetry") }}</button>
      </template>
    </el-dialog>

    <!-- 版本历史弹窗（admin，批次4）：版本列表 + 回滚（归档内容生效，持有者标记迭代） -->
    <el-dialog v-model="versionsVisible" :title="t('plaza.versionTitle', { name: versionsTarget?.skill_name ?? '' })" width="760">
      <DataTable
        :columns="versionColumns"
        :rows="versions"
        :loading="versionsLoading"
        :empty-text="t('plaza.versionEmpty')"
        row-key="version"
        table-class="version-table"
      >
        <template #version="{ row }">
          <span class="text-mono">v{{ row.version }}</span>
          <span v-if="row.version === currentVersion" class="tag tag-primary current-tag">{{ t("plaza.versionCurrentTag") }}</span>
        </template>
        <template #audit_passed="{ row }">
          <span :class="row.audit_passed === true ? 'audit-pass' : row.audit_passed === false ? 'audit-fail' : ''">
            {{ row.audit_passed === true ? t("skill.auditPassed") : row.audit_passed === false ? t("skill.auditFailed") : "-" }}
          </span>
        </template>
        <template #created_at="{ row }">{{ row.created_at?.replace("T", " ").slice(0, 19) || "—" }}</template>
        <template #actions="{ row }">
          <button
            class="btn btn-sm btn-danger"
            :disabled="rollingBack || row.version === currentVersion"
            @click="rollbackVersion(row)"
          >{{ t("plaza.rollbackAction") }}</button>
        </template>
      </DataTable>
    </el-dialog>
  </div>
</template>

<style scoped>
.plaza-tabs { margin-bottom: 4px; }
.involve-tag { margin-right: 4px; }
.empty-cell { text-align: center; color: var(--color-text-secondary); padding: 24px 0; }
.detail-body p { margin: 6px 0; font-size: 14px; }
.readme-body { white-space: pre-wrap; word-break: break-word; background: #f7f8fa; border-radius: 6px; padding: 12px; max-height: 420px; overflow: auto; font-size: 13px; line-height: 1.6; }
.conflict-msg { margin: 0 0 12px; font-size: 14px; line-height: 1.6; }
.conflict-label { display: block; font-size: 13px; color: #666; margin-bottom: 6px; }
.current-tag { margin-left: 6px; }
.audit-pass { color: #67c23a; }
.audit-fail { color: #f56c6c; }
</style>
