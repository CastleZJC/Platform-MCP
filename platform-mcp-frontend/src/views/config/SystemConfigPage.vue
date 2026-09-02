<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import type { SystemConfig } from "@/types"

const { t } = useI18n()

// 注册表行（已知键）与自定义键统一为同一展示模型
interface RegistryItem {
  key: string
  id: number | null
  value_type: string
  effect: string
  effect_label: string
  sensitive: boolean
  description: string
  configured: boolean
  current_value: unknown
  custom?: boolean
}

const loading = ref(false)
const registryItems = ref<RegistryItem[]>([])
const customItems = ref<SystemConfig[]>([])
const search = ref("")

const dialogVisible = ref(false)
const target = ref<RegistryItem | null>(null) // null = 新增自定义键
const confirmSensitive = ref(false)
const form = ref<{ config_key: string; config_value: string; config_type: string; description: string }>({
  config_key: "",
  config_value: "",
  config_type: "string",
  description: "",
})

const editingId = computed(() => target.value?.id ?? null)
const editingSensitive = computed(() => !!target.value?.sensitive)

async function fetchAll() {
  loading.value = true
  try {
    const [regRes, listRes] = await Promise.all([
      request.get("/system-config/registry"),
      request.get("/system-config", { params: { page: 1, page_size: 200 } }),
    ])
    registryItems.value = (regRes.data as RegistryItem[]) || []
    const knownKeys = new Set(registryItems.value.map((r) => r.key))
    customItems.value = ((listRes.data.items || []) as SystemConfig[]).filter((c) => !knownKeys.has(c.config_key))
  } finally {
    loading.value = false
  }
}

const rows = computed<RegistryItem[]>(() => {
  const custom: RegistryItem[] = customItems.value.map((c) => ({
    key: c.config_key,
    id: c.id,
    value_type: c.config_type,
    effect: "",
    effect_label: "—",
    sensitive: false,
    description: c.description || "",
    configured: true,
    current_value: c.config_value,
    custom: true,
  }))
  const all = [...registryItems.value, ...custom]
  if (!search.value) return all
  const s = search.value.toLowerCase()
  return all.filter((r) => r.key.toLowerCase().includes(s))
})

function openCreate() {
  target.value = null
  confirmSensitive.value = false
  form.value = { config_key: "", config_value: "", config_type: "string", description: "" }
  dialogVisible.value = true
}

function openEdit(row: RegistryItem) {
  target.value = row
  confirmSensitive.value = false
  // 敏感键不回显（后端返回掩码，回显会导致掩码被当作新值提交）
  const prefill = row.sensitive ? "" : row.configured ? String(row.current_value ?? "") : ""
  form.value = {
    config_key: row.key,
    config_value: prefill,
    config_type: row.value_type || "string",
    description: row.description || "",
  }
  dialogVisible.value = true
}

async function submitForm() {
  if (!target.value && !form.value.config_key) {
    ElMessage.warning(t("config.keyRequired"))
    return
  }
  if (editingSensitive.value && !confirmSensitive.value) {
    ElMessage.warning(t("config.sensitiveConfirm"))
    return
  }
  if (editingId.value !== null) {
    const payload: Record<string, unknown> = {
      description: form.value.description,
      confirm_sensitive: confirmSensitive.value,
    }
    // 敏感键留空 = 不修改值（后端 config_value=None 保留原值）
    payload.config_value = editingSensitive.value && form.value.config_value === "" ? null : form.value.config_value
    await request.put(`/system-config/${editingId.value}`, payload)
    ElMessage.success(t("config.updated"))
  } else {
    await request.post("/system-config", { ...form.value, confirm_sensitive: confirmSensitive.value })
    ElMessage.success(t("config.created"))
  }
  dialogVisible.value = false
  fetchAll()
}

async function deleteConfig(row: RegistryItem) {
  if (row.id === null) return
  await request.delete(`/system-config/${row.id}`)
  ElMessage.success(t("config.deleted"))
  fetchAll()
}

function typeLabel(v: string) {
  if (v === "string") return t("config.typeString")
  if (v === "int") return t("config.typeInt")
  if (v === "bool") return t("config.typeBool")
  if (v === "json") return t("config.typeJson")
  return v
}

onMounted(fetchAll)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("config.title") }}</h2>
      <p>{{ t("config.subtitle") }}</p>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="toolbar-left">
          <input type="text" class="search-input" v-model="search" :placeholder="t('config.searchPlaceholder')">
          <button class="btn" @click="fetchAll">{{ t("common.query") }}</button>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-primary" @click="openCreate">{{ t("config.add") }}</button>
        </div>
      </div>
      <table class="data-table" v-loading="loading">
        <thead>
          <tr>
            <th>{{ t("config.colKey") }}</th>
            <th>{{ t("config.colValue") }}</th>
            <th>{{ t("config.colType") }}</th>
            <th>{{ t("config.colEffect") }}</th>
            <th>{{ t("config.colDescription") }}</th>
            <th>{{ t("config.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key">
            <td class="text-mono">
              {{ row.key }}
              <el-tag v-if="row.sensitive" type="danger" size="small" style="margin-left:6px">{{ t("config.colSensitive") }}</el-tag>
            </td>
            <td class="config-value">
              <span v-if="row.configured">{{ row.current_value }}</span>
              <span v-else style="color:var(--color-text-muted)">{{ t("config.notConfigured") }}</span>
            </td>
            <td><span class="tag tag-info">{{ typeLabel(row.value_type) }}</span></td>
            <td>{{ row.effect_label || "—" }}</td>
            <td>{{ row.description || "-" }}</td>
            <td class="actions">
              <button class="btn btn-sm" @click="openEdit(row)">{{ t("common.edit") }}</button>
              <button v-if="row.id !== null" class="btn btn-sm btn-danger" @click="deleteConfig(row)">{{ t("common.delete") }}</button>
            </td>
          </tr>
          <tr v-if="!loading && rows.length === 0"><td colspan="6" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">—</td></tr>
        </tbody>
      </table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId !== null ? t('config.dialogEdit') : t('config.dialogCreate')" width="560">
      <el-form label-width="90px">
        <el-form-item :label="t('config.labelKey')">
          <el-input v-model="form.config_key" :disabled="target !== null" placeholder="例: app.max_upload_size_mb" />
        </el-form-item>
        <el-form-item :label="t('config.labelValue')">
          <el-input v-model="form.config_value" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('config.labelType')">
          <select class="form-select" v-model="form.config_type" :disabled="target !== null">
            <option value="string">{{ t("config.typeString") }}</option>
            <option value="int">{{ t("config.typeInt") }}</option>
            <option value="bool">{{ t("config.typeBool") }}</option>
            <option value="json">{{ t("config.typeJson") }}</option>
          </select>
        </el-form-item>
        <el-form-item :label="t('config.labelDescription')">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item v-if="editingSensitive" label="">
          <p style="color:var(--color-text-secondary);font-size:12px;margin:0 0 6px">{{ t("config.sensitiveConfirm") }}</p>
          <el-checkbox v-model="confirmSensitive">{{ t("config.sensitiveLabel") }}</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submitForm">{{ t("common.submit") }}</el-button>
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
