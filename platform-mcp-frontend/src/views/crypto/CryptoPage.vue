<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import { copyToClipboard } from "@/utils/clipboard"

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
const encryptLoading = ref(false)
const verifyLoading = ref(false)

const historyLoading = ref(false)
const historyData = ref<CryptoHistoryItem[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = ref(10)

async function handleEncrypt() {
  if (!plaintext.value) return ElMessage.warning("请输入明文")
  encryptLoading.value = true
  try {
    const res = await request.post("/crypto/encrypt", { plaintext: plaintext.value })
    ciphertext.value = res.data.ciphertext
    ElMessage.success("加密成功")
    await fetchHistory()
  } finally { encryptLoading.value = false }
}

async function handleVerify() {
  if (!verifyText.value) return ElMessage.warning("请输入密文")
  verifyLoading.value = true
  try {
    const res = await request.post("/crypto/verify", { ciphertext: verifyText.value })
    verifyResult.value = res.data.success ? "验证通过" : `验证失败: ${res.data.error}`
    await fetchHistory()
  } finally { verifyLoading.value = false }
}

async function copyText(text: string) {
  const ok = await copyToClipboard(text)
  ElMessage[ok ? "success" : "error"](ok ? "已复制" : "复制失败，请手动选中复制")
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
      <h2>密码加密</h2>
      <p>使用 AES-256-GCM 对数据源密码进行加密操作，所有操作均记录审计日志</p>
    </div>
    <div class="crypto-panels">
      <div class="crypto-panel">
        <h3>密码加密</h3>
        <p class="panel-desc">输入明文密码，系统将使用 AES-256-GCM 加密并返回密文</p>
        <label style="display:block;font-size:13px;font-weight:500;color:var(--color-text);margin-bottom:6px">明文密码</label>
        <textarea v-model="plaintext" placeholder="请输入需要加密的明文密码"></textarea>
        <div class="btn-row">
          <button class="btn btn-primary" :disabled="encryptLoading" @click="handleEncrypt">{{ encryptLoading ? '加密中...' : '加密' }}</button>
          <button class="btn" @click="plaintext = ''; ciphertext = ''">清空</button>
        </div>
        <div class="result-label">加密结果（密文）：</div>
        <div class="result-box">
          <span v-if="!ciphertext" style="color:var(--color-text-muted)">点击"加密"按钮生成密文</span>
          <span v-else style="word-break:break-all">{{ ciphertext }}</span>
        </div>
        <div class="btn-row" v-if="ciphertext">
          <button class="btn btn-sm" @click="copyText(ciphertext)">复制密文</button>
        </div>
      </div>
      <div class="crypto-panel">
        <h3>密码验证</h3>
        <p class="panel-desc">输入密文进行解密验证，验证结果仅用于连接测试，不在页面展示完整明文</p>
        <label style="display:block;font-size:13px;font-weight:500;color:var(--color-text);margin-bottom:6px">密文</label>
        <textarea v-model="verifyText" placeholder="请输入需要验证的密文"></textarea>
        <div class="btn-row">
          <button class="btn btn-warning" :disabled="verifyLoading" @click="handleVerify">{{ verifyLoading ? '验证中...' : '验证' }}</button>
          <button class="btn" @click="verifyText = ''; verifyResult = ''">清空</button>
        </div>
        <div class="result-label">验证结果：</div>
        <div class="result-box">
          <span v-if="!verifyResult" style="color:var(--color-text-muted)">点击"验证"按钮验证密文</span>
          <span v-else :style="{color: verifyResult === '验证通过' ? 'var(--color-success)' : 'var(--color-danger)'}">{{ verifyResult }}</span>
        </div>
      </div>
    </div>

    <div class="card mt-16">
      <div class="card-header"><h3>近期加密操作记录</h3></div>
      <table class="data-table" v-loading="historyLoading">
        <thead><tr>
          <th>操作时间</th><th>操作人</th><th>操作类型</th><th>关联数据源</th><th>算法</th><th>结果</th>
        </tr></thead>
        <tbody>
          <tr v-for="(row, i) in historyData" :key="i">
            <td class="text-mono">{{ row.inserted_at?.replace('T', ' ').slice(0, 19) }}</td>
            <td>{{ row.operator || '—' }}</td>
            <td><span class="tag" :class="row.operation_type === 'encrypt' ? 'tag-primary' : 'tag-warning'">{{ row.operation_type === 'encrypt' ? '加密' : '验证' }}</span></td>
            <td class="text-mono">{{ row.datasource_code || '—' }}</td>
            <td class="text-mono">{{ row.algorithm || '—' }}</td>
            <td><span class="tag" :class="row.result_status === 'success' ? 'tag-success' : 'tag-danger'">{{ row.result_status === 'success' ? '成功' : '失败' }}</span></td>
          </tr>
          <tr v-if="!historyLoading && historyData.length === 0"><td colspan="6" style="text-align:center;color:var(--color-text-secondary);padding:32px 0">暂无加密操作记录</td></tr>
        </tbody>
      </table>
      <Pagination v-model:page="historyPage" v-model:pageSize="historyPageSize" :total="historyTotal" @change="fetchHistory" />
    </div>
  </div>
</template>

<style scoped>
</style>
