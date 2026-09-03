<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Skill, SkillAuditRule } from "@/types"

const { t } = useI18n()
const loading = ref(false)
const skills = ref<Skill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")
const statusFilter = ref("")

const reviewVisible = ref(false)
const reviewTarget = ref<Skill | null>(null)
const reviewComment = ref("")

const uploadVisible = ref(false)
const uploadFile = ref<File | null>(null)
const uploadLoading = ref(false)

const auditVisible = ref(false)
const auditLoading = ref(false)
const auditRules = ref<SkillAuditRule[]>([])
const auditSkillName = ref("")

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

function openUpload() {
  uploadFile.value = null
  uploadVisible.value = true
}

function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files[0]) {
    const f = input.files[0]
    if (!f.name.endsWith(".zip") && !f.name.endsWith(".7z")) {
      ElMessage.error(t("skill.uploadFormatError"))
      return
    }
    uploadFile.value = f
  }
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

async function handleStatus(skill: Skill, status: string) {
  await request.put(`/skills/${skill.id}/status`, { status })
  ElMessage.success(t("common.statusUpdated"))
  fetchSkills()
}

function openReview(skill: Skill) {
  reviewTarget.value = skill
  reviewComment.value = ""
  reviewVisible.value = true
}

async function submitReview(action: string) {
  await request.post(`/skills/${reviewTarget.value!.id}/review`, { action, comment: reviewComment.value })
  ElMessage.success(t("skill.reviewDone"))
  reviewVisible.value = false
  fetchSkills()
}

async function openAuditReport(skill: Skill) {
  auditSkillName.value = skill.skill_name
  auditRules.value = []
  auditLoading.value = true
  auditVisible.value = true
  try {
    const res = await request.get(`/skills/${skill.id}/audit-report`)
    const data = res.data as { rules?: SkillAuditRule[] }
    if (data) {
      auditRules.value = data.rules || []
    }
  } finally {
    auditLoading.value = false
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

function statusLabel(status: string) {
  const map: Record<string, string> = {
    ENABLED: t("skill.stateEnabled"),
    DISABLED: t("skill.stateDisabled"),
    PENDING_REVIEW: t("skill.statePending"),
    REJECTED: t("skill.stateRejected"),
  }
  return map[status] || status
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
            <option value="ENABLED">{{ t("skill.stateEnabled") }}</option>
            <option value="PENDING_REVIEW">{{ t("skill.statePending") }}</option>
            <option value="DISABLED">{{ t("skill.stateDisabled") }}</option>
          </select>
          <button class="btn" @click="fetchSkills">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openUpload">{{ t("skill.add") }}</button>
        </div>
      </div>
      <table class="data-table">
        <thead><tr>
          <th>{{ t("skill.colCode") }}</th><th>{{ t("skill.colName") }}</th><th>{{ t("skill.colStatus") }}</th><th>{{ t("skill.colAudit") }}</th><th>{{ t("skill.colToolCount") }}</th><th>{{ t("skill.colRegister") }}</th><th>{{ t("skill.colDescription") }}</th><th>{{ t("skill.colActions") }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in skills" :key="row.id">
            <td class="text-mono">{{ row.skill_code }}</td>
            <td>{{ row.skill_name }}</td>
            <td><span class="status-dot" :class="row.status === 'ENABLED' ? 'active' : row.status === 'PENDING_REVIEW' ? 'pending' : 'inactive'">{{ statusLabel(row.status) }}</span></td>
            <td>
              <span v-if="row.audit_status" class="status-dot" :class="row.audit_status === 'passed' ? 'active' : row.audit_status === 'failed' ? 'inactive' : 'pending'">{{ auditStatusLabel(row.audit_status) }}</span>
              <el-button v-if="row.audit_status" link type="primary" size="small" @click="openAuditReport(row)">{{ t("common.detail") }}</el-button>
            </td>
            <td>{{ row.tool_count }}</td>
            <td><span class="tag" :class="row.register_method === 'decorator' ? 'tag-primary' : 'tag-info'">{{ row.register_method === 'decorator' ? t("skill.registerDecorator") : row.register_method }}</span></td>
            <td>{{ row.description }}</td>
            <td class="actions">
              <button v-if="row.status === 'PENDING_REVIEW'" class="btn btn-sm btn-success" @click="openReview(row)">{{ t("skill.reviewAction") }}</button>
              <button v-if="row.status === 'ENABLED'" class="btn btn-sm btn-danger" @click="handleStatus(row, 'DISABLED')">{{ t("common.disable") }}</button>
              <button v-if="row.status === 'DISABLED'" class="btn btn-sm btn-primary" @click="handleStatus(row, 'ENABLED')">{{ t("common.enable") }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchSkills" />
    </div>

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

    <el-dialog v-model="reviewVisible" :title="t('skill.reviewTitle')" width="500">
      <div v-if="reviewTarget" class="review-info">
        <p><b>{{ t("skill.reviewCode") }}</b> {{ reviewTarget.skill_code }}</p>
        <p><b>{{ t("skill.reviewName") }}</b> {{ reviewTarget.skill_name }}</p>
        <p><b>{{ t("skill.reviewAudit") }}</b> {{ auditStatusLabel(reviewTarget.audit_status) }}</p>
        <p v-if="reviewTarget.source_format"><b>{{ t("skill.reviewFormat") }}</b> {{ reviewTarget.source_format }}</p>
      </div>
      <el-input v-model="reviewComment" type="textarea" :rows="3" :placeholder="t('skill.reviewCommentPlaceholder')" style="margin-top: 12px" />
      <template #footer>
        <el-button type="danger" @click="submitReview('reject')">{{ t("skill.reviewReject") }}</el-button>
        <el-button type="success" @click="submitReview('approve')">{{ t("skill.reviewApprove") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="auditVisible" :title="t('skill.auditReportTitle')" width="700">
      <p class="audit-title">{{ auditSkillName }}</p>
      <div v-if="auditLoading">{{ t("common.loading") }}</div>
      <table v-else-if="auditRules.length" class="data-table">
        <thead><tr><th>{{ t("skill.auditColRule") }}</th><th>{{ t("skill.auditColSeverity") }}</th><th>{{ t("skill.auditColFile") }}</th><th>{{ t("skill.auditColLine") }}</th><th>{{ t("skill.auditColDescription") }}</th><th>{{ t("skill.auditColSuggestion") }}</th></tr></thead>
        <tbody>
          <tr v-for="r in auditRules" :key="r.rule_id + r.file_path + r.line_number">
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
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.review-info p { margin: 4px 0; }
.upload-area { text-align: center; padding: 20px 0; }
.upload-area p { margin: 8px 0; color: #666; }
.upload-file-info { color: #409eff; font-weight: 500; }
.audit-title { font-weight: 600; font-size: 15px; margin-bottom: 12px; }
</style>
