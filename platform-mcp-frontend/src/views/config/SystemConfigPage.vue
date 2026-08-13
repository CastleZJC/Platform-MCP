<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import type { SystemConfig } from "@/types"

const loading = ref(false)
const configs = ref<SystemConfig[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")

const dialogVisible = ref(false)
const editMode = ref(false)
const editId = ref<number | null>(null)
const form = ref<{ config_key: string; config_value: string; config_type: string; description: string }>({
  config_key: "",
  config_value: "",
  config_type: "string",
  description: "",
})

async function fetchConfigs() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    const res = await request.get("/system-config", { params })
    configs.value = res.data.items || []
    total.value = res.data.total || 0
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editMode.value = false
  editId.value = null
  form.value = { config_key: "", config_value: "", config_type: "string", description: "" }
  dialogVisible.value = true
}

function openEdit(c: SystemConfig) {
  editMode.value = true
  editId.value = c.id
  form.value = {
    config_key: c.config_key,
    config_value: c.config_value,
    config_type: c.config_type,
    description: c.description || "",
  }
  dialogVisible.value = true
}

async function submitForm() {
  if (!form.value.config_key) {
    ElMessage.warning("请填写配置键")
    return
  }
  if (editMode.value && editId.value !== null) {
    await request.put(`/system-config/${editId.value}`, {
      config_value: form.value.config_value,
      description: form.value.description,
    })
    ElMessage.success("更新成功")
  } else {
    await request.post("/system-config", form.value)
    ElMessage.success("创建成功")
  }
  dialogVisible.value = false
  fetchConfigs()
}

async function deleteConfig(c: SystemConfig) {
  await request.delete(`/system-config/${c.id}`)
  ElMessage.success("删除成功")
  fetchConfigs()
}

function typeLabel(t: string) {
  const map: Record<string, string> = { string: "字符串", int: "整数", bool: "布尔", json: "JSON" }
  return map[t] || t
}

onMounted(fetchConfigs)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>系统配置</h2>
      <p>管理 pmcp_system_config 表（CRUD），支持字符串/整数/布尔/JSON 类型</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" placeholder="搜索配置键" @keyup.enter="fetchConfigs">
          <button class="btn" @click="fetchConfigs">查询</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openCreate">+ 新增配置</button>
        </div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>配置键</th>
            <th>配置值</th>
            <th>类型</th>
            <th>描述</th>
            <th>状态</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in configs" :key="row.id">
            <td class="text-mono">{{ row.config_key }}</td>
            <td class="config-value">{{ row.config_value }}</td>
            <td><span class="tag tag-info">{{ typeLabel(row.config_type) }}</span></td>
            <td>{{ row.description || "-" }}</td>
            <td>
              <span class="status-dot" :class="row.status === 1 ? 'active' : 'inactive'">
                {{ row.status === 1 ? "启用" : "停用" }}
              </span>
            </td>
            <td>{{ row.created_at }}</td>
            <td class="actions">
              <button class="btn btn-sm" @click="openEdit(row)">编辑</button>
              <button class="btn btn-sm btn-danger" @click="deleteConfig(row)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchConfigs" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editMode ? '编辑配置' : '新增配置'" width="560">
      <el-form label-width="90px">
        <el-form-item label="配置键">
          <el-input v-model="form.config_key" :disabled="editMode" placeholder="例: app.max_upload_size_mb" />
        </el-form-item>
        <el-form-item label="配置值">
          <el-input v-model="form.config_value" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <select class="form-select" v-model="form.config_type" :disabled="editMode">
            <option value="string">字符串</option>
            <option value="int">整数</option>
            <option value="bool">布尔</option>
            <option value="json">JSON</option>
          </select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.config-value {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
  font-size: 12px;
}
</style>