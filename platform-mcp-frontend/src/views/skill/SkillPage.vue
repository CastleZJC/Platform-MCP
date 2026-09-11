<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { ElMessage, ElMessageBox } from "element-plus"
import request from "@/utils/request"
import Pagination from "@/components/Pagination.vue"
import DataTable, { type DataColumn } from "@/components/DataTable.vue"
import { useUserStore } from "@/stores/user"
import { currentLocale } from "@/i18n"
import type {
  Skill,
  SkillVersion,
  SkillVersionsResponse,
  SkillIterationDiff,
  PlazaSkill,
  MergeBuildResult,
  MergeCandidate,
  MergeConflict,
  PendingSkill,
  SkillFileEntry,
  SkillFilesResponse,
  SkillFileContent,
} from "@/types"

const { t } = useI18n()
const userStore = useUserStore()
const username = computed(() => userStore.user?.username ?? "")
const isAdmin = computed(() => userStore.isAdmin)

const loading = ref(false)
const skills = ref<Skill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(userStore.pageSize)
const search = ref("")
const statusFilter = ref("")

// ===== 批次 7：双视图（我的 Skill / 待审提交，admin 独立分页）=====
const activeTab = ref("mine")
const pendingSkills = ref<PendingSkill[]>([])
const pendingTotal = ref(0)
const pendingPage = ref(1)
const pendingPageSize = ref(userStore.pageSize)

// ===== 列定义（DataTable 公共组件；computed 保持语言切换响应）=====
const skillColumns = computed<DataColumn[]>(() => [
  { key: "skill_code", label: t("common.skillCode"), cls: "text-mono" },
  { key: "skill_name", label: t("common.skillName") },
  { key: "status", label: t("common.colStatus") },
  { key: "tool_count", label: t("common.colToolCount"), align: "center" },
  { key: "register_method", label: t("common.colRegister") },
  { key: "actions", label: t("common.colActions") },
])

// 待审提交列（批次 7.2：code/名称/提交人/通道/时间/版本/同名比对/操作）
const pendingColumns = computed<DataColumn[]>(() => [
  { key: "skill_code", label: t("common.skillCode"), cls: "text-mono" },
  { key: "skill_name", label: t("common.skillName") },
  { key: "submitted_by", label: t("skill.pendingSubmitter") },
  { key: "register_method", label: t("skill.pendingChannel") },
  { key: "created_at", label: t("common.time") },
  { key: "version", label: t("skill.pendingVersion") },
  { key: "name_match", label: t("skill.pendingNameMatch") },
  { key: "actions", label: t("common.colActions") },
])

// 审核弹窗（仅 admin，仅审核中）
const reviewVisible = ref(false)
const reviewTarget = ref<Skill | null>(null)
const reviewComment = ref("")
const reviewVersion = ref<SkillVersion | null>(null)
const reviewLoading = ref(false)
// 批次 7.3：审核弹窗文件预览（包内清单 + 单文件内容，admin 专用端点）
const reviewFiles = ref<SkillFileEntry[]>([])
const reviewFilesLoading = ref(false)
const reviewFileContent = ref<SkillFileContent | null>(null)

// merge 工作台（设计定稿④，admin：build → 冲突逐文件裁决 → publish/discard，merge_token 供 CC 试用；
// 场景①原创并入走此通道，快捷合并（无试用）仅限已关联广场的副本）
const mergeVisible = ref(false)
const mergeSource = ref<Skill | null>(null)
const mergePlazas = ref<PlazaSkill[]>([])
const mergePlazaId = ref<number | null>(null)
const mergeBaseVersion = ref("")
const mergeTargetVersion = ref("")
const mergeComment = ref("")
const mergeBuilding = ref(false)
const mergeResult = ref<MergeBuildResult | null>(null)
const mergeResolutions = ref<Record<string, number | "base">>({})
const mergeOperating = ref(false)

// 上传弹窗（新建）
const uploadVisible = ref(false)
const uploadFile = ref<File | null>(null)
const uploadLoading = ref(false)

// README 图标弹窗（按 locale）
const readmeVisible = ref(false)
const readmeLoading = ref(false)
const readmeContent = ref("")
const readmeSkillName = ref("")
const readmeGeneratedBy = ref<string | null>(null)

// 分享管理 Sheet（owner：分享 / 更新 / 撤回 / 迭代 + 逐版本审核日志）
const sheetVisible = ref(false)
const sheetTarget = ref<Skill | null>(null)
const updateFile = ref<File | null>(null)
const sheetLoading = ref(false)
const sheetVersions = ref<SkillVersion[]>([])
const sheetLogLoading = ref(false)
// 批次 6.1：重命名（Sheet 内改 skill_code，后端同步磁盘目录）
const renameCode = ref("")
const renaming = ref(false)

// M4.3：分享迭代差异（本地 vs 广场快照，F-30）；Sheet 打开时并行拉取
const iterationDiff = ref<SkillIterationDiff | null>(null)
const iterationDiffLoading = ref(false)
const diffExpanded = ref(false)

// 设计定稿②：迭代态新版 README 预览（广场发布口径，GET /plaza/{id}/readme）
const plazaReadme = ref("")
const plazaReadmeLoading = ref(false)

// 版本审核反馈弹窗（Sheet 日志"详情"，展示该版本双语存档报告）
const versionReportVisible = ref(false)
const versionReportContent = ref("")
const versionReportName = ref("")
const versionReportGeneratedBy = ref<string | null>(null)

function isOwner(skill: Skill): boolean {
  return !!username.value && skill.submitted_by === username.value
}

// owner 可经 Sheet 操作的状态（分享 / 更新 / 撤回 / 迭代）
const SHEET_STATES = ["DRAFT", "ENABLED", "DISABLED", "PENDING_REVIEW", "REJECTED", "WITHDRAWN", "SHARE_ITERATION"]
function canManage(skill: Skill): boolean {
  return isOwner(skill) && SHEET_STATES.includes(skill.status)
}

// 批次 6.1：可重命名的稳定态（过渡态先撤回/解决迭代；与后端 personal.rename_my_skill 同矩阵）
const RENAMABLE_STATES = ["DRAFT", "REJECTED", "WITHDRAWN", "ENABLED", "DISABLED"]
function canRename(skill: Skill): boolean {
  return (
    isOwner(skill) &&
    skill.register_method !== "decorator" &&
    skill.origin !== "PLAZA" &&
    !skill.plaza_id &&
    RENAMABLE_STATES.includes(skill.status)
  )
}

// 批次 6.3：启停入口（owner 或 admin 均经状态机留痕）；内置装饰器/广场复制仅 admin（后端同口径）
function canToggle(skill: Skill): boolean {
  if (skill.register_method === "decorator" || skill.origin === "PLAZA") return isAdmin.value
  return isAdmin.value || isOwner(skill)
}

async function fetchSkills() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await request.get("/skills", { params })
    skills.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

// 批次 7：待审提交（admin 独立分页；切到待审 Tab 时拉取）
async function fetchPending() {
  const res = await request.get("/skills/pending", {
    params: { page: pendingPage.value, page_size: pendingPageSize.value },
  })
  pendingSkills.value = res.data.items
  pendingTotal.value = res.data.total
}

function onTabChange(name: string | number) {
  if (name === "pending") fetchPending()
}

// 待审行 → Skill 视图模型（审核弹窗复用：补齐弹窗展示所需字段）
function pendingToSkill(p: PendingSkill): Skill {
  return {
    id: p.id,
    skill_code: p.skill_code,
    skill_name: p.skill_name,
    description: p.description,
    status: p.status,
    tool_count: 0,
    register_method: p.register_method,
    submitted_by: p.submitted_by,
    source_format: null,
    version: p.version,
    audit_status: p.audit_status,
    readme_generated: false,
    created_at: p.created_at ?? "",
    origin: p.origin,
    plaza_id: p.plaza_id,
    review_comment: p.review_comment,
  }
}

// 同名比对裁决（设计定稿⑪：同名+功能似→建议合并 / 同名+功能异→打回参考 / 名异+功能似→合并候选）
function nmLabel(verdict: string) {
  const map: Record<string, string> = {
    merge: t("skill.nmMerge"),
    reject_ref: t("skill.nmRejectRef"),
    merge_candidate: t("skill.nmMergeCandidate"),
  }
  return map[verdict] || verdict
}

function nmClass(verdict: string) {
  if (verdict === "merge") return "tag-warning"
  if (verdict === "reject_ref") return "tag-danger"
  return "tag-info"
}

function pickFile(e: Event): File | null {
  const input = e.target as HTMLInputElement
  const f = input.files && input.files[0]
  if (!f) return null
  if (!f.name.endsWith(".zip") && !f.name.endsWith(".7z")) {
    ElMessage.error(t("skill.uploadFormatError"))
    return null
  }
  return f
}

function openUpload() {
  uploadFile.value = null
  uploadVisible.value = true
}

function handleFileChange(e: Event) {
  const f = pickFile(e)
  if (f) uploadFile.value = f
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning(t("skill.uploadNoFile"))
    return
  }
  uploadLoading.value = true
  try {
    const formData = new FormData()
    formData.append("file", uploadFile.value)
    await request.post("/skills/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    ElMessage.success(t("skill.uploadSuccess"))
    uploadVisible.value = false
    fetchSkills()
  } catch {
    ElMessage.error(t("skill.uploadFailed"))
  } finally {
    uploadLoading.value = false
  }
}

// 启停（批次 6.3：owner 或 admin 均经状态机留痕；内置装饰器/广场复制仅 admin 可调）
async function handleStatus(skill: Skill, status: string) {
  await request.put(`/skills/${skill.id}/status`, { status })
  ElMessage.success(t("common.statusUpdated"))
  fetchSkills()
}

// 重命名（批次 6.1）：PUT /skills/{id}（owner 同条件矩阵，磁盘目录同步改名）
async function submitRename() {
  const s = sheetTarget.value
  if (!s) return
  const code = renameCode.value.trim()
  if (!code) {
    ElMessage.warning(t("skill.renameEmpty"))
    return
  }
  renaming.value = true
  try {
    await request.put(`/skills/${s.id}`, { skill_code: code })
    ElMessage.success(t("skill.renameSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    renaming.value = false
  }
}

// 选取当前 locale 的存档文本（批次 5.2 分级取值：zh/en 主列 → extra 补档命中 → 回退）
function localeText(
  zh: string | null | undefined,
  en: string | null | undefined,
  extra?: Record<string, string> | null,
): string {
  const loc = currentLocale().toLowerCase()
  if (loc.startsWith("zh")) return zh || en || ""
  if (loc.startsWith("en")) return en || zh || ""
  if (extra) {
    const lang = loc.split("-")[0]
    const hit = Object.keys(extra).find(
      (k) => (k.toLowerCase() === loc || k.toLowerCase() === lang) && extra[k],
    )
    if (hit) return extra[hit]
  }
  return zh || en || ""
}

// README 图标弹窗：读取版本存档最新条目的双语 README（M4：generated_by=model 时附带性能提示）
async function openReadme(skill: Skill) {
  readmeSkillName.value = skill.skill_name
  readmeContent.value = ""
  readmeGeneratedBy.value = null
  readmeLoading.value = true
  readmeVisible.value = true
  try {
    const res = await request.get(`/skills/${skill.id}/versions`)
    const data = res.data as SkillVersionsResponse
    const latest = data.versions?.[0]
    readmeContent.value = latest ? localeText(latest.readme_zh, latest.readme_en, latest.readme_extra) : ""
    readmeGeneratedBy.value = latest?.generated_by ?? null
  } finally {
    readmeLoading.value = false
  }
}

// 审核弹窗（admin，仅 PENDING_REVIEW）：审核报告 + README（均来自最新版本存档）+ 文件预览（批次 7.3）
async function openReview(skill: Skill) {
  reviewTarget.value = skill
  reviewComment.value = ""
  reviewVersion.value = null
  reviewFiles.value = []
  reviewFileContent.value = null
  reviewVisible.value = true
  reviewLoading.value = true
  void loadReviewFiles(skill.id)
  try {
    const res = await request.get(`/skills/${skill.id}/versions`)
    const versions = (res.data as SkillVersionsResponse).versions || []
    reviewVersion.value = versions[0] || null
  } finally {
    reviewLoading.value = false
  }
}

// 包内文件清单（与版本存档并行拉取；失败不阻断审核，仅清空展示）
async function loadReviewFiles(skillId: number) {
  reviewFilesLoading.value = true
  try {
    const res = await request.get(`/skills/${skillId}/files`)
    reviewFiles.value = (res.data as SkillFilesResponse).files || []
  } catch {
    reviewFiles.value = []
  } finally {
    reviewFilesLoading.value = false
  }
}

// 单文件内容预览（文本直读 / 二进制 base64 提示）
async function previewReviewFile(path: string) {
  if (!reviewTarget.value) return
  reviewFileContent.value = null
  const res = await request.get(`/skills/${reviewTarget.value.id}/files`, { params: { path } })
  reviewFileContent.value = res.data as SkillFileContent
}

const reviewReport = computed(() =>
  reviewVersion.value
    ? localeText(reviewVersion.value.report_zh, reviewVersion.value.report_en, reviewVersion.value.report_extra)
    : ""
)
const reviewReadme = computed(() =>
  reviewVersion.value
    ? localeText(reviewVersion.value.readme_zh, reviewVersion.value.readme_en, reviewVersion.value.readme_extra)
    : ""
)

async function submitReview(action: string) {
  await request.post(`/skills/${reviewTarget.value!.id}/review`, {
    action,
    comment: reviewComment.value,
  })
  ElMessage.success(t("skill.reviewDone"))
  reviewVisible.value = false
  fetchSkills()
  if (isAdmin.value) fetchPending()
}

// ===== merge 工作台（设计定稿④，admin）=====

// 打开工作台：拉取目标广场候选（admin 视角含已停用项供追溯）；已关联广场预填，迭代说明预填审核意见
async function openMergeWorkbench(skill: Skill | null) {
  if (!skill) return
  mergeSource.value = skill
  mergePlazaId.value = skill.plaza_id ?? null
  mergeBaseVersion.value = ""
  mergeTargetVersion.value = ""
  mergeComment.value = reviewComment.value
  mergeResult.value = null
  mergeResolutions.value = {}
  mergeVisible.value = true
  try {
    const res = await request.get("/plaza", { params: { page: 1, page_size: 100 } })
    mergePlazas.value = res.data.items || []
  } catch {
    mergePlazas.value = []
  }
}

async function buildMerge() {
  if (!mergeSource.value || !mergePlazaId.value) return
  mergeBuilding.value = true
  try {
    const res = await request.post("/plaza/merge/build", {
      plaza_id: mergePlazaId.value,
      source_skill_ids: [mergeSource.value.id],
      base_version: mergeBaseVersion.value || undefined,
      target_version: mergeTargetVersion.value || undefined,
      comment: mergeComment.value || undefined,
    })
    mergeResult.value = res.data as MergeBuildResult
    // 裁决默认 = 主源（临时包已按默认写入；表单仅维护当前选择）
    mergeResolutions.value = {}
    for (const c of mergeResult.value.conflicts || []) {
      mergeResolutions.value[c.path] = c.default_source_skill_id
    }
  } finally {
    mergeBuilding.value = false
  }
}

function mergeRoleLabel(role: string) {
  const map: Record<string, string> = {
    primary: t("skill.mergePrimaryRole"),
    secondary: t("skill.mergeSecondaryRole"),
    base: t("skill.mergeBaseRole"),
  }
  return map[role] || role
}

function candidateValue(cand: MergeCandidate): string {
  return cand.source_skill_id === null ? "base" : String(cand.source_skill_id)
}

function onResolutionChange(c: MergeConflict, e: Event) {
  const v = (e.target as HTMLSelectElement).value
  mergeResolutions.value[c.path] = v === "base" ? "base" : Number(v)
}

const mergeCriticalCount = computed(() => Number(mergeResult.value?.audit_summary?.critical_count ?? 0))

async function publishMerge(action: "publish" | "discard") {
  if (!mergeResult.value) return
  mergeOperating.value = true
  try {
    const res = await request.post(`/plaza/merge/${mergeResult.value.merge_token}/publish`, {
      action,
      resolutions: action === "publish" ? mergeResolutions.value : undefined,
      comment: mergeComment.value || undefined,
    })
    if (action === "discard") {
      ElMessage.success(t("skill.mergeDiscarded"))
    } else {
      ElMessage.success(t("skill.mergePublished", {
        version: res.data?.new_version ?? mergeResult.value.new_version,
        count: res.data?.holders_marked ?? 0,
      }))
    }
    mergeVisible.value = false
    fetchSkills()
  } finally {
    mergeOperating.value = false
  }
}

// ===== 分享管理 Sheet（owner）=====
// 打开即拉取版本存档：逐版本审核日志（每次审计的反馈及信息）；
// M4.3：SHARE_ITERATION 态并行拉取迭代差异（本地 vs 广场快照，F-30），失败不阻断迭代操作
async function openSheet(skill: Skill) {
  sheetTarget.value = skill
  updateFile.value = null
  renameCode.value = ""
  sheetVersions.value = []
  sheetVisible.value = true
  sheetLogLoading.value = true
  if (skill.status === "SHARE_ITERATION") {
    void fetchIterationDiff(skill)
    void fetchPlazaReadme(skill)
  }
  try {
    const res = await request.get(`/skills/${skill.id}/versions`)
    sheetVersions.value = (res.data as SkillVersionsResponse).versions || []
  } finally {
    sheetLogLoading.value = false
  }
}

// M4.3：迭代差异描述（模板/本地模型双语描述 + 性能提示，M4.4）
async function fetchIterationDiff(skill: Skill) {
  iterationDiff.value = null
  diffExpanded.value = false
  iterationDiffLoading.value = true
  try {
    const res = await request.get(`/skills/${skill.id}/iteration-diff`)
    iterationDiff.value = res.data as SkillIterationDiff
  } catch {
    // 差异加载失败不阻断迭代决策（拦截器已统一提示；仅清空展示）
    iterationDiff.value = null
  } finally {
    iterationDiffLoading.value = false
  }
}

const diffDescription = computed(() =>
  iterationDiff.value ? localeText(iterationDiff.value.description_zh, iterationDiff.value.description_en) : ""
)
const diffHint = computed(() =>
  iterationDiff.value
    ? localeText(iterationDiff.value.performance_hint_zh, iterationDiff.value.performance_hint_en)
    : ""
)

// 设计定稿②：新版 README 预览（按 locale；失败/无 plaza_id 不阻断迭代决策，仅清空展示）
async function fetchPlazaReadme(skill: Skill) {
  plazaReadme.value = ""
  if (!skill.plaza_id) return
  plazaReadmeLoading.value = true
  try {
    const res = await request.get(`/plaza/${skill.plaza_id}/readme`)
    plazaReadme.value = localeText(res.data.readme_zh, res.data.readme_en)
  } catch {
    plazaReadme.value = ""
  } finally {
    plazaReadmeLoading.value = false
  }
}

// 版本审计结论：audit_snapshot.passed（无快照 → null 展示 "-"）
function versionPassed(v: SkillVersion): boolean | null {
  const snap = v.audit_snapshot as { passed?: boolean } | null
  if (!snap) return null
  return snap.passed === true
}

// 版本审核反馈详情：展示该版本双语存档报告（按 locale；M4：model 来源附带性能提示）
function openVersionReport(v: SkillVersion) {
  versionReportName.value = `v${v.version}`
  versionReportContent.value = localeText(v.report_zh, v.report_en, v.report_extra)
  versionReportGeneratedBy.value = v.generated_by ?? null
  versionReportVisible.value = true
}

// F-31 重复分享：已分享 / 审核管线中 → 前端预检二次确认（后端 10005 为安全网）
const needReshareConfirm = computed(() => {
  const s = sheetTarget.value
  if (!s) return false
  return s.share_status === "shared" || ["PENDING_REVIEW", "APPROVED", "SHARE_ITERATION"].includes(s.status)
})

async function submitShare() {
  const s = sheetTarget.value
  if (!s) return
  let confirmReshare = false
  if (needReshareConfirm.value) {
    try {
      await ElMessageBox.confirm(t("skill.reshareConfirmMsg"), t("skill.reshareConfirmTitle"), {
        type: "warning",
      })
      confirmReshare = true
    } catch {
      return
    }
  }
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/submit`, { confirm_reshare: confirmReshare })
    ElMessage.success(t("skill.submitSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

async function withdrawShare() {
  const s = sheetTarget.value
  if (!s) return
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/withdraw`)
    ElMessage.success(t("skill.withdrawSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

// 撤回/已拒绝 → 恢复为草稿（后端按状态走 restore/revise，无需重新上传包）
async function toDraft() {
  const s = sheetTarget.value
  if (!s) return
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/${s.status === "REJECTED" ? "revise" : "restore"}`)
    ElMessage.success(t("skill.toDraftSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

async function resolveIteration(choice: "iterate" | "keep") {
  const s = sheetTarget.value
  if (!s) return
  sheetLoading.value = true
  try {
    await request.post(`/skills/${s.id}/resolve-iteration`, { choice })
    ElMessage.success(t("skill.resolveSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } finally {
    sheetLoading.value = false
  }
}

function handleUpdateFileChange(e: Event) {
  const f = pickFile(e)
  if (f) updateFile.value = f
}

// 更新（重新上传同编码包 → 后端 upsert + 状态机联动 REVISE/RESTORE）
async function submitUpdate() {
  if (!updateFile.value) {
    ElMessage.warning(t("skill.uploadNoFile"))
    return
  }
  sheetLoading.value = true
  try {
    const formData = new FormData()
    formData.append("file", updateFile.value)
    await request.post("/skills/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    ElMessage.success(t("skill.updateSuccess"))
    sheetVisible.value = false
    fetchSkills()
  } catch {
    ElMessage.error(t("skill.uploadFailed"))
  } finally {
    sheetLoading.value = false
  }
}

function auditStatusLabel(status: string | null) {
  const map: Record<string, string> = {
    pending: t("skill.auditPending"),
    passed: t("skill.auditPassed"),
    failed: t("skill.auditFailed"),
  }
  return map[status || ""] || status || "-"
}

// 8 状态生命周期标签（勘误：此前仅 4 状态）
function statusLabel(status: string) {
  const map: Record<string, string> = {
    DRAFT: t("skill.stateDraft"),
    PENDING_REVIEW: t("skill.statePending"),
    APPROVED: t("skill.stateApproved"),
    REJECTED: t("skill.stateRejected"),
    SHARE_ITERATION: t("skill.stateShareIteration"),
    ENABLED: t("common.enabled"),
    DISABLED: t("common.disabled"),
    WITHDRAWN: t("skill.stateWithdrawn"),
  }
  return map[status] || status
}

function statusDotClass(status: string) {
  if (status === "ENABLED" || status === "APPROVED") return "active"
  if (status === "PENDING_REVIEW" || status === "SHARE_ITERATION") return "pending"
  return "inactive"
}

function originLabel(origin: string | null | undefined) {
  if (origin === "PLAZA") return t("skill.originPlaza")
  if (origin) return t("skill.originSelf")
  return "-"
}

// M4（F-35）：产物来源标签（template 模板 / model 本地 Qwen3 / external MCP 外部大模型 glm 5.3）
function generatedByLabel(by: string | null | undefined) {
  const map: Record<string, string> = {
    template: t("skill.genByTemplate"),
    model: t("skill.genByModel"),
    external: t("skill.genByExternal"),
  }
  return by ? map[by] || by : ""
}

// 注册方式标签（与 McpGuidePage 同源 common.register*；后端值 decorator/form/upload/mcp/copy）
function registerMethodLabel(m: string | null | undefined) {
  const map: Record<string, string> = {
    decorator: t("common.registerDecorator"),
    form: t("common.registerForm"),
    upload: t("common.registerUpload"),
    mcp: t("common.registerMcp"),
    copy: t("common.registerCopy"),
  }
  return (m && map[m]) || m || "—"
}

onMounted(fetchSkills)
</script>

<template>
  <div>
    <div class="page-header">
      <h2>{{ t("skill.title") }}</h2>
      <p>{{ t("skill.subtitle") }}</p>
    </div>
    <div class="card">
      <!-- 批次 7.2：双视图「我的 Skill / 待审提交（admin）」；待审页签 lazy 首次激活才渲染，与我的视图互不串表 -->
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane :label="t('skill.tabMine')" name="mine">
          <div class="toolbar">
            <div class="toolbar-left">
              <input type="text" class="search-input" v-model="search" :placeholder="t('skill.searchPlaceholder')" @keyup.enter="fetchSkills">
              <select class="form-select" v-model="statusFilter" @change="fetchSkills">
                <option value="">{{ t("common.allStatus") }}</option>
                <option value="DRAFT">{{ t("skill.stateDraft") }}</option>
                <option value="PENDING_REVIEW">{{ t("skill.statePending") }}</option>
                <option value="APPROVED">{{ t("skill.stateApproved") }}</option>
                <option value="REJECTED">{{ t("skill.stateRejected") }}</option>
                <option value="SHARE_ITERATION">{{ t("skill.stateShareIteration") }}</option>
                <option value="ENABLED">{{ t("common.enabled") }}</option>
                <option value="DISABLED">{{ t("common.disabled") }}</option>
                <option value="WITHDRAWN">{{ t("skill.stateWithdrawn") }}</option>
              </select>
              <button class="btn" @click="fetchSkills">{{ t("common.query") }}</button>
            </div>
            <div class="toolbar-right">
              <button class="btn btn-primary" @click="openUpload">{{ t("skill.add") }}</button>
            </div>
          </div>
          <DataTable :columns="skillColumns" :rows="skills" row-key="id">
            <template #status="{ row }">
              <span class="status-dot" :class="statusDotClass(row.status)">{{ statusLabel(row.status) }}</span>
            </template>
            <template #register_method="{ row }">
              <span class="tag" :class="row.register_method === 'decorator' ? 'tag-primary' : 'tag-info'">{{ registerMethodLabel(row.register_method) }}</span>
            </template>
            <template #actions="{ row }">
              <button class="btn btn-sm" @click="openReadme(row)">{{ t("common.readmeAction") }}</button>
              <button v-if="canManage(row)" class="btn btn-sm btn-primary" @click="openSheet(row)">{{ t("skill.manageAction") }}</button>
              <button v-if="isAdmin && row.status === 'PENDING_REVIEW'" class="btn btn-sm btn-success" @click="openReview(row)">{{ t("skill.reviewAction") }}</button>
              <button v-if="canToggle(row) && row.status === 'ENABLED'" class="btn btn-sm btn-danger" @click="handleStatus(row, 'DISABLED')">{{ t("common.disable") }}</button>
              <button v-if="canToggle(row) && row.status === 'DISABLED'" class="btn btn-sm btn-primary" @click="handleStatus(row, 'ENABLED')">{{ t("common.enable") }}</button>
            </template>
          </DataTable>
          <Pagination v-model:page="page" v-model:pageSize="pageSize" :total="total" @change="fetchSkills" />
        </el-tab-pane>

        <!-- 待审提交（admin 独立分页，page_size 取用户级 pmcp_user.page_size） -->
        <el-tab-pane v-if="isAdmin" :label="t('skill.tabPending')" name="pending" lazy>
          <DataTable :columns="pendingColumns" :rows="pendingSkills" row-key="id">
            <template #register_method="{ row }">
              <span class="tag" :class="row.register_method === 'decorator' ? 'tag-primary' : 'tag-info'">{{ registerMethodLabel(row.register_method) }}</span>
            </template>
            <template #created_at="{ row }">
              <span>{{ row.created_at ? row.created_at.slice(0, 16).replace("T", " ") : "-" }}</span>
            </template>
            <template #version="{ row }">
              <span class="text-mono">{{ row.version ? "v" + row.version : "-" }}</span>
            </template>
            <template #name_match="{ row }">
              <template v-if="row.name_match?.length">
                <div v-for="m in row.name_match" :key="m.plaza_id" class="nm-row">
                  <span class="tag" :class="nmClass(m.verdict)">{{ nmLabel(m.verdict) }}</span>
                  <span class="text-mono">{{ m.skill_code }}</span>
                  <span>{{ (m.similarity * 100).toFixed(1) }}%</span>
                </div>
              </template>
              <span v-else>-</span>
            </template>
            <template #actions="{ row }">
              <button class="btn btn-sm btn-success" @click="openReview(pendingToSkill(row))">{{ t("skill.reviewAction") }}</button>
            </template>
          </DataTable>
          <Pagination v-model:page="pendingPage" v-model:pageSize="pendingPageSize" :total="pendingTotal" @change="fetchPending" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 上传（新建）弹窗 -->
    <el-dialog v-model="uploadVisible" :title="t('skill.uploadTitle')" width="500">
      <div class="upload-area">
        <p>{{ t("skill.uploadHint") }}</p>
        <label class="btn file-btn">
          <input type="file" accept=".zip,.7z" @change="handleFileChange" />
          {{ t("skill.uploadChoose") }}
        </label>
        <p v-if="uploadFile" class="upload-file-info">{{ t("skill.uploadSelected", { name: uploadFile.name, size: (uploadFile.size / 1024 / 1024).toFixed(1) }) }}</p>
      </div>
      <template #footer>
        <button class="btn" @click="uploadVisible = false">{{ t("common.cancel") }}</button>
        <button class="btn btn-primary" :disabled="uploadLoading" @click="submitUpload">{{ uploadLoading ? t("skill.uploading") : t("skill.uploadSubmit") }}</button>
      </template>
    </el-dialog>

    <!-- README 图标弹窗（按 locale 取存档双语 README；M4：本地模型来源附带性能提示） -->
    <el-dialog v-model="readmeVisible" :title="t('skill.readmeTitle')" width="700">
      <p class="audit-title">{{ readmeSkillName }}</p>
      <div v-if="readmeLoading">{{ t("common.loading") }}</div>
      <template v-else-if="readmeContent">
        <p v-if="readmeGeneratedBy === 'model'" class="genby-hint">{{ t("skill.performanceHint") }}</p>
        <pre class="readme-body">{{ readmeContent }}</pre>
      </template>
      <p v-else>{{ t("skill.readmeEmpty") }}</p>
    </el-dialog>

    <!-- 审核弹窗（仅 admin，仅审核中）：报告 + 推荐结论/README -->
    <el-dialog v-model="reviewVisible" :title="t('common.skillReview')" width="760">
      <div v-if="reviewTarget" class="review-info">
        <p><b>{{ t("common.skillCode") }}:</b> {{ reviewTarget.skill_code }}</p>
        <p><b>{{ t("common.skillName") }}:</b> {{ reviewTarget.skill_name }}</p>
        <p><b>{{ t("skill.reviewAudit") }}</b> {{ auditStatusLabel(reviewTarget.audit_status) }}</p>
        <p><b>{{ t("skill.reviewOrigin") }}</b> {{ originLabel(reviewTarget.origin) }}</p>
        <p v-if="reviewTarget.version"><b>{{ t("skill.reviewVersion") }}</b> {{ reviewTarget.version }}</p>
        <p v-if="reviewTarget.source_format"><b>{{ t("skill.reviewFormat") }}</b> {{ reviewTarget.source_format }}</p>
      </div>
      <div v-if="reviewLoading" class="review-loading">{{ t("common.loading") }}</div>
      <el-tabs v-else class="review-tabs">
        <el-tab-pane :label="t('skill.reviewReportTab')">
          <pre v-if="reviewReport" class="readme-body">{{ reviewReport }}</pre>
          <p v-else>{{ t("skill.reviewReportEmpty") }}</p>
        </el-tab-pane>
        <el-tab-pane :label="t('skill.reviewReadmeTab')">
          <pre v-if="reviewReadme" class="readme-body">{{ reviewReadme }}</pre>
          <p v-else>{{ t("skill.readmeEmpty") }}</p>
        </el-tab-pane>
        <!-- 批次 7.3：文件预览（包内清单 → 点击单文件内容；文本直读 / 二进制 base64 提示） -->
        <el-tab-pane :label="t('skill.filesTab')">
          <div v-if="reviewFilesLoading">{{ t("common.loading") }}</div>
          <template v-else-if="reviewFiles.length">
            <p class="files-hint">{{ t("skill.filesListHint") }}</p>
            <div class="file-list">
              <button v-for="f in reviewFiles" :key="f.path" class="btn btn-sm file-item" @click="previewReviewFile(f.path)">
                <span class="text-mono">{{ f.path }}</span>
                <span class="file-size">{{ (f.size / 1024).toFixed(1) }}KB</span>
              </button>
            </div>
            <template v-if="reviewFileContent">
              <p v-if="reviewFileContent.encoding === 'base64'" class="diff-hint">{{ t("skill.fileBinary") }}</p>
              <pre v-else class="readme-body file-body">{{ reviewFileContent.content }}</pre>
            </template>
          </template>
          <p v-else>{{ t("skill.filesEmpty") }}</p>
        </el-tab-pane>
      </el-tabs>
      <el-input v-model="reviewComment" type="textarea" :rows="3" :placeholder="t('skill.reviewCommentPlaceholder')" style="margin-top: 12px" />
      <template #footer>
        <button class="btn btn-danger" @click="submitReview('reject')">{{ t("skill.reviewReject") }}</button>
        <button v-if="reviewTarget && reviewTarget.plaza_id" class="btn btn-warning" @click="submitReview('merge')">{{ t("skill.reviewMerge") }}</button>
        <button class="btn btn-warning" @click="openMergeWorkbench(reviewTarget)">{{ t("skill.mergeWorkbench") }}</button>
        <button class="btn btn-success" @click="submitReview('approve')">{{ t("skill.reviewApprove") }}</button>
      </template>
    </el-dialog>

    <!-- merge 工作台（设计定稿④，admin）：目标广场选择 → build → 冲突逐文件裁决 → 发布/丢弃（merge_token 供 CC 试用） -->
    <el-dialog v-model="mergeVisible" :title="t('skill.mergeWorkbench')" width="760" :close-on-click-modal="false">
      <p v-if="mergeSource" class="merge-source">
        <b>{{ t("common.skillCode") }}:</b> {{ mergeSource.skill_code }}（{{ mergeSource.skill_name }}）{{ t("skill.mergeSourceHint") }}
      </p>
      <div class="merge-form">
        <label class="merge-label">{{ t("skill.mergeTargetPlaza") }}</label>
        <select class="form-select merge-plaza-select" v-model="mergePlazaId">
          <option :value="null">{{ t("skill.mergeTargetPlaceholder") }}</option>
          <option v-for="p in mergePlazas" :key="p.plaza_id" :value="p.plaza_id">
            {{ p.skill_code }} · {{ p.skill_name }}（v{{ p.version }}）
          </option>
        </select>
        <div class="merge-grid">
          <div>
            <label class="merge-label">{{ t("skill.mergeBaseVersion") }}</label>
            <input type="text" class="form-input" v-model="mergeBaseVersion" :placeholder="t('skill.mergeBaseVersionPh')">
          </div>
          <div>
            <label class="merge-label">{{ t("skill.mergeTargetVersion") }}</label>
            <input type="text" class="form-input" v-model="mergeTargetVersion" :placeholder="t('skill.mergeTargetVersionPh')">
          </div>
        </div>
        <label class="merge-label">{{ t("skill.mergeNote") }}</label>
        <input type="text" class="form-input" v-model="mergeComment" :placeholder="t('skill.reviewCommentPlaceholder')">
        <div class="sheet-actions">
          <button class="btn btn-primary" :disabled="!mergePlazaId || mergeBuilding" @click="buildMerge">
            {{ mergeBuilding ? t("skill.mergeBuilding") : t("skill.mergeBuildAction") }}
          </button>
        </div>
      </div>
      <div v-if="mergeResult" class="merge-result">
        <p class="merge-token">
          <b>{{ t("skill.mergeTokenLabel") }}:</b> <code class="text-mono">{{ mergeResult.merge_token }}</code>
          <span class="tag tag-info">{{ mergeResult.status }}</span>
        </p>
        <p class="diff-hint">{{ t("skill.mergeTrialHint") }}</p>
        <p class="merge-version">
          <b>{{ t("skill.mergeVersionInfo", { base: mergeResult.base_version, next: mergeResult.new_version }) }}</b>
          <span :class="mergeResult.audit_summary?.passed ? 'log-pass' : 'log-fail'">
            {{ mergeResult.audit_summary?.passed ? t("skill.auditPassed") : t("skill.auditFailed") }}
          </span>
          {{ t("skill.mergeAuditCounts", {
            critical: mergeResult.audit_summary?.critical_count ?? 0,
            warning: mergeResult.audit_summary?.warning_count ?? 0,
            suggestion: mergeResult.audit_summary?.suggestion_count ?? 0,
          }) }}
        </p>
        <p v-if="mergeCriticalCount > 0" class="diff-hint">{{ t("skill.mergeBlockedHint") }}</p>
        <p class="sheet-h">{{ t("skill.mergeConflictsTitle") }}</p>
        <template v-if="mergeResult.conflicts?.length">
          <div v-for="c in mergeResult.conflicts" :key="c.path" class="merge-conflict">
            <span class="text-mono">{{ c.path }}</span>
            <select
              class="form-select"
              :value="String(mergeResolutions[c.path] ?? c.default_source_skill_id)"
              @change="onResolutionChange(c, $event)"
            >
              <option v-for="cand in c.candidates" :key="cand.role + (cand.source_skill_id ?? '')" :value="candidateValue(cand)">
                {{ cand.skill_code }}（{{ mergeRoleLabel(cand.role) }}）
              </option>
            </select>
          </div>
        </template>
        <p v-else>{{ t("skill.mergeNoConflicts") }}</p>
      </div>
      <template #footer>
        <button class="btn" @click="mergeVisible = false">{{ t("common.cancel") }}</button>
        <button v-if="mergeResult" class="btn" :disabled="mergeOperating" @click="publishMerge('discard')">{{ t("skill.mergeDiscardAction") }}</button>
        <button v-if="mergeResult" class="btn btn-success" :disabled="mergeOperating || mergeCriticalCount > 0" @click="publishMerge('publish')">
          {{ mergeOperating ? t("skill.mergeOperating") : t("skill.mergePublishAction") }}
        </button>
      </template>
    </el-dialog>

    <!-- 版本审核反馈弹窗（Sheet 审核日志"详情"：该版本双语存档报告按 locale；M4：model 来源提示） -->
    <el-dialog v-model="versionReportVisible" :title="t('skill.versionReportTitle', { version: versionReportName })" width="700">
      <template v-if="versionReportContent">
        <p v-if="versionReportGeneratedBy === 'model'" class="genby-hint">{{ t("skill.performanceHint") }}</p>
        <pre class="readme-body">{{ versionReportContent }}</pre>
      </template>
      <p v-else>{{ t("skill.logEmpty") }}</p>
    </el-dialog>

    <!-- 分享管理 Sheet（owner：分享 / 更新 / 撤回 / 迭代） -->
    <el-drawer v-model="sheetVisible" :title="t('skill.sheetTitle', { name: sheetTarget?.skill_name ?? '' })" size="420">
      <div v-if="sheetTarget" class="sheet-body">
        <p class="sheet-status"><b>{{ t("common.colStatus") }}</b> {{ statusLabel(sheetTarget.status) }}</p>
        <p v-if="sheetTarget.review_comment" class="sheet-comment"><b>{{ t("skill.reviewCommentPlaceholder") }}</b> {{ sheetTarget.review_comment }}</p>

        <!-- 审核日志：逐版本审计反馈（版本 · 日期 · 结论 + 存档报告详情） -->
        <div class="sheet-section">
          <p class="sheet-h">{{ t("skill.logTitle") }}</p>
          <div v-if="sheetLogLoading">{{ t("common.loading") }}</div>
          <template v-else-if="sheetVersions.length">
            <div v-for="v in sheetVersions" :key="v.version" class="log-row">
              <span class="text-mono">v{{ v.version }}</span>
              <span v-if="v.generated_by" class="tag" :class="v.generated_by === 'model' ? 'tag-warning' : 'tag-info'" :title="v.generated_by === 'model' ? t('skill.performanceHint') : ''">{{ generatedByLabel(v.generated_by) }}</span>
              <span>{{ v.created_at ? v.created_at.slice(0, 10) : "-" }}</span>
              <span :class="versionPassed(v) === true ? 'log-pass' : versionPassed(v) === false ? 'log-fail' : ''">
                {{ versionPassed(v) === true ? t("skill.auditPassed") : versionPassed(v) === false ? t("skill.auditFailed") : "-" }}
              </span>
              <button class="btn btn-sm" @click="openVersionReport(v)">{{ t("common.detail") }}</button>
            </div>
          </template>
          <p v-else>{{ t("skill.logEmpty") }}</p>
        </div>

        <!-- M4.3：分享迭代差异描述（本地 vs 广场快照 + 统计 + 性能提示，F-30/M4.4） -->
        <div v-if="sheetTarget.status === 'SHARE_ITERATION'" class="sheet-section">
          <p class="sheet-h">{{ t("skill.diffTitle") }}</p>
          <div v-if="iterationDiffLoading">{{ t("common.loading") }}</div>
          <template v-else-if="iterationDiff">
            <p class="diff-desc">{{ diffDescription }}</p>
            <p class="diff-stats">
              {{ t("skill.diffStats", { added: iterationDiff.added_lines, removed: iterationDiff.removed_lines, local: iterationDiff.local_lines, plaza: iterationDiff.plaza_lines }) }}
              · {{ t("skill.diffSimilarity", { sim: (iterationDiff.similarity * 100).toFixed(1) + "%" }) }}
              <span class="tag" :class="iterationDiff.generated_by === 'model' ? 'tag-warning' : 'tag-info'">{{ generatedByLabel(iterationDiff.generated_by) }}</span>
            </p>
            <p v-if="diffHint" class="diff-hint">{{ diffHint }}</p>
            <div v-if="iterationDiff.unified_diff && !iterationDiff.identical" class="diff-details">
              <button class="btn btn-sm" @click="diffExpanded = !diffExpanded">{{ t("skill.diffDetail") }}</button>
              <pre v-if="diffExpanded" class="diff-body">{{ iterationDiff.unified_diff }}</pre>
            </div>
          </template>
          <p v-else>{{ t("skill.diffEmpty") }}</p>
        </div>

        <!-- 设计定稿②：新版 README 预览（广场发布口径，迭代决策依据） -->
        <div v-if="sheetTarget.status === 'SHARE_ITERATION'" class="sheet-section">
          <p class="sheet-h">{{ t("skill.newReadmeTitle") }}</p>
          <div v-if="plazaReadmeLoading">{{ t("common.loading") }}</div>
          <pre v-else-if="plazaReadme" class="readme-body readme-preview">{{ plazaReadme }}</pre>
          <p v-else>{{ t("skill.newReadmeEmpty") }}</p>
        </div>

        <!-- 分享迭代：迭代（覆盖本地）/ 忽略本次迭代 -->
        <div v-if="sheetTarget.status === 'SHARE_ITERATION'" class="sheet-section">
          <p class="sheet-hint">{{ t("skill.resolveHint") }}</p>
          <div class="sheet-actions">
            <button class="btn btn-primary" :disabled="sheetLoading" @click="resolveIteration('iterate')">{{ t("skill.resolveIterate") }}</button>
            <button class="btn" :disabled="sheetLoading" @click="resolveIteration('keep')">{{ t("skill.resolveKeep") }}</button>
          </div>
        </div>

        <!-- 审核中：撤回 -->
        <div v-else-if="sheetTarget.status === 'PENDING_REVIEW'" class="sheet-section">
          <div class="sheet-actions">
            <button class="btn btn-warning" :disabled="sheetLoading" @click="withdrawShare">{{ t("skill.withdrawAction") }}</button>
          </div>
        </div>

        <!-- 其余状态：提交分享（DRAFT/ENABLED/DISABLED，含 F-31 重复分享确认）/ 恢复草稿（WITHDRAWN/REJECTED，免重传包） -->
        <div v-else class="sheet-section">
          <div class="sheet-actions">
            <button v-if="['DRAFT', 'ENABLED', 'DISABLED'].includes(sheetTarget.status)" class="btn btn-success" :disabled="sheetLoading" @click="submitShare">{{ t("skill.shareAction") }}</button>
            <button v-else class="btn" :disabled="sheetLoading" @click="toDraft">{{ t("skill.toDraftAction") }}</button>
          </div>
        </div>

        <!-- 重命名（批次 6.1：owner 稳定态改编码，磁盘目录同步改名） -->
        <div v-if="canRename(sheetTarget)" class="sheet-section">
          <p class="sheet-h">{{ t("skill.renameHint") }}</p>
          <input type="text" class="form-input" v-model="renameCode" :placeholder="t('skill.renamePlaceholder')">
          <div class="sheet-actions">
            <button class="btn btn-primary" :disabled="renaming" @click="submitRename">{{ t("skill.renameAction") }}</button>
          </div>
        </div>

        <!-- 更新（重新上传同编码包） -->
        <div class="sheet-section sheet-update">
          <p class="sheet-hint">{{ t("skill.updateHint") }}</p>
          <input type="file" accept=".zip,.7z" @change="handleUpdateFileChange" />
          <p v-if="updateFile" class="upload-file-info">{{ updateFile.name }}</p>
          <div class="sheet-actions">
            <button class="btn btn-primary" :disabled="sheetLoading" @click="submitUpdate">{{ t("skill.updateAction") }}</button>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.review-info p { margin: 4px 0; }
.review-loading { padding: 12px 0; color: #666; }
.upload-area { display: flex; flex-direction: column; align-items: center; padding: 20px 0; }
.upload-area p { margin: 8px 0; color: #666; }
/* 文件选择行：原生 file input 固有宽度含右侧保留空白（Chromium 实测 253px，可见内容仅 ~175px），
   盒子居中≠可见内容居中；fit-content / min-content / text-align / input 自身 flex 均无法消除保留宽度（20260908 实测）。
   故视觉隐藏原生 input、以 label 复用全局 .btn 样式承载点击区（选择结果仍由下方 upload-file-info 展示），
   行宽即按钮宽，外层 align-items:center 对可见内容真实居中 */
.file-btn { position: relative; margin: 8px 0; }
.file-btn input[type="file"] { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
.upload-file-info { color: #409eff; font-weight: 500; }
.audit-title { font-weight: 600; font-size: 15px; margin-bottom: 12px; }
.readme-body { white-space: pre-wrap; word-break: break-word; background: #f7f8fa; border-radius: 6px; padding: 12px; max-height: 360px; overflow: auto; font-size: 13px; line-height: 1.6; }
.sheet-body { padding: 0 4px; }
.sheet-status { margin: 4px 0 12px; }
.sheet-comment { margin: 4px 0 12px; color: #e6a23c; }
.sheet-section { border-top: 1px solid #ebeef5; padding: 16px 0; }
.sheet-update { }
.sheet-hint { color: #666; font-size: 13px; margin: 0 0 10px; }
.sheet-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.log-row { display: flex; gap: 10px; align-items: center; padding: 4px 0; font-size: 13px; }
.log-pass { color: #67c23a; }
.log-fail { color: #f56c6c; }
.genby-hint { color: #e6a23c; font-size: 13px; margin: 0 0 10px; }
.diff-desc { margin: 0 0 8px; font-size: 13px; line-height: 1.6; }
.diff-stats { margin: 0 0 8px; color: #666; font-size: 13px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.diff-hint { color: #e6a23c; font-size: 13px; margin: 0 0 8px; }
.diff-body { white-space: pre-wrap; word-break: break-word; background: #f7f8fa; border-radius: 6px; padding: 10px; max-height: 260px; overflow: auto; font-size: 12px; line-height: 1.5; margin-top: 8px; }
.diff-details { margin-top: 4px; }
.readme-preview { max-height: 200px; font-size: 12px; }
.merge-source { margin: 0 0 10px; }
.merge-form { display: flex; flex-direction: column; gap: 6px; }
.merge-label { font-size: 13px; color: #666; margin-top: 6px; }
.merge-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.merge-result { border-top: 1px solid #ebeef5; margin-top: 14px; padding-top: 12px; }
.merge-token { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0 0 8px; }
.merge-version { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13px; }
.merge-conflict { display: flex; gap: 10px; align-items: center; padding: 6px 0; font-size: 13px; flex-wrap: wrap; }
.merge-conflict .form-select { width: auto; min-width: 220px; }
.merge-conflict .text-mono { word-break: break-all; }
/* 批次 7：待审同名比对行 + 审核弹窗文件预览 */
.nm-row { display: flex; gap: 6px; align-items: center; padding: 2px 0; font-size: 12px; flex-wrap: wrap; }
.files-hint { color: #666; font-size: 13px; margin: 0 0 8px; }
.file-list { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; margin-bottom: 12px; max-height: 220px; overflow: auto; }
.file-item { display: inline-flex; gap: 8px; align-items: center; }
.file-size { color: #999; font-size: 12px; }
.file-body { margin-top: 4px; }
</style>
