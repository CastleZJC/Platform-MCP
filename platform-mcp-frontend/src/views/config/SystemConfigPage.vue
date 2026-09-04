<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"

const { t } = useI18n()

// 注册表行：已知键统一展示（配置项=功能简述 label；值列恒显当前生效值）。
// 以 config_key 为自然键：PUT by key 为 upsert，DELETE by key 重置回默认值，无行 id 概念。
interface RegistryItem {
  key: string
  label: string
  hint: string | null
  value_type: string
  effect: string
  effect_label: string
  sensitive: boolean
  description: string
  configured: boolean
  current_value: unknown
}

const loading = ref(false)
const registryItems = ref<RegistryItem[]>([])
const search = ref("")

const dialogVisible = ref(false)
const target = ref<RegistryItem | null>(null)
const form = ref<{ config_value: string }>({ config_value: "" })

const editingSensitive = computed(() => !!target.value?.sensitive)

async function fetchAll() {
  loading.value = true
  try {
    const regRes = await request.get("/system-config/registry")
    registryItems.value = (regRes.data as RegistryItem[]) || []
  } finally {
    loading.value = false
  }
}

const rows = computed<RegistryItem[]>(() => {
  if (!search.value) return registryItems.value
  const s = search.value.toLowerCase()
  return registryItems.value.filter(
    (r) =>
      r.label.toLowerCase().includes(s) ||
      r.description.toLowerCase().includes(s) ||
      r.key.toLowerCase().includes(s)
  )
})

// 值列展示：恒显当前生效值（未落库键即注册表默认生效值，无需区分展示）
function valueText(row: RegistryItem): string {
  return row.current_value === null || row.current_value === undefined ? "" : String(row.current_value)
}

function openEdit(row: RegistryItem) {
  target.value = row
  // 凭证键不回显（后端返回掩码，回显会导致掩码被当作新值提交）
  form.value = { config_value: row.sensitive ? "" : row.configured ? valueText(row) : "" }
  dialogVisible.value = true
}

async function submitForm() {
  if (!target.value) return
  // 按键 upsert：已有行更新 / 未落库键创建行（后端未知键 16004 拒绝）；
  // 凭证键留空 = 不修改值（后端 config_value=null 保留原值）
  const configValue = editingSensitive.value && form.value.config_value === "" ? null : form.value.config_value
  await request.put(`/system-config/${encodeURIComponent(target.value.key)}`, {
    config_value: configValue,
  })
  ElMessage.success(t("config.updated"))
  dialogVisible.value = false
  fetchAll()
}

// 重置 = 删除配置行，回退注册表默认值（仅已落库行可重置）
async function resetConfig(row: RegistryItem) {
  if (!row.configured) return
  await request.delete(`/system-config/${encodeURIComponent(row.key)}`)
  ElMessage.success(t("config.deleted"))
  fetchAll()
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
      </div>
      <table class="data-table" v-loading="loading">
        <thead>
          <tr>
            <th>{{ t("config.colItem") }}</th>
            <th>{{ t("config.colValue") }}</th>
            <th>{{ t("config.colEffect") }}</th>
            <th>{{ t("config.colDescription") }}</th>
            <th>{{ t("config.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key">
            <td>
              {{ row.label }}
            </td>
            <td class="config-value">
              <span>{{ valueText(row) }}</span>
            </td>
            <td>{{ row.effect_label || "—" }}</td>
            <td>{{ row.description || "-" }}</td>
            <td class="actions">
              <button class="btn btn-sm" @click="openEdit(row)">{{ t("common.edit") }}</button>
              <button v-if="row.configured" class="btn btn-sm btn-danger" @click="resetConfig(row)">{{ t("config.reset") }}</button>
            </td>
          </tr>
          <tr v-if="!loading && rows.length === 0"><td colspan="5" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">—</td></tr>
        </tbody>
      </table>
    </div>

    <el-dialog v-model="dialogVisible" :title="t('config.dialogEdit')" width="560">
      <el-form label-width="90px">
        <el-form-item :label="t('config.colItem')">
          <span>{{ target?.label }}</span>
        </el-form-item>
        <el-form-item v-if="target?.hint" :label="t('config.hintLabel')">
          <span class="hint-text">{{ target.hint }}</span>
        </el-form-item>
        <el-form-item :label="t('config.labelValue')">
          <el-input v-model="form.config_value" type="textarea" :rows="3" :placeholder="editingSensitive && target && !target.configured ? valueText(target) : ''" />
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
.hint-text { color: var(--color-text-secondary, #666); font-size: 13px; }
</style>
