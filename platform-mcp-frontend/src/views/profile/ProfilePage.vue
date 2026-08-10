<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import request from "@/utils/request"
import { maskApiKey } from "@/utils/format"
import { useUserStore } from "@/stores/user"
import { copyToClipboard } from "@/utils/clipboard"

const userStore = useUserStore()
const nickname = ref("")
const email = ref("")

const oldPassword = ref("")
const newPassword = ref("")
const confirmPassword = ref("")

// API Key state
const apiKeyId = ref(0)
const apiKeyMasked = ref("")
const apiKeyFull = ref("")
const keyVisible = ref(false)

async function fetchProfile() {
  const res = await request.get("/profile")
  nickname.value = res.data.nickname || ""
  email.value = res.data.email || ""
  await loadApiKey()
}

async function loadApiKey() {
  try {
    const res = await request.get("/api-keys")
    const keys = ((res.data as any[]) || [])
    const active = keys.find((k: any) => k.status === 1)
    if (active) { apiKeyId.value = active.id; apiKeyMasked.value = maskApiKey(active.key_prefix) }
  } catch { /* 尚无 Key */ }
}

async function handleSaveProfile() {
  await request.put("/profile", { nickname: nickname.value, email: email.value })
  ElMessage.success("保存成功")
}

async function handleChangePassword() {
  if (newPassword.value !== confirmPassword.value) {
    return ElMessage.error("两次密码不一致")
  }
  await request.post("/profile/change-password", { old_password: oldPassword.value, new_password: newPassword.value })
  ElMessage.success("密码修改成功"); oldPassword.value = ""; newPassword.value = ""; confirmPassword.value = ""
}

async function toggleApiKey() {
  if (keyVisible.value) {
    keyVisible.value = false
    apiKeyFull.value = ""
    return
  }
  const uid = (userStore.user as any)?.id
  if (!uid) { ElMessage.error("未获取到用户信息"); return }
  try {
    const res = await request.get(`/api-keys/full/${uid}`)
    const d = res.data as any
    if (d?.key) {
      apiKeyFull.value = d.key
      apiKeyMasked.value = maskApiKey(d.key_prefix || d.key)
      keyVisible.value = true
    } else {
      ElMessage.warning("当前 Key 在新机制前生成，无法 reveal 明文，请点击重置生成新 Key")
    }
  } catch { /* handled by interceptor */ }
}

async function copyApiKey() {
  const uid = (userStore.user as any)?.id
  if (!uid) { ElMessage.error("未获取到用户信息"); return }
  let key = apiKeyFull.value || ""
  if (!key) {
    try {
      const res = await request.get(`/api-keys/full/${uid}`)
      const d = res.data as any
      if (d?.key) key = d.key
    } catch { /* handled by interceptor */ }
  }
  if (key) {
    const ok = await copyToClipboard(key)
    ElMessage[ok ? "success" : "error"](ok ? "已复制明文 Key" : "复制失败，请手动选中复制")
  } else {
    ElMessage.warning("当前无活跃 Key，请先点击重置生成")
  }
}

async function resetApiKey() {
  try { await ElMessageBox.confirm("重置后旧 Key 立即失效，确定继续？", "确认", { type: "warning" }) } catch { return }
  const res = await request.post(`/api-keys/${apiKeyId.value}/regenerate`); const d = res.data as any
  apiKeyId.value = d.id; apiKeyMasked.value = maskApiKey(d.key_prefix); apiKeyFull.value = d.key; keyVisible.value = true
  ElMessage.success("API Key 已重置，请复制保存")
}

onMounted(fetchProfile)
</script>

<template>
  <div class="profile-page">
    <div class="page-header">
      <h2>个人设置</h2>
      <p>管理您的个人信息与账户安全</p>
    </div>
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><b>基本信息</b></template>
      <el-form label-width="100px" style="max-width: 400px">
        <el-form-item label="显示名称"><el-input v-model="nickname" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="email" /></el-form-item>
        <el-form-item><el-button type="primary" @click="handleSaveProfile">保存</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><b>API Key</b></template>
      <p style="font-size:13px;color:#64748b;margin-bottom:12px">
        用于 MCP 接入认证。在 <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">~/.claude.json</code> 中配置 <code>headers.PLATFORM_MCP_API_KEY</code>
      </p>
      <div style="display:flex;align-items:center;gap:8px;padding:10px 12px;background:#f8fafc;border-radius:6px">
        <code style="font-size:13px;font-family:monospace;flex:1">
          {{ keyVisible && apiKeyFull ? apiKeyFull : apiKeyMasked || '暂无 Key，点击 👁 生成' }}
        </code>
        <el-button size="small" text @click="toggleApiKey" :title="keyVisible?'掩码':'明文'">&#128065;</el-button>
        <el-button size="small" text @click="copyApiKey" title="复制">&#128203;</el-button>
        <el-button size="small" text @click="resetApiKey" title="重置" :disabled="!apiKeyId">&#8635;</el-button>
      </div>
    </el-card>
    <el-card shadow="never">
      <template #header><b>修改密码</b></template>
      <el-form label-width="100px" style="max-width: 400px">
        <el-form-item label="当前密码"><el-input v-model="oldPassword" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="newPassword" type="password" show-password /></el-form-item>
        <el-form-item label="确认密码"><el-input v-model="confirmPassword" type="password" show-password /></el-form-item>
        <el-form-item><el-button type="primary" @click="handleChangePassword">修改密码</el-button></el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.profile-page { max-width: 700px; }
</style>
