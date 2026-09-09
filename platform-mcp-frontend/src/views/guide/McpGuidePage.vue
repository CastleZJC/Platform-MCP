<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import DataTable, { type DataColumn } from "@/components/DataTable.vue"
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
// 使用建议为静态页面文案：走前端 i18n（zh/en 同键），不再经后端 /guide/usage 下发
const usage = computed(() => [
  { title: t("guide.usageScene1Title"), user_says: t("guide.usageScene1Example"), behavior: t("guide.usageScene1Behavior") },
  { title: t("guide.usageScene2Title"), user_says: t("guide.usageScene2Example"), behavior: t("guide.usageScene2Behavior") },
  { title: t("guide.usageScene3Title"), user_says: t("guide.usageScene3Example"), behavior: t("guide.usageScene3Behavior") },
  { title: t("guide.usageScene4Title"), user_says: t("guide.usageScene4Example"), behavior: t("guide.usageScene4Behavior") },
  { title: t("guide.usageScene5Title"), user_says: t("guide.usageScene5Example"), behavior: t("guide.usageScene5Behavior") },
  { title: t("guide.usageScene6Title"), user_says: t("guide.usageScene6Example"), behavior: t("guide.usageScene6Behavior") },
])
const usageTips = computed(() => [
  t("guide.usageTip1"), t("guide.usageTip2"), t("guide.usageTip3"), t("guide.usageTip4"),
  t("guide.usageTip5"), t("guide.usageTip6"), t("guide.usageTip7"),
])

// ===== 列定义（DataTable 公共组件；列默认等分——原固定列宽已移除）=====
const usageColumns = computed<DataColumn[]>(() => [
  { key: "title", label: t("guide.usageColScene") },
  { key: "user_says", label: t("guide.usageColExample"), cls: "text-mono" },
  { key: "behavior", label: t("guide.usageColBehavior") },
])
const skillsColumns = computed<DataColumn[]>(() => [
  { key: "skill_code", label: t("common.skillCode"), cls: "text-mono" },
  { key: "skill_name", label: t("common.skillName") },
  { key: "register_method", label: t("common.colRegister") },
  { key: "tool_count", label: t("common.colToolCount"), align: "center" },
  { key: "tools", label: t("guide.skillsColTools") },
  { key: "description", label: t("common.note") },
])
const envColumns = computed<DataColumn[]>(() => [
  { key: "item", label: t("guide.reqColItem") },
  { key: "requirement", label: t("guide.reqColRequire") },
  { key: "note", label: t("guide.reqColNote") },
])
const envReqs = computed(() => [
  { item: "Python", requirement: "3.11.9+", note: t("guide.reqPython") },
  { item: "Oracle Instant Client", requirement: "11g 64-bit", note: t("guide.reqOracle") },
  { item: t("guide.reqDbNetworkItem"), requirement: t("guide.reqReachable"), note: t("guide.reqDbNetwork") },
  { item: t("guide.reqServerNetworkItem"), requirement: t("guide.reqReachable"), note: t("guide.reqServerNetwork") },
  { item: t("guide.reqClientItem"), requirement: "Claude Code / Desktop", note: t("guide.reqClient") },
])

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
  const map: Record<string, string> = {
    decorator: t("common.registerDecorator"),
    form: t("common.registerForm"),
    upload: t("common.registerUpload"),
    mcp: t("common.registerMcp"),
    copy: t("common.registerCopy"),
  }
  return map[m] || m
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

onMounted(() => { fetchConfig(); fetchTools() })
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
            <li>{{ t("guide.stepWriteConfig") }}</li>
            <li>{{ t("guide.prodStep5") }}</li>
          </ol>
          <p style="font-size:13px;font-weight:500;color:var(--color-text);margin-top:16px;margin-bottom:8px">{{ t("guide.prodConfigTitle") }}</p>
          <div class="code-block">
            <button class="btn btn-sm code-copy" @click="copyProdConfig">{{ t("common.copy") }}</button>
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
            <li>{{ t("guide.stepWriteConfig") }}</li>
          </ol>
          <p style="font-size:13px;font-weight:500;color:var(--color-text);margin-top:16px;margin-bottom:8px">{{ t("guide.devConfigTitle") }}</p>
          <div class="code-block">
            <button class="btn btn-sm code-copy" @click="copyDevConfig">{{ t("common.copy") }}</button>
            <pre>{{ devConfigJson || '{}' }}</pre>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>{{ t("guide.usageTitle") }}</h3>
        <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">{{ t("guide.usageDesc") }}</p>
        <DataTable :columns="usageColumns" :rows="usage" row-key="title">
          <template #user_says="{ row }">
            <span class="text-mono">{{ row.user_says }}</span>
          </template>
        </DataTable>
        <ul style="margin-top:16px;font-size:13px;color:var(--color-text-secondary);padding-left:20px">
          <li v-for="tip in usageTips" :key="tip" style="margin-bottom:4px">{{ tip }}</li>
        </ul>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>{{ t("guide.skillsTitle") }}</h3>
        <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">{{ t("guide.skillsDesc") }}</p>
        <DataTable
          :columns="skillsColumns"
          :rows="skills"
          :empty-text="t('guide.skillsEmpty')"
          row-key="skill_code"
        >
          <template #skill_name="{ row }">{{ row.skill_name }}</template>
          <template #register_method="{ row }">
            <span class="tag tag-primary">{{ registerMethodLabel(row.register_method) }}</span>
          </template>
          <template #tools="{ row }">
            <span v-for="tool in row.tools" :key="tool.tool_name" class="tag"
              :class="riskTagClass(tool.risk_level)" :title="t('guide.toolTip', { name: tool.display_name, description: tool.description, risk: tool.risk_level })"
              style="margin:2px;display:inline-flex">
              {{ tool.tool_name }}
            </span>
            <span v-if="row.tools.length === 0" style="color:var(--color-text-muted)">—</span>
          </template>
        </DataTable>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>{{ t("guide.reqTitle") }}</h3>
        <DataTable :columns="envColumns" :rows="envReqs" row-key="item" />
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
