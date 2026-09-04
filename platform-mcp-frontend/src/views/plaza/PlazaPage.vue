<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage, ElMessageBox } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import { currentLocale } from "@/i18n"
import type { PlazaSkill, PlazaReadme, PlazaSearchResponse, BlockedSkill } from "@/types"

const { t } = useI18n()
// V3.0 M3.1：按当前 locale 选择双语 README；zh* 取中文，其余取英文
const isZh = computed(() => currentLocale().startsWith("zh"))

const activeTab = ref<"plaza" | "blocked">("plaza")

// ===== Skill 广场页签 =====
const loading = ref(false)
const plazas = ref<PlazaSkill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref("")
// 语义搜索模式：命中 /plaza/search 时展示 similarity 列且不分页
const searchMode = ref(false)

// ===== 黑名单页签 =====
const blockedLoading = ref(false)
const blocked = ref<BlockedSkill[]>([])

// ===== 详情 / README 弹窗 =====
const detailVisible = ref(false)
const detailTarget = ref<PlazaSkill | null>(null)
const readmeVisible = ref(false)
const readmeLoading = ref(false)
const readmeContent = ref("")
const readmeName = ref("")

function localeText(zh: string | null | undefined, en: string | null | undefined): string {
  return (isZh.value ? zh || en : en || zh) || ""
}

async function fetchPlaza() {
  loading.value = true
  try {
    if (search.value.trim()) {
      // F-33：语义搜索（BGE-M3 / 降级哈希向量 + 关键词兜底），返回含 similarity
      const res = await request.get("/plaza/search", { params: { q: search.value.trim(), top_k: 50 } })
      const data = res.data as PlazaSearchResponse
      plazas.value = data.items || []
      total.value = data.total || 0
      searchMode.value = true
    } else {
      const res = await request.get("/plaza", { params: { page: page.value, page_size: pageSize.value } })
      plazas.value = res.data.items || []
      total.value = res.data.total || 0
      searchMode.value = false
    }
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  search.value = ""
  page.value = 1
  fetchPlaza()
}

async function fetchBlocked() {
  blockedLoading.value = true
  try {
    const res = await request.get("/plaza/blocked")
    blocked.value = res.data.items || []
  } finally {
    blockedLoading.value = false
  }
}

function onTabChange(name: string | number) {
  if (name === "blocked") fetchBlocked()
  else fetchPlaza()
}

function openDetail(row: PlazaSkill) {
  detailTarget.value = row
  detailVisible.value = true
}

// README 弹窗：读广场副本双语 README（GET /plaza/{id}/readme），按 locale 选取
async function openReadme(row: PlazaSkill) {
  readmeName.value = row.skill_name
  readmeContent.value = ""
  readmeLoading.value = true
  readmeVisible.value = true
  try {
    const res = await request.get(`/plaza/${row.plaza_id}/readme`)
    const data = res.data as PlazaReadme
    readmeContent.value = localeText(data.readme_zh, data.readme_en)
  } finally {
    readmeLoading.value = false
  }
}

// 添加至我的：复制广场副本到个人库（origin=PLAZA，status=ENABLED 可直接使用）
// 拦截器已对 code!=0 统一弹错并 reject，此处仅在成功后提示（与 SkillPage 一致）
async function copyToMy(row: PlazaSkill) {
  try {
    await ElMessageBox.confirm(
      t("plaza.copyConfirmMsg", { name: row.skill_name }),
      t("plaza.copyConfirmTitle"),
      { type: "warning" },
    )
  } catch {
    return
  }
  await request.post(`/plaza/${row.plaza_id}/copy`)
  ElMessage.success(t("plaza.copySuccess"))
  detailVisible.value = false
}

// 屏蔽：二次确认 + 可选原因（F-34，屏蔽后双端不可见，仅黑名单页可见，可撤销）
async function blockSkill(row: PlazaSkill) {
  let reason = ""
  try {
    const r = await ElMessageBox.prompt(
      t("plaza.blockConfirmMsg"),
      t("plaza.blockConfirmTitle"),
      { inputPlaceholder: t("plaza.blockReasonPlaceholder"), inputValidator: () => true },
    )
    reason = r.value || ""
  } catch {
    return
  }
  await request.post("/plaza/block", { plaza_id: row.plaza_id, reason: reason || null })
  ElMessage.success(t("plaza.blockSuccess"))
  fetchPlaza()
}

// 撤销屏蔽（黑名单页签）
async function unblock(entry: BlockedSkill) {
  const payload =
    entry.target_type === "plaza" ? { plaza_id: entry.target_id } : { skill_id: entry.target_id }
  await request.post("/plaza/unblock", payload)
  ElMessage.success(t("plaza.unblockSuccess"))
  fetchBlocked()
}

function involveLabels(flags: string[]): string[] {
  const out: string[] = []
  if (flags.includes("database")) out.push(t("plaza.involveDatabase"))
  if (flags.includes("server")) out.push(t("plaza.involveServer"))
  return out
}

function uploaderName(row: PlazaSkill): string {
  const u = row.uploader
  if (!u) return "-"
  return u.nickname || u.username || "-"
}

onMounted(fetchPlaza)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("plaza.title") }}</h2>
      <p>{{ t("plaza.subtitle") }}</p>
    </div>

    <el-tabs v-model="activeTab" class="plaza-tabs" @tab-change="onTabChange">
      <!-- ===== Skill 广场 ===== -->
      <el-tab-pane :label="t('plaza.tabPlaza')" name="plaza">
        <div class="card">
          <div class="toolbar">
            <div class="toolbar-left">
              <input
                type="text"
                class="search-input"
                v-model="search"
                :placeholder="t('plaza.searchPlaceholder')"
                @keyup.enter="fetchPlaza"
              />
              <button class="btn btn-primary" @click="fetchPlaza">{{ t("plaza.searchBtn") }}</button>
              <button class="btn" @click="resetSearch">{{ t("plaza.resetBtn") }}</button>
            </div>
          </div>
          <table class="data-table plaza-table">
            <thead>
              <tr>
                <th>{{ t("plaza.colCode") }}</th>
                <th>{{ t("plaza.colName") }}</th>
                <th>{{ t("plaza.colVersion") }}</th>
                <th>{{ t("plaza.colUploader") }}</th>
                <th>{{ t("plaza.colInvolve") }}</th>
                <th v-if="searchMode">{{ t("plaza.colSimilarity") }}</th>
                <th>{{ t("plaza.colStatus") }}</th>
                <th>{{ t("plaza.colDescription") }}</th>
                <th>{{ t("plaza.colActions") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in plazas" :key="row.plaza_id">
                <td class="text-mono">{{ row.skill_code }}</td>
                <td>{{ row.skill_name }}</td>
                <td class="text-mono">{{ row.version || "-" }}</td>
                <td>{{ uploaderName(row) }}</td>
                <td>
                  <template v-if="involveLabels(row.involve_flags).length">
                    <span
                      v-for="lbl in involveLabels(row.involve_flags)"
                      :key="lbl"
                      class="tag tag-warning involve-tag"
                    >{{ lbl }}</span>
                  </template>
                  <span v-else>{{ t("plaza.involveNone") }}</span>
                </td>
                <td v-if="searchMode" class="text-mono">
                  {{ row.similarity != null ? row.similarity.toFixed(3) : "-" }}
                </td>
                <td><span class="status-dot active">{{ t("plaza.statusPublished") }}</span></td>
                <td>{{ row.description || "-" }}</td>
                <td class="actions">
                  <button class="btn btn-sm" @click="openDetail(row)">{{ t("plaza.detailAction") }}</button>
                  <button class="btn btn-sm" @click="openReadme(row)">{{ t("plaza.readmeAction") }}</button>
                  <button class="btn btn-sm btn-primary" @click="copyToMy(row)">{{ t("plaza.copyAction") }}</button>
                  <button class="btn btn-sm btn-danger" @click="blockSkill(row)">{{ t("plaza.blockAction") }}</button>
                </td>
              </tr>
              <tr v-if="!loading && plazas.length === 0">
                <td :colspan="searchMode ? 9 : 8" class="empty-cell">{{ t("plaza.emptyPlaza") }}</td>
              </tr>
            </tbody>
          </table>
          <Pagination
            v-if="!searchMode"
            v-model:page="page"
            v-model:pageSize="pageSize"
            :total="total"
            @change="fetchPlaza"
          />
        </div>
      </el-tab-pane>

      <!-- ===== Skill 黑名单 ===== -->
      <el-tab-pane :label="t('plaza.tabBlocked')" name="blocked">
        <div class="card">
          <table class="data-table blocked-table">
            <thead>
              <tr>
                <th>{{ t("plaza.blockedColType") }}</th>
                <th>{{ t("plaza.blockedColCode") }}</th>
                <th>{{ t("plaza.blockedColName") }}</th>
                <th>{{ t("plaza.blockedColReason") }}</th>
                <th>{{ t("plaza.blockedColCreatedAt") }}</th>
                <th>{{ t("plaza.blockedColActions") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in blocked" :key="entry.id">
                <td>
                  <span class="tag" :class="entry.target_type === 'plaza' ? 'tag-primary' : 'tag-info'">
                    {{ entry.target_type === "plaza" ? t("plaza.targetTypePlaza") : t("plaza.targetTypeSkill") }}
                  </span>
                </td>
                <td class="text-mono">{{ entry.skill_code || "-" }}</td>
                <td>{{ entry.skill_name || "-" }}</td>
                <td>{{ entry.reason || "-" }}</td>
                <td>{{ entry.created_at || "-" }}</td>
                <td class="actions">
                  <button class="btn btn-sm btn-primary" @click="unblock(entry)">{{ t("plaza.unblockAction") }}</button>
                </td>
              </tr>
              <tr v-if="!blockedLoading && blocked.length === 0">
                <td colspan="6" class="empty-cell">{{ t("plaza.emptyBlocked") }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="t('plaza.detailTitle', { name: detailTarget?.skill_name ?? '' })" width="600">
      <div v-if="detailTarget" class="detail-body">
        <p><b>{{ t("plaza.colCode") }}</b> {{ detailTarget.skill_code }}</p>
        <p><b>{{ t("plaza.colName") }}</b> {{ detailTarget.skill_name }}</p>
        <p><b>{{ t("plaza.detailVersion") }}</b> {{ detailTarget.version || "-" }}</p>
        <p><b>{{ t("plaza.detailUploader") }}</b> {{ uploaderName(detailTarget) }}</p>
        <p><b>{{ t("plaza.detailInvolve") }}</b>
          <template v-if="involveLabels(detailTarget.involve_flags).length">
            <span
              v-for="lbl in involveLabels(detailTarget.involve_flags)"
              :key="lbl"
              class="tag tag-warning involve-tag"
            >{{ lbl }}</span>
          </template>
          <span v-else>{{ t("plaza.involveNone") }}</span>
        </p>
        <p><b>{{ t("plaza.detailStatus") }}</b> {{ t("plaza.statusPublished") }}</p>
        <p v-if="detailTarget.iteration_note"><b>{{ t("plaza.detailIterationNote") }}</b> {{ detailTarget.iteration_note }}</p>
        <p><b>{{ t("plaza.detailCreatedAt") }}</b> {{ detailTarget.created_at || "-" }}</p>
        <p><b>{{ t("plaza.detailUpdatedAt") }}</b> {{ detailTarget.updated_at || "-" }}</p>
        <p><b>{{ t("plaza.detailDescription") }}</b> {{ detailTarget.description || "-" }}</p>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="copyToMy(detailTarget!)">{{ t("plaza.copyAction") }}</el-button>
      </template>
    </el-dialog>

    <!-- README 弹窗（按 locale 取双语 README） -->
    <el-dialog v-model="readmeVisible" :title="t('plaza.readmeTitle', { name: readmeName })" width="700">
      <div v-if="readmeLoading">{{ t("common.loading") }}</div>
      <pre v-else-if="readmeContent" class="readme-body">{{ readmeContent }}</pre>
      <p v-else>{{ t("plaza.readmeEmpty") }}</p>
    </el-dialog>
  </div>
</template>

<style scoped>
.plaza-tabs { margin-bottom: 4px; }
.involve-tag { margin-right: 4px; }
.empty-cell { text-align: center; color: var(--color-text-secondary); padding: 24px 0; }
.detail-body p { margin: 6px 0; font-size: 14px; }
.readme-body { white-space: pre-wrap; word-break: break-word; background: #f7f8fa; border-radius: 6px; padding: 12px; max-height: 420px; overflow: auto; font-size: 13px; line-height: 1.6; }
</style>
