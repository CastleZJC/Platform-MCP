<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Skill, SkillAuditRule } from "@/types"

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
      ElMessage.error("仅支持 .zip 或 .7z 格式")
      return
    }
    uploadFile.value = f
  }
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning("请选择文件")
    return
  }
  uploadLoading.value = true
  try {
    const formData = new FormData()
    formData.append("file", uploadFile.value)
    await request.post("/skills/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    ElMessage.success("上传成功，等待审核")
    uploadVisible.value = false
    fetchSkills()
  } catch {
    ElMessage.error("上传失败")
  } finally {
    uploadLoading.value = false
  }
}

async function handleStatus(skill: Skill, status: string) {
  await request.put(`/skills/${skill.id}/status`, { status })
  ElMessage.success("状态更新成功")
  fetchSkills()
}

function openReview(skill: Skill) {
  reviewTarget.value = skill
  reviewComment.value = ""
  reviewVisible.value = true
}

async function submitReview(action: string) {
  await request.post(`/skills/${reviewTarget.value!.id}/review`, { action, comment: reviewComment.value })
  ElMessage.success("审核完成")
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
  const map: Record<string, string> = { pending: "待审计", passed: "通过", failed: "不通过" }
  return map[status || ""] || status || "-"
}

function statusLabel(status: string) {
  const map: Record<string, string> = { ENABLED: "已启用", DISABLED: "已禁用", PENDING_REVIEW: "待审核", REJECTED: "已拒绝" }
  return map[status] || status
}

onMounted(fetchSkills)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>Skill 管理</h2>
      <p>管理系统已注册的 MCP Skill 能力模块</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索 Skill 编码 / 名称" @keyup.enter="fetchSkills">
          <select class="form-select" v-model="statusFilter" @change="fetchSkills">
            <option value="">全部状态</option>
            <option value="ENABLED">已启用</option>
            <option value="PENDING_REVIEW">待审核</option>
            <option value="DISABLED">已停用</option>
          </select>
          <button class="btn" @click="fetchSkills">查询</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openUpload">+ 上传 Skill</button>
        </div>
      </div>
      <table class="data-table">
        <thead><tr>
          <th>Skill 编码</th><th>Skill 名称</th><th>状态</th><th>审计</th><th>Tool 数量</th><th>注册方式</th><th>描述</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in skills" :key="row.id">
            <td class="text-mono">{{ row.skill_code }}</td>
            <td>{{ row.skill_name }}</td>
            <td><span class="status-dot" :class="row.status === 'ENABLED' ? 'active' : row.status === 'PENDING_REVIEW' ? 'pending' : 'inactive'">{{ statusLabel(row.status) }}</span></td>
            <td>
              <span v-if="row.audit_status" class="status-dot" :class="row.audit_status === 'passed' ? 'active' : row.audit_status === 'failed' ? 'inactive' : 'pending'">{{ auditStatusLabel(row.audit_status) }}</span>
              <el-button v-if="row.audit_status" link type="primary" size="small" @click="openAuditReport(row)">详情</el-button>
            </td>
            <td>{{ row.tool_count }}</td>
            <td><span class="tag" :class="row.register_method === 'decorator' ? 'tag-primary' : 'tag-info'">{{ row.register_method === 'decorator' ? '装饰器注册' : row.register_method }}</span></td>
            <td>{{ row.description }}</td>
            <td class="actions">
              <button v-if="row.status === 'PENDING_REVIEW'" class="btn btn-sm btn-success" @click="openReview(row)">审核</button>
              <button v-if="row.status === 'ENABLED'" class="btn btn-sm btn-danger" @click="handleStatus(row, 'DISABLED')">停用</button>
              <button v-if="row.status === 'DISABLED'" class="btn btn-sm btn-primary" @click="handleStatus(row, 'ENABLED')">启用</button>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchSkills" />
    </div>

    <el-dialog v-model="uploadVisible" title="上传 Skill 包" width="500">
      <div class="upload-area">
        <p>支持 .zip / .7z 格式，最大 50MB</p>
        <input type="file" accept=".zip,.7z" @change="handleFileChange" />
        <p v-if="uploadFile" class="upload-file-info">已选择: {{ uploadFile.name }} ({{ (uploadFile.size / 1024 / 1024).toFixed(1) }}MB)</p>
      </div>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadLoading" @click="submitUpload">上传</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reviewVisible" title="Skill 审核" width="500">
      <div v-if="reviewTarget" class="review-info">
        <p><b>Skill 编码:</b> {{ reviewTarget.skill_code }}</p>
        <p><b>Skill 名称:</b> {{ reviewTarget.skill_name }}</p>
        <p><b>审计状态:</b> {{ auditStatusLabel(reviewTarget.audit_status) }}</p>
        <p v-if="reviewTarget.source_format"><b>包格式:</b> {{ reviewTarget.source_format }}</p>
      </div>
      <el-input v-model="reviewComment" type="textarea" :rows="3" placeholder="审核意见" style="margin-top: 12px" />
      <template #footer>
        <el-button type="danger" @click="submitReview('reject')">拒绝</el-button>
        <el-button type="success" @click="submitReview('approve')">通过</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="auditVisible" title="审计报告" width="700">
      <p class="audit-title">{{ auditSkillName }}</p>
      <div v-if="auditLoading">加载中...</div>
      <table v-else-if="auditRules.length" class="data-table">
        <thead><tr><th>规则</th><th>级别</th><th>文件</th><th>行号</th><th>描述</th><th>建议</th></tr></thead>
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
      <p v-else>无审计记录</p>
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