<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import { copyToClipboard } from "@/utils/clipboard"

const { t } = useI18n()

interface CryptoHistoryItem {
  id: number
  operator: string | null
  operation_type: string | null
  datasource_code: string | null
  algorithm: string | null
  result_status: string | null
  error_message: string | null
  inserted_at: string | null
}

const plaintext = ref("")
const ciphertext = ref("")
const verifyText = ref("")
const verifyResult = ref("")
const verifyOk = ref(false)
const encryptLoading = ref(false)
const verifyLoading = ref(false)

const historyLoading = ref(false)
const historyData = ref<CryptoHistoryItem[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = ref(10)

async function handleEncrypt() {
  if (!plaintext.value) return ElMessage.warning(t("crypto.plaintextRequired"))
  encryptLoading.value = true
  try {
    const res = await request.post("/crypto/encrypt", { plaintext: plaintext.value })
    ciphertext.value = res.data.ciphertext
    ElMessage.success(t("crypto.encryptSuccess"))
    await fetchHistory()
  } finally { encryptLoading.value = false }
}

async function handleVerify() {
  if (!verifyText.value) return ElMessage.warning(t("crypto.ciphertextRequired"))
  verifyLoading.value = true
  try {
    const res = await request.post("/crypto/verify", { ciphertext: verifyText.value })
    verifyOk.value = !!res.data.success
    verifyResult.value = res.data.success ? t("crypto.verifyPassed") : t("crypto.verifyFailed", { error: res.data.error })
    await fetchHistory()
  } finally { verifyLoading.value = false }
}

async function copyText(text: string) {
  const ok = await copyToClipboard(text)
  ElMessage[ok ? "success" : "error"](ok ? t("common.copied") : t("common.copyFailed"))
}

async function fetchHistory() {
  historyLoading.value = true
  try {
    const res = await request.get("/crypto/history", { params: { page: historyPage.value, page_size: historyPageSize.value } })
    historyData.value = res.data.items
    historyTotal.value = res.data.total
  } finally { historyLoading.value = false }
}

onMounted(fetchHistory)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("crypto.title") }}</h2>
      <p>{{ t("crypto.subtitle") }}</p>
    </div>
    <div class="crypto-panels">
      <div class="crypto-panel">
        <h3>{{ t("crypto.encryptTitle") }}</h3>
        <p class="panel-desc">{{ t("crypto.encryptDesc") }}</p>
        <label style="display:block;font-size:13px;font-weight:500;color:var(--color-text);margin-bottom:6px">{{ t("crypto.plaintextLabel") }}</label>
        <textarea v-model="plaintext" :placeholder="t('crypto.plaintextPlaceholder')"></textarea>
        <div class="btn-row">
          <button class="btn btn-primary" :disabled="encryptLoading" @click="handleEncrypt">{{ encryptLoading ? t("crypto.encrypting") : t("crypto.encryptSubmit") }}</button>
          <button class="btn" @click="plaintext = ''; ciphertext = ''">{{ t("crypto.clear") }}</button>
        </div>
        <div class="result-label">{{ t("crypto.resultLabel") }}</div>
        <div class="result-box">
          <span v-if="!ciphertext" style="color:var(--color-text-muted)">{{ t("crypto.resultEmpty") }}</span>
          <span v-else style="word-break:break-all">{{ ciphertext }}</span>
        </div>
        <div class="btn-row" v-if="ciphertext">
          <button class="btn btn-sm" @click="copyText(ciphertext)">{{ t("crypto.copyCiphertext") }}</button>
        </div>
      </div>
      <div class="crypto-panel">
        <h3>{{ t("crypto.verifyTitle") }}</h3>
        <p class="panel-desc">{{ t("crypto.verifyDesc") }}</p>
        <label style="display:block;font-size:13px;font-weight:500;color:var(--color-text);margin-bottom:6px">{{ t("crypto.ciphertextLabel") }}</label>
        <textarea v-model="verifyText" :placeholder="t('crypto.ciphertextPlaceholder')"></textarea>
        <div class="btn-row">
          <button class="btn btn-warning" :disabled="verifyLoading" @click="handleVerify">{{ verifyLoading ? t("crypto.verifying") : t("crypto.verifySubmit") }}</button>
          <button class="btn" @click="verifyText = ''; verifyResult = ''; verifyOk = false">{{ t("crypto.clear") }}</button>
        </div>
        <div class="result-label">{{ t("crypto.verifyResultLabel") }}</div>
        <div class="result-box">
          <span v-if="!verifyResult" style="color:var(--color-text-muted)">{{ t("crypto.verifyResultEmpty") }}</span>
          <span v-else :style="{color: verifyOk ? 'var(--color-success)' : 'var(--color-danger)'}">{{ verifyResult }}</span>
        </div>
      </div>
    </div>

    <div class="card mt-16">
      <div class="card-header"><h3>{{ t("crypto.historyTitle") }}</h3></div>
      <table class="data-table" v-loading="historyLoading">
        <thead><tr>
          <th>{{ t("crypto.colTime") }}</th><th>{{ t("crypto.colOperator") }}</th><th>{{ t("crypto.colType") }}</th><th>{{ t("crypto.colDatasource") }}</th><th>{{ t("crypto.colAlgorithm") }}</th><th>{{ t("crypto.colResult") }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="(row, i) in historyData" :key="i">
            <td class="text-mono">{{ row.inserted_at?.replace('T', ' ').slice(0, 19) }}</td>
            <td>{{ row.operator || '—' }}</td>
            <td><span class="tag" :class="row.operation_type === 'encrypt' ? 'tag-primary' : 'tag-warning'">{{ row.operation_type === 'encrypt' ? t("crypto.opEncrypt") : t("crypto.opVerify") }}</span></td>
            <td class="text-mono">{{ row.datasource_code || '—' }}</td>
            <td class="text-mono">{{ row.algorithm || '—' }}</td>
            <td><span class="tag" :class="row.result_status === 'success' ? 'tag-success' : 'tag-danger'">{{ row.result_status === 'success' ? t("crypto.resultSuccess") : t("crypto.resultFailed") }}</span></td>
          </tr>
          <tr v-if="!historyLoading && historyData.length === 0"><td colspan="6" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">{{ t("crypto.historyEmpty") }}</td></tr>
        </tbody>
      </table>
      <Pagination v-model:page="historyPage" v-model:pageSize="historyPageSize" :total="historyTotal" @change="fetchHistory" />
    </div>
  </div>
</template>

<style scoped>
</style>
