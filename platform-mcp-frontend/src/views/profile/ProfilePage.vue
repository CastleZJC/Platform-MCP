<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage, ElMessageBox } from "element-plus"
import request from "@/utils/request"
import { maskApiKey } from "@/utils/format"
import { useUserStore } from "@/stores/user"
import { copyToClipboard } from "@/utils/clipboard"
import { setLocale, currentLocale, LOCALE_OPTIONS } from "@/i18n"
import type { AppLocale } from "@/i18n"

const { t } = useI18n()
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

// V3.0: 界面语言即时生效（前端 i18n + 后端生成内容均实时读 pmcp_user.locale，无需重新登录；
// 系统配置 sys.default_locale 仅影响未设置个人偏好的用户/新用户）
const locale = computed<AppLocale>(() => currentLocale())
async function handleLanguageChange(v: AppLocale) {
  setLocale(v)
  try {
    await request.put("/profile", { locale: v })
    ElMessage.success(t("profile.languageSaved"))
  } catch { /* handled by interceptor */ }
}

// V3.0 分页统一：个人每页条数（保存即更新 store，全部列表页即时生效，无需重新登录）
const PAGE_SIZE_OPTIONS = [5, 10, 20, 50, 75, 100]
const pageSizePref = ref(userStore.pageSize)
async function handlePageSizeChange(v: number) {
  try {
    await request.put("/profile", { page_size: v })
    userStore.setPageSize(v)
    ElMessage.success(t("profile.pageSizeSaved"))
  } catch { /* handled by interceptor */ }
}

async function fetchProfile() {
  const res = await request.get("/profile")
  nickname.value = res.data.nickname || ""
  email.value = res.data.email || ""
  pageSizePref.value = Number(res.data.page_size) || userStore.pageSize
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
  ElMessage.success(t("common.saveSuccess"))
}

async function handleChangePassword() {
  if (newPassword.value !== confirmPassword.value) {
    return ElMessage.error(t("profile.pwdMismatch"))
  }
  await request.post("/profile/change-password", { old_password: oldPassword.value, new_password: newPassword.value })
  ElMessage.success(t("profile.pwdSuccess")); oldPassword.value = ""; newPassword.value = ""; confirmPassword.value = ""
}

async function toggleApiKey() {
  if (keyVisible.value) {
    keyVisible.value = false
    apiKeyFull.value = ""
    return
  }
  const uid = (userStore.user as any)?.id
  if (!uid) { ElMessage.error(t("profile.noUserInfo")); return }
  try {
    const res = await request.get(`/api-keys/full/${uid}`)
    const d = res.data as any
    if (d?.key) {
      apiKeyFull.value = d.key
      apiKeyMasked.value = maskApiKey(d.key_prefix || d.key)
      keyVisible.value = true
    } else {
      ElMessage.warning(t("profile.revealLegacyWarning"))
    }
  } catch { /* handled by interceptor */ }
}

async function copyApiKey() {
  const uid = (userStore.user as any)?.id
  if (!uid) { ElMessage.error(t("profile.noUserInfo")); return }
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
    ElMessage[ok ? "success" : "error"](ok ? t("common.copiedKey") : t("common.copyFailed"))
  } else {
    ElMessage.warning(t("profile.noActiveKey"))
  }
}

async function resetApiKey() {
  try { await ElMessageBox.confirm(t("profile.resetConfirm"), t("common.confirmTitle"), { type: "warning" }) } catch { return }
  const res = await request.post(`/api-keys/${apiKeyId.value}/regenerate`); const d = res.data as any
  apiKeyId.value = d.id; apiKeyMasked.value = maskApiKey(d.key_prefix); apiKeyFull.value = d.key; keyVisible.value = true
  ElMessage.success(t("profile.resetSuccess"))
}

onMounted(fetchProfile)
</script>

<template>
  <div class="profile-page">
    <div class="page-header">
      <h2>{{ t("profile.title") }}</h2>
      <p>{{ t("profile.subtitle") }}</p>
    </div>
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><b>{{ t("profile.basicInfo") }}</b></template>
      <el-form label-width="100px" style="max-width: 400px">
        <el-form-item :label="t('profile.nickname')"><el-input v-model="nickname" /></el-form-item>
        <el-form-item :label="t('profile.email')"><el-input v-model="email" /></el-form-item>
        <el-form-item><button class="btn btn-primary" @click="handleSaveProfile">{{ t("common.save") }}</button></el-form-item>
      </el-form>
    </el-card>
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><b>{{ t("profile.language") }}</b></template>
      <div style="display:flex;align-items:center;gap:12px">
        <el-select :model-value="locale" style="width: 180px" @change="handleLanguageChange">
          <el-option v-for="loc in LOCALE_OPTIONS" :key="loc.value" :label="loc.nativeName" :value="loc.value" />
        </el-select>
      </div>
      <p style="font-size:13px;color:#64748b;margin-top:12px">{{ t("profile.languageHint") }}</p>
    </el-card>
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><b>{{ t("profile.pageSizeTitle") }}</b></template>
      <div style="display:flex;align-items:center;gap:12px">
        <el-select :model-value="pageSizePref" style="width: 180px" @change="handlePageSizeChange">
          <el-option v-for="s in PAGE_SIZE_OPTIONS" :key="s" :label="String(s)" :value="s" />
        </el-select>
      </div>
      <p style="font-size:13px;color:#64748b;margin-top:12px">{{ t("profile.pageSizeHint") }}</p>
    </el-card>
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><b>{{ t("profile.apiKeyTitle") }}</b></template>
      <p style="font-size:13px;color:#64748b;margin-bottom:12px">
        {{ t("profile.apiKeyDescPre") }} <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">~/.claude.json</code> {{ t("profile.apiKeyDescPost") }} <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">headers.PLATFORM_MCP_API_KEY</code>
      </p>
      <div style="display:flex;align-items:center;gap:8px;padding:10px 12px;background:#f8fafc;border-radius:6px">
        <code style="font-size:13px;font-family:monospace;flex:1">
          {{ keyVisible && apiKeyFull ? apiKeyFull : apiKeyMasked || t("profile.keyEmpty") }}
        </code>
        <span class="key-action" :title="keyVisible ? t('profile.titleMask') : t('profile.titleReveal')" @click="toggleApiKey">&#128065;</span>
        <span class="key-action" :title="t('profile.titleCopy')" @click="copyApiKey">&#128203;</span>
        <span class="key-action" :class="{ 'is-disabled': !apiKeyId }" :title="t('profile.titleReset')" @click="resetApiKey">&#8635;</span>
      </div>
    </el-card>
    <el-card shadow="never">
      <template #header><b>{{ t("profile.changePassword") }}</b></template>
      <el-form label-width="100px" style="max-width: 400px">
        <el-form-item :label="t('profile.currentPassword')"><el-input v-model="oldPassword" type="password" show-password /></el-form-item>
        <el-form-item :label="t('profile.newPassword')"><el-input v-model="newPassword" type="password" show-password /></el-form-item>
        <el-form-item :label="t('profile.confirmPassword')"><el-input v-model="confirmPassword" type="password" show-password /></el-form-item>
        <el-form-item><button class="btn btn-primary" @click="handleChangePassword">{{ t("profile.submitPassword") }}</button></el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.profile-page { max-width: 700px; }
</style>
