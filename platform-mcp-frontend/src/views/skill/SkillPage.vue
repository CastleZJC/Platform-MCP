<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { Skill } from "@/types"

const loading = ref(false)
const skills = ref<Skill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")
const statusFilter = ref("")

const dialogVisible = ref(false)
const reviewVisible = ref(false)
const form = ref({ skill_code: "", skill_name: "", description: "" })
const reviewTarget = ref<Skill | null>(null)
const reviewComment = ref("")

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

async function handleCreate() {
  await request.post("/skills", form.value)
  ElMessage.success("创建成功")
  dialogVisible.value = false
  form.value = { skill_code: "", skill_name: "", description: "" }
  fetchSkills()
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
          <button class="btn btn-primary" disabled title="二期功能" style="opacity:.5;cursor:not-allowed">+ 新增 Skill</button>
        </div>
      </div>
      <table class="data-table">
        <thead><tr>
          <th>Skill 编码</th><th>Skill 名称</th><th>状态</th><th>Tool 数量</th><th>注册方式</th><th>描述</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in skills" :key="row.id">
            <td class="text-mono">{{ row.skill_code }}</td>
            <td>{{ row.skill_name }}</td>
            <td><span class="status-dot" :class="row.status === 'ENABLED' ? 'active' : row.status === 'PENDING_REVIEW' ? 'pending' : 'inactive'">{{ statusLabel(row.status) }}</span></td>
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

    <el-dialog v-model="dialogVisible" title="新增 Skill" width="500">
      <el-form label-width="100px">
        <el-form-item label="Skill 编码"><el-input v-model="form.skill_code" /></el-form-item>
        <el-form-item label="Skill 名称"><el-input v-model="form.skill_name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="handleCreate">提交</el-button></template>
    </el-dialog>

    <el-dialog v-model="reviewVisible" title="Skill 审核" width="500">
      <div v-if="reviewTarget" class="review-info">
        <p><b>Skill 编码:</b> {{ reviewTarget.skill_code }}</p>
        <p><b>Skill 名称:</b> {{ reviewTarget.skill_name }}</p>
        <p><b>提交人:</b> {{ reviewTarget.submitted_by }}</p>
      </div>
      <el-input v-model="reviewComment" type="textarea" :rows="3" placeholder="审核意见" style="margin-top: 12px" />
      <template #footer>
        <el-button type="danger" @click="submitReview('reject')">拒绝</el-button>
        <el-button type="success" @click="submitReview('approve')">通过</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.review-info p { margin: 4px 0; }
</style>
