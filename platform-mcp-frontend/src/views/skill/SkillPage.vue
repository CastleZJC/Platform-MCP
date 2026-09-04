<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage, ElMessageBox } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import { useUserStore } from "@/stores/user"
import { currentLocale } from "@/i18n"
import type { Skill, SkillAuditRule, SkillVersion, SkillVersionsResponse, SkillAuditReportResponse } from "@/types"

const { t } = useI18n()
const userStore = useUserStore()
// V3.0 M2.7：按当前 locale 选择双语存档（README / 报告）；zh* 取中文，其余取英文
const isZh = computed(() => currentLocale().startsWith("zh"))
const username = computed(() => userStore.user?.username ?? "")
const isAdmin = computed(() => userStore.isAdmin)

const loading = ref(false)
const skills = ref<Skill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")
const statusFilter = ref("")

// 审核弹窗（仅 admin，仅审核中）
const reviewVisible = ref(false)
const reviewTarget = ref<Skill | null>(null)
const reviewComment = ref("")
const reviewReports = ref<SkillAuditRule[]>([])
const reviewVersion = ref<SkillVersion | null>(null)
const reviewLoading = ref(false)

// 上传弹窗（新建）
const uploadVisible = ref(false)
const uploadFile = ref<File | null>(null)
const uploadLoading = ref(false)

// README 图标弹窗（按 locale）
const readmeVisible = ref(false)
const readmeLoading = ref(false)
const readmeContent = ref("")
const readmeSkillName = ref("")

// 分享管理 Sheet（owner：分享 / 更新 / 撤回 / 迭代 + 逐版本审核日志）
const sheetVisible = ref(false)
const sheetTarget = ref<Skill | null>(null)
const updateFile = ref<File | null>(null)
const sheetLoading = ref(false)
const sheetVersions = ref<SkillVersion[]>([])
const sheetLogLoading = ref(false)

// 版本审核反馈弹窗（Sheet 日志"详情"，展示该版本双语存档报告）
const versionReportVisible = ref(false)
const versionReportContent = ref("")
const versionReportName = ref("")

function isOwner(skill: Skill): boolean {
  return !!username.value && skill.submitted_by === username.value
}

// owner 可经 Sheet 操作的状态（分享 / 更新 / 撤回 / 迭代）
const SHEET_STATES = ["DRAFT", "ENABLED", "DISABLED", "PENDING_REVIEW", "REJECTED", "WITHDRAWN", "SHARE_ITERATION"]
function canManage(skill: Skill): boolean {
  return isOwner(skill) && SHEET_STATES.includes(skill.status)
}

async function fetchSkills() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await request.get("/skills", { params })
    skills.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function pickFile(e: Event): File | null {
  const input = e.target as HTMLInputElement
  const f = input.files && input.files[0]
  if (!f) return null
  if (!f.name.endsWith(".zip") && !f.name.endsWith(".7z")) {
    ElMessage.error(t("skill.uploadFormatError"))
    return null
  }
  return f
}

function openUpload() {
  uploadFile.value = null
  uploadVisible.value = true
}

function handleFileChange(e: Event) {
  const f = pickFile(e)
  if (f) uploadFile.value = f
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning(t("skill.uploadNoFile"))
    return
  }
  uploadLoading.value = true
  try {
    const formData = new FormData()
    formData.append("file", uploadFile.value)
    await request.post("/skills/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    ElMessage.success(t("skill.uploadSuccess"))
    uploadVisible.value = false
    fetchSkills()
  } catch {
    ElMessage.error(t("skill.uploadFailed"))
  } finally {
    uploadLoading.value = false
  }
}

// admin 启停（沿用 update_skill_status）
async function handleStatus(skill: Skill, status: string) {
  await request.put(`/skills/${skill.id}/status`, { status })
  ElMessage.success(t("common.statusUpdated"))
  fetchSkills()
}

// 选取当前 locale 的存档文本（带另一语言兜底）
function localeText(zh: string | null | undefined, en: string | null | undefined): string {
  return (isZh.value ? zh || en : en || zh) || ""
}

// README 图标弹窗：读取版本存档最新条目的双语 README
async function openReadme(skill: Skill) {
  readmeSkillName.value = skill.skill_name
  readmeContent.value = ""
  readmeLoading.value = true
  readmeVisible.value = true
  try {
    const res = await request.get(`/skills/${skill.id}/versions`)
    const data = res.data as SkillVersionsResponse
    const latest = data.versions?.[0]
    readmeContent.value = latest ? localeText(latest.readme_zh, latest.readme_en) : ""
  } finally {
    readmeLoading.value = false
  }
}

// 审核弹窗（admin，仅 PENDING_REVIEW）：报告 + 推荐结论/README（来自版本存档）
async function openReview(skill: Skill) {
  reviewTarget.value = skill
  reviewComment.value = ""
  reviewReports.value = []
  reviewVersion.value = null
  reviewVisible.value = true
  reviewLoading.value = true
  try {
    const [reportRes, versionRes] = await Promise.all([
      request.get(`/skills/${skill.id}/audit-report`),
      request.get(`/skills/${skill.id}/versions`),
    ])
    reviewReports.value = (reportRes.data as SkillAuditReportResponse).reports || []
    const versions = (versionRes.data as SkillVersionsResponse).versions || []
    reviewVersion.value = versions[0] || null
  } finally {
    reviewLoading.value = false
  }
}

const reviewReport = computed(() =>
  reviewVersion.value ? localeText(reviewVersion.value.report_zh, reviewVersion.value.report_en) : ""
)
const reviewReadme = computed(() =>
  reviewVersion.value ? localeText(reviewVersion.value.readme_zh, reviewVersion.value.readme_en) : ""
)

async function submitReview(action: string) {
  await request.post(`/skills/${reviewTarget.value!.id}/review`, {
    action,
    comment: reviewComment.value,
  })
  ElMessage.success(t("skill.reviewDone"))
  reviewVisible.value = false
  fetchSkills()
}

// ===== 分享管理 Sheet（owner）=====
// 打开即拉取版本存档：逐版本审核日志（每次审计的反馈及信息）
async function openSheet(skill: Skill) {
  sheetTarget.value = skill
  updateFile.value = null
  sheetVersions.value = []
  sheetVisible.value = true
  sheetLogLoading.value = true
  try {
    const res = await request.get(`/skills/${skill.id}/versions`)
    sheetVersions.value = (res.data as SkillVersionsResponse).versions || []
  } finally {
    sheetLogLoading.value = false
  }
}

// 版本审计结论：audit_snapshot.passed（无快照 → null 展示 "-"）
function versionPassed(v: SkillVersion): boolean | null {
  const snap = v.audit_snapshot as { passed?: boolean } | null
  if (!snap) return null
  return snap.passed === true
}

// 版本审核反馈详情：展示该版本双语存档报告（按 locale）
function openVersionReport(v: SkillVersion) {
  versionReportName.value = `v${v.version}`
  versionReportContent.value = localeText(v.report_zh, v.report_en)
  versionReportVisible.value = true
}

// F-31 重复分享：已分享 / 审核管线中 → 前端预检二次确认（后端 10005 为安全网）
const needReshareConfirm = computed(() => {
  const s = sheetTarget.value
  if (!s) return false
  return s.share_status === "shared" || ["PENDING_REVIEW", "APPROVED", "SHARE_ITERATION"].includes(s.status)
})

async function submitShare() {
  const s = sheetTarget.value
  if (!s) return
  let confirmReshare = false
  if (needReshareConfirm.value) {
    try {
      await ElMessageBox.confirm(t("skill.reshareConfirmMsg"), t("skill.reshareConfirmTitle"), {
        type: "warning",
      })
      confirmReshare = true
    } catch {
      return
    }
  }
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/submit`, { confirm_reshare: confirmReshare })
    ElMessage.success(t("skill.submitSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

async function withdrawShare() {
  const s = sheetTarget.value
  if (!s) return
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/withdraw`)
    ElMessage.success(t("skill.withdrawSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

async function resolveIteration(choice: "iterate" | "keep") {
  const s = sheetTarget.value
  if (!s) return
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/resolve-iteration`, { choice })
    ElMessage.success(t("skill.resolveSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

function handleUpdateFileChange(e: Event) {
  const f = pickFile(e)
  if (f) updateFile.value = f
}

// 更新（重新上传同编码包 → 后端 upsert + 状态机联动 REVISE/RESTORE）
async function submitUpdate() {
  if (!updateFile.value) {
    ElMessage.warning(t("skill.uploadNoFile"))
    return
  }
  sheetLoading.value = true
  try {
    const formData = new FormData()
    formData.append("file", updateFile.value)
    await request.post("/skills/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    ElMessage.success(t("skill.updateSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } catch {
    ElMessage.error(t("skill.uploadFailed"))
  } finally {
    sheetLoading.value = false
  }
}

function severityTag(severity: string) {
  if (severity === "critical") return "danger"
  if (severity === "warning") return "warning"
  return "info"
}

function auditStatusLabel(status: string | null) {
  const map: Record<string, string> = {
    pending: t("skill.auditPending"),
    passed: t("skill.auditPassed"),
    failed: t("skill.auditFailed"),
  }
  return map[status || ""] || status || "-"
}

// 8 状态生命周期标签（勘误：此前仅 4 状态）
function statusLabel(status: string) {
  const map: Record<string, string> = {
    DRAFT: t("skill.stateDraft"),
    PENDING_REVIEW: t("skill.statePending"),
    APPROVED: t("skill.stateApproved"),
    REJECTED: t("skill.stateRejected"),
    SHARE_ITERATION: t("skill.stateShareIteration"),
    ENABLED: t("skill.stateEnabled"),
    DISABLED: t("skill.stateDisabled"),
    WITHDRAWN: t("skill.stateWithdrawn"),
  }
  return map[status] || status
}

function statusDotClass(status: string) {
  if (status === "ENABLED" || status === "APPROVED") return "active"
  if (status === "PENDING_REVIEW" || status === "SHARE_ITERATION") return "pending"
  return "inactive"
}

function originLabel(origin: string | null | undefined) {
  if (origin === "PLAZA") return t("skill.originPlaza")
  if (origin) return t("skill.originSelf")
  return "-"
}

onMounted(fetchSkills)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("skill.title") }}</h2>
      <p>{{ t("skill.subtitle") }}</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" :placeholder="t('skill.searchPlaceholder')" @keyup.enter="fetchSkills">
          <select class="form-select" v-model="statusFilter" @change="fetchSkills">
            <option value="">{{ t("common.allStatus") }}</option>
            <option value="DRAFT">{{ t("skill.stateDraft") }}</option>
            <option value="PENDING_REVIEW">{{ t("skill.statePending") }}</option>
            <option value="APPROVED">{{ t("skill.stateApproved") }}</option>
            <option value="REJECTED">{{ t("skill.stateRejected") }}</option>
            <option value="SHARE_ITERATION">{{ t("skill.stateShareIteration") }}</option>
            <option value="ENABLED">{{ t("skill.stateEnabled") }}</option>
            <option value="DISABLED">{{ t("skill.stateDisabled") }}</option>
            <option value="WITHDRAWN">{{ t("skill.stateWithdrawn") }}</option>
          </select>
          <button class="btn" @click="fetchSkills">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openUpload">{{ t("skill.add") }}</button>
        </div>
      </div>
      <table class="data-table">
        <thead><tr>
          <th>{{ t("skill.colCode") }}</th><th>{{ t("skill.colName") }}</th><th>{{ t("skill.colStatus") }}</th><th>{{ t("skill.colToolCount") }}</th><th>{{ t("skill.colRegister") }}</th><th>{{ t("skill.colActions") }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in skills" :key="row.id">
            <td class="text-mono">{{ row.skill_code }}</td>
            <td>{{ row.skill_name }}</td>
            <td><span class="status-dot" :class="statusDotClass(row.status)">{{ statusLabel(row.status) }}</span></td>
            <td>{{ row.tool_count }}</td>
            <td><span class="tag" :class="row.register_method === 'decorator' ? 'tag-primary' : 'tag-info'">{{ row.register_method === 'decorator' ? t("skill.registerDecorator") : row.register_method }}</span></td>
            <td class="actions">
              <button class="btn btn-sm" @click="openReadme(row)">{{ t("common.readmeAction") }}</button>
              <button v-if="canManage(row)" class="btn btn-sm btn-primary" @click="openSheet(row)">{{ t("skill.manageAction") }}</button>
              <button v-if="isAdmin && row.status === 'PENDING_REVIEW'" class="btn btn-sm btn-success" @click="openReview(row)">{{ t("skill.reviewAction") }}</button>
              <button v-if="isAdmin && row.status === 'ENABLED'" class="btn btn-sm btn-danger" @click="handleStatus(row, 'DISABLED')">{{ t("common.disable") }}</button>
              <button v-if="isAdmin && row.status === 'DISABLED'" class="btn btn-sm btn-primary" @click="handleStatus(row, 'ENABLED')">{{ t("common.enable") }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchSkills" />
    </div>

    <!-- 上传（新建）弹窗 -->
    <el-dialog v-model="uploadVisible" :title="t('skill.uploadTitle')" width="500">
      <div class="upload-area">
        <p>{{ t("skill.uploadHint") }}</p>
        <input type="file" accept=".zip,.7z" @change="handleFileChange" />
        <p v-if="uploadFile" class="upload-file-info">{{ t("skill.uploadSelected", { name: uploadFile.name, size: (uploadFile.size / 1024 / 1024).toFixed(1) }) }}</p>
      </div>
      <template #footer>
        <el-button @click="uploadVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" :loading="uploadLoading" @click="submitUpload">{{ t("skill.uploadSubmit") }}</el-button>
      </template>
    </el-dialog>

    <!-- README 图标弹窗（按 locale 取存档双语 README） -->
    <el-dialog v-model="readmeVisible" :title="t('skill.readmeTitle')" width="700">
      <p class="audit-title">{{ readmeSkillName }}</p>
      <div v-if="readmeLoading">{{ t("common.loading") }}</div>
      <pre v-else-if="readmeContent" class="readme-body">{{ readmeContent }}</pre>
      <p v-else>{{ t("skill.readmeEmpty") }}</p>
    </el-dialog>

    <!-- 审核弹窗（仅 admin，仅审核中）：报告 + 推荐结论/README -->
    <el-dialog v-model="reviewVisible" :title="t('skill.reviewTitle')" width="760">
      <div v-if="reviewTarget" class="review-info">
        <p><b>{{ t("skill.reviewCode") }}</b> {{ reviewTarget.skill_code }}</p>
        <p><b>{{ t("skill.reviewName") }}</b> {{ reviewTarget.skill_name }}</p>
        <p><b>{{ t("skill.reviewAudit") }}</b> {{ auditStatusLabel(reviewTarget.audit_status) }}</p>
        <p><b>{{ t("skill.reviewOrigin") }}</b> {{ originLabel(reviewTarget.origin) }}</p>
        <p v-if="reviewTarget.version"><b>{{ t("skill.reviewVersion") }}</b> {{ reviewTarget.version }}</p>
        <p v-if="reviewTarget.source_format"><b>{{ t("skill.reviewFormat") }}</b> {{ reviewTarget.source_format }}</p>
      </div>
      <div v-if="reviewLoading" class="review-loading">{{ t("common.loading") }}</div>
      <el-tabs v-else class="review-tabs">
        <el-tab-pane :label="t('skill.reviewReportTab')">
          <table v-if="reviewReports.length" class="data-table">
            <thead><tr><th>{{ t("skill.auditColRule") }}</th><th>{{ t("skill.auditColSeverity") }}</th><th>{{ t("skill.auditColFile") }}</th><th>{{ t("skill.auditColLine") }}</th><th>{{ t("skill.auditColDescription") }}</th><th>{{ t("skill.auditColSuggestion") }}</th></tr></thead>
            <tbody>
              <tr v-for="r in reviewReports" :key="r.rule_id + r.file_path + r.line_number">
                <td class="text-mono">{{ r.rule_id }}</td>
                <td><el-tag :type="severityTag(r.severity)" size="small">{{ r.severity }}</el-tag></td>
                <td>{{ r.file_path || '-' }}</td>
                <td>{{ r.line_number || '-' }}</td>
                <td>{{ r.description }}</td>
                <td>{{ r.suggestion || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else>{{ t("skill.auditEmpty") }}</p>
        </el-tab-pane>
        <el-tab-pane :label="t('skill.reviewRecommendTab')">
          <div v-if="reviewReport || reviewReadme">
            <h4 class="recommend-h">{{ t("skill.reviewReportTab") }}</h4>
            <pre class="readme-body">{{ reviewReport }}</pre>
            <h4 class="recommend-h">{{ t("skill.readmeTitle") }}</h4>
            <pre class="readme-body">{{ reviewReadme }}</pre>
          </div>
          <p v-else>{{ t("skill.reviewRecommendEmpty") }}</p>
        </el-tab-pane>
      </el-tabs>
      <el-input v-model="reviewComment" type="textarea" :rows="3" :placeholder="t('skill.reviewCommentPlaceholder')" style="margin-top: 12px" />
      <template #footer>
        <el-button type="danger" @click="submitReview('reject')">{{ t("skill.reviewReject") }}</el-button>
        <el-button v-if="reviewTarget && reviewTarget.origin === 'PLAZA'" type="warning" @click="submitReview('merge')">{{ t("skill.reviewMerge") }}</el-button>
        <el-button type="success" @click="submitReview('approve')">{{ t("skill.reviewApprove") }}</el-button>
      </template>
    </el-dialog>

    <!-- 版本审核反馈弹窗（Sheet 审核日志"详情"：该版本双语存档报告按 locale） -->
    <el-dialog v-model="versionReportVisible" :title="t('skill.versionReportTitle', { version: versionReportName })" width="700">
      <pre v-if="versionReportContent" class="readme-body">{{ versionReportContent }}</pre>
      <p v-else>{{ t("skill.logEmpty") }}</p>
    </el-dialog>

    <!-- 分享管理 Sheet（owner：分享 / 更新 / 撤回 / 迭代） -->
    <el-drawer v-model="sheetVisible" :title="t('skill.sheetTitle', { name: sheetTarget?.skill_name ?? '' })" size="420">
      <div v-if="sheetTarget" class="sheet-body">
        <p class="sheet-status"><b>{{ t("skill.colStatus") }}</b> {{ statusLabel(sheetTarget.status) }}</p>
        <p v-if="sheetTarget.review_comment" class="sheet-comment"><b>{{ t("skill.reviewCommentPlaceholder") }}</b> {{ sheetTarget.review_comment }}</p>

        <!-- 审核日志：逐版本审计反馈（版本 · 日期 · 结论 + 存档报告详情） -->
        <div class="sheet-section">
          <p class="sheet-h">{{ t("skill.logTitle") }}</p>
          <div v-if="sheetLogLoading">{{ t("common.loading") }}</div>
          <template v-else-if="sheetVersions.length">
            <div v-for="v in sheetVersions" :key="v.version" class="log-row">
              <span class="text-mono">v{{ v.version }}</span>
              <span>{{ v.created_at ? v.created_at.slice(0, 10) : "-" }}</span>
              <span :class="versionPassed(v) === true ? 'log-pass' : versionPassed(v) === false ? 'log-fail' : ''">
                {{ versionPassed(v) === true ? t("skill.auditPassed") : versionPassed(v) === false ? t("skill.auditFailed") : "-" }}
              </span>
              <el-button link type="primary" size="small" @click="openVersionReport(v)">{{ t("common.detail") }}</el-button>
            </div>
          </template>
          <p v-else>{{ t("skill.logEmpty") }}</p>
        </div>

        <!-- 分享迭代：采纳合并 / 保留本地 -->
        <div v-if="sheetTarget.status === 'SHARE_ITERATION'" class="sheet-section">
          <p class="sheet-hint">{{ t("skill.resolveHint") }}</p>
          <div class="sheet-actions">
            <el-button type="primary" :loading="sheetLoading" @click="resolveIteration('iterate')">{{ t("skill.resolveIterate") }}</el-button>
            <el-button :loading="sheetLoading" @click="resolveIteration('keep')">{{ t("skill.resolveKeep") }}</el-button>
          </div>
        </div>

        <!-- 审核中：撤回 -->
        <div v-else-if="sheetTarget.status === 'PENDING_REVIEW'" class="sheet-section">
          <div class="sheet-actions">
            <el-button type="warning" :loading="sheetLoading" @click="withdrawShare">{{ t("skill.withdrawAction") }}</el-button>
          </div>
        </div>

        <!-- 其余状态：提交分享（DRAFT/ENABLED/DISABLED，含 F-31 重复分享确认） -->
        <div v-else class="sheet-section">
          <div class="sheet-actions">
            <el-button v-if="['DRAFT', 'ENABLED', 'DISABLED'].includes(sheetTarget.status)" type="success" :loading="sheetLoading" @click="submitShare">{{ t("skill.shareAction") }}</el-button>
          </div>
        </div>

        <!-- 更新（重新上传同编码包） -->
        <div class="sheet-section sheet-update">
          <p class="sheet-hint">{{ t("skill.updateHint") }}</p>
          <input type="file" accept=".zip,.7z" @change="handleUpdateFileChange" />
          <p v-if="updateFile" class="upload-file-info">{{ updateFile.name }}</p>
          <div class="sheet-actions">
            <el-button type="primary" :loading="sheetLoading" @click="submitUpdate">{{ t("skill.updateAction") }}</el-button>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.review-info p { margin: 4px 0; }
.review-loading { padding: 12px 0; color: #666; }
.recommend-h { margin: 12px 0 6px; font-size: 14px; }
.upload-area { text-align: center; padding: 20px 0; }
.upload-area input[type="file"] { display: block; margin: 0 auto; }
.upload-area p { margin: 8px 0; color: #666; }
.upload-file-info { color: #409eff; font-weight: 500; }
.audit-title { font-weight: 600; font-size: 15px; margin-bottom: 12px; }
.readme-body { white-space: pre-wrap; word-break: break-word; background: #f7f8fa; border-radius: 6px; padding: 12px; max-height: 360px; overflow: auto; font-size: 13px; line-height: 1.6; }
.sheet-body { padding: 0 4px; }
.sheet-status { margin: 4px 0 12px; }
.sheet-comment { margin: 4px 0 12px; color: #e6a23c; }
.sheet-section { border-top: 1px solid #ebeef5; padding: 16px 0; }
.sheet-update { }
.sheet-hint { color: #666; font-size: 13px; margin: 0 0 10px; }
.sheet-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.log-row { display: flex; gap: 10px; align-items: center; padding: 4px 0; font-size: 13px; }
.log-pass { color: #67c23a; }
.log-fail { color: #f56c6c; }
</style>
