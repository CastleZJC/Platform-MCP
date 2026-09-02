<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import { copyToClipboard } from "@/utils/clipboard"

const { t } = useI18n()

interface ToolInfo { tool_name: string; display_name: string; description: string; risk_level: string }
interface SkillGroup {
  skill_code: string
  skill_name: string
  description: string | null
  register_method: string | null
  tool_count: number
  tools: ToolInfo[]
}

const devConfigJson = ref("")
const prodConfigJson = ref("")
const prodReplaceHints = ref<string[]>([])
const skills = ref<SkillGroup[]>([])
const usage = ref<{ title: string; user_says: string; behavior: string }[]>([])
const usageTips = ref<string[]>([])

async function fetchConfig() {
  const res = await request.get("/guide/config")
  const data = res.data as any
  devConfigJson.value = JSON.stringify(data.dev?.mcpServers, null, 2)
  prodConfigJson.value = JSON.stringify(data.prod?.mcpServers, null, 2)
  prodReplaceHints.value = data.prod?.replace_hints || []
}

async function fetchTools() {
  const res = await request.get("/guide/tools")
  skills.value = res.data as SkillGroup[]
}

async function fetchUsage() {
  const res = await request.get("/guide/usage")
  const data = res.data as any
  usage.value = data?.scenarios || []
  usageTips.value = data?.tips || []
}

async function copyDevConfig() {
  const ok = await copyToClipboard(devConfigJson.value)
  ElMessage[ok ? "success" : "error"](ok ? t("guide.copiedDev") : t("common.copyFailed"))
}

async function copyProdConfig() {
  const ok = await copyToClipboard(prodConfigJson.value)
  ElMessage[ok ? "success" : "error"](ok ? t("guide.copiedProd") : t("common.copyFailed"))
}

function registerMethodLabel(m: string | null) {
  if (!m) return "—"
  if (m === "decorator") return t("guide.registerDecorator")
  if (m === "form") return t("guide.registerForm")
  if (m === "upload") return t("guide.registerUpload")
  return m
}

function riskTagClass(level: string) {
  if (level === "CRITICAL" || level === "HIGH") return "tag-danger"
  if (level === "MEDIUM") return "tag-warning"
  return "tag-success"
}

const faqs = computed(() => [
  { q: t("guide.faq1q"), a: t("guide.faq1a") },
  { q: t("guide.faq2q"), a: t("guide.faq2a") },
  { q: t("guide.faq3q"), a: t("guide.faq3a") },
  { q: t("guide.faq4q"), a: t("guide.faq4a") },
  { q: t("guide.faq5q"), a: t("guide.faq5a") },
])

onMounted(() => { fetchConfig(); fetchTools(); fetchUsage() })
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("guide.title") }}</h2>
      <p>{{ t("guide.subtitle") }}</p>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
      <!-- prod: streamable-http -->
      <div class="card" style="border-left:3px solid var(--color-primary)">
        <div class="guide-section">
          <h3 style="display:flex;align-items:center;gap:8px"><span class="tag tag-success" style="font-size:12px">{{ t("guide.prodTag") }}</span> {{ t("guide.prodTitle") }}</h3>
          <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">{{ t("guide.prodDesc") }}</p>
          <ol class="guide-steps">
            <li>{{ t("guide.prodStep1") }}</li>
            <li>{{ t("guide.prodStep2") }}</li>
            <li>{{ t("guide.prodStep3") }}</li>
            <li>{{ t("guide.prodStep4") }}</li>
            <li>{{ t("guide.prodStep5") }}</li>
          </ol>
          <p style="font-size:13px;font-weight:500;color:var(--color-text);margin-top:16px;margin-bottom:8px">{{ t("guide.prodConfigTitle") }}</p>
          <div class="code-block">
            <button class="btn btn-sm" style="position:absolute;top:8px;right:8px;background:rgba(255,255,255,0.1);color:#fff;border-color:transparent" @click="copyProdConfig">{{ t("common.copy") }}</button>
            <pre>{{ prodConfigJson || '{}' }}</pre>
          </div>
          <div v-if="prodReplaceHints.length > 0" style="margin-top:12px;padding:8px 12px;background:var(--color-background);border-radius:4px;font-size:12px;color:var(--color-text-secondary)">
            <div style="font-weight:500;color:var(--color-text);margin-bottom:4px">{{ t("guide.prodReplaceTitle") }}</div>
            <ul style="margin:0;padding-left:20px">
              <li v-for="h in prodReplaceHints" :key="h" style="margin-bottom:2px;font-family:monospace">{{ h }}</li>
            </ul>
          </div>
        </div>
      </div>
      <!-- dev: stdio -->
      <div class="card" style="border-left:3px solid var(--color-warning)">
        <div class="guide-section">
          <h3 style="display:flex;align-items:center;gap:8px"><span class="tag tag-warning" style="font-size:12px">{{ t("guide.devTag") }}</span> {{ t("guide.devTitle") }}</h3>
          <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">{{ t("guide.devDesc") }}</p>
          <ol class="guide-steps">
            <li>{{ t("guide.devStep1") }}</li>
            <li>{{ t("guide.devStep2") }}</li>
            <li>{{ t("guide.devStep3") }}</li>
          </ol>
          <p style="font-size:13px;font-weight:500;color:var(--color-text);margin-top:16px;margin-bottom:8px">{{ t("guide.devConfigTitle") }}</p>
          <div class="code-block">
            <button class="btn btn-sm" style="position:absolute;top:8px;right:8px;background:rgba(255,255,255,0.1);color:#fff;border-color:transparent" @click="copyDevConfig">{{ t("common.copy") }}</button>
            <pre>{{ devConfigJson || '{}' }}</pre>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>{{ t("guide.usageTitle") }}</h3>
        <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">{{ t("guide.usageDesc") }}</p>
        <table class="data-table">
          <thead><tr><th style="width:160px">{{ t("guide.usageColScene") }}</th><th style="width:300px">{{ t("guide.usageColExample") }}</th><th>{{ t("guide.usageColBehavior") }}</th></tr></thead>
          <tbody>
            <tr v-for="s in usage" :key="s.title">
              <td>{{ s.title }}</td>
              <td class="text-mono">{{ s.user_says }}</td>
              <td>{{ s.behavior }}</td>
            </tr>
            <tr v-if="usage.length === 0"><td colspan="3" style="text-align:center;color:var(--color-text-secondary);padding:24px 0">{{ t("common.loading") }}</td></tr>
          </tbody>
        </table>
        <ul style="margin-top:16px;font-size:13px;color:var(--color-text-secondary);padding-left:20px">
          <li v-for="tip in usageTips" :key="tip" style="margin-bottom:4px">{{ tip }}</li>
        </ul>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>{{ t("guide.skillsTitle") }}</h3>
        <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">{{ t("guide.skillsDesc") }}</p>
        <table class="data-table">
          <thead><tr>
            <th>{{ t("guide.skillsColCode") }}</th><th>{{ t("guide.skillsColName") }}</th><th>{{ t("guide.skillsColRegister") }}</th><th>{{ t("guide.skillsColToolCount") }}</th><th>{{ t("guide.skillsColTools") }}</th><th>{{ t("guide.skillsColDescription") }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in skills" :key="s.skill_code">
              <td class="text-mono">{{ s.skill_code }}</td>
              <td>{{ s.skill_name }}</td>
              <td><span class="tag tag-primary">{{ registerMethodLabel(s.register_method) }}</span></td>
              <td>{{ s.tool_count }}</td>
              <td>
                <span v-for="tool in s.tools" :key="tool.tool_name" class="tag"
                  :class="riskTagClass(tool.risk_level)" :title="t('guide.toolTip', { name: tool.display_name, description: tool.description, risk: tool.risk_level })"
                  style="margin:2px;display:inline-flex">
                  {{ tool.tool_name }}
                </span>
                <span v-if="s.tools.length === 0" style="color:var(--color-text-muted)">—</span>
              </td>
              <td>{{ s.description || '—' }}</td>
            </tr>
            <tr v-if="skills.length === 0"><td colspan="6" style="text-align:center;color:var(--color-text-secondary);padding:24px 0">{{ t("guide.skillsEmpty") }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>{{ t("guide.reqTitle") }}</h3>
        <table class="data-table">
          <thead><tr><th>{{ t("guide.reqColItem") }}</th><th>{{ t("guide.reqColRequire") }}</th><th>{{ t("guide.reqColNote") }}</th></tr></thead>
          <tbody>
            <tr><td>Python</td><td>3.11.9+</td><td>{{ t("guide.reqPython") }}</td></tr>
            <tr><td>Oracle Instant Client</td><td>11g 64-bit</td><td>{{ t("guide.reqOracle") }}</td></tr>
            <tr><td>{{ t("guide.reqDbNetworkItem") }}</td><td>{{ t("guide.reqReachable") }}</td><td>{{ t("guide.reqDbNetwork") }}</td></tr>
            <tr><td>{{ t("guide.reqServerNetworkItem") }}</td><td>{{ t("guide.reqReachable") }}</td><td>{{ t("guide.reqServerNetwork") }}</td></tr>
            <tr><td>{{ t("guide.reqClientItem") }}</td><td>Claude Code / Desktop</td><td>{{ t("guide.reqClient") }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="guide-section">
        <h3>{{ t("guide.faqTitle") }}</h3>
        <div class="faq-item" v-for="(faq, i) in faqs" :key="i" @click="($event.currentTarget as HTMLElement)?.classList?.toggle('open')">
          <div class="faq-q">{{ faq.q }}</div>
          <div class="faq-a">{{ faq.a }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.faq-a { display: none; }
.faq-item.open .faq-a { display: block; }
</style>
