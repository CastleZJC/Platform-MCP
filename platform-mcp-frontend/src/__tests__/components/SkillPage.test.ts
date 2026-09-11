/**
 * 5.5.3 组件测试 — SkillPage（P1-1 / V3.0 M2.7 增强 + 反馈批次：删审计列/Sheet 审核日志）
 * 覆盖：渲染、8 状态标签、角色/归属门控、README 弹窗、分享管理 Sheet（逐版本审核日志 + 反馈详情）、
 *       审核弹窗（审核报告 / README 双 Tab，均读取版本存档）
 *
 * 说明：ElementPlus 弹窗/抽屉内容经 VTU 挂在 wrapper 组件树内（与 DatasourcePage 测试一致），
 * 故弹窗按钮/文本经 wrapper.findAll / wrapper.text() 断言；document.body 仅承载 ElMessage 提示。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import ElementPlus from "element-plus"
import SkillPage from "@/views/skill/SkillPage.vue"
import { useUserStore } from "@/stores/user"
import type { PendingSkill, Skill, SkillVersion } from "@/types"

vi.mock("@/utils/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

import request from "@/utils/request"

const mockVersion: SkillVersion = {
  version: "1.0.0",
  checksum: "abc123",
  generated_by: "template",
  readme_zh: "# 中文说明",
  readme_en: "# English README",
  report_zh: "审核报告：与广场无相似，推荐新增",
  report_en: "report: no similar, recommend new",
  audit_snapshot: { passed: true },
  created_at: "2026-01-05T00:00:00Z",
}

const enabledSkill: Skill = {
  id: 1,
  skill_code: "database",
  skill_name: "Database Skill",
  description: "SQL execution",
  status: "ENABLED",
  tool_count: 5,
  register_method: "decorator",
  submitted_by: "admin",
  source_format: null,
  version: "1.0.0",
  audit_status: "passed",
  readme_generated: false,
  created_at: "2026-01-01T00:00:00Z",
  share_status: "private",
  origin: "ORIGINAL",
}

const pendingSkill: Skill = {
  id: 2,
  skill_code: "pending_skill",
  skill_name: "Pending Skill",
  description: "Pending review",
  status: "PENDING_REVIEW",
  tool_count: 2,
  register_method: "decorator",
  submitted_by: "dev01",
  source_format: "zip",
  version: "1.0.0",
  audit_status: "pending",
  readme_generated: true,
  created_at: "2026-01-02T00:00:00Z",
  share_status: "private",
  origin: "PLAZA",
}

// 批次 7：待审提交视图模型（GET /skills/pending）+ 同名比对裁决素材（设计定稿⑪）
const mockPending: PendingSkill = {
  id: 9,
  skill_code: "oracle-backup",
  skill_name: "Oracle 备份",
  description: "备份工具",
  status: "PENDING_REVIEW",
  register_method: "mcp",
  submitted_by: "dev02",
  created_at: "2026-01-06T10:20:30Z",
  version: "1.2.0",
  origin: "ORIGINAL",
  plaza_id: null,
  audit_status: "pending",
  review_comment: null,
  name_match: [
    { plaza_id: 5, skill_code: "oracle-backup", skill_name: "Oracle 备份", version: "1.1.0", similarity: 0.87, same_name: true, verdict: "merge" },
    { plaza_id: 6, skill_code: "mysql-backup", skill_name: "MySQL 备份", version: "2.0.0", similarity: 0.62, same_name: false, verdict: "merge_candidate" },
  ],
}

// 按 URL 路由的 GET mock：list / versions / iteration-diff（M4）
const mockDiff = {
  unified_diff: "--- local/SKILL.md\n+++ plaza/SKILL.md\n@@ -1 +1 @@\n-# local\n+# plaza",
  local_lines: 3,
  plaza_lines: 4,
  added_lines: 2,
  removed_lines: 1,
  identical: false,
  similarity: 0.87,
  description_zh: "存在行级差异：新增 2 行",
  description_en: "differs: +2 lines",
  generated_by: "template",
  performance_hint_zh: null,
  performance_hint_en: null,
}

// merge 工作台目标广场候选（设计定稿④：openMergeWorkbench 拉取 GET /plaza）
const mockPlazaItem = {
  plaza_id: 10,
  skill_code: "tool-a",
  skill_name: "Tool A",
  description: "plaza a",
  version: "1.0.0",
  involve_flags: [] as string[],
  iteration_note: null,
  status: "PUBLISHED",
  uploader: null,
  created_at: null,
  updated_at: null,
}

function routeGet(items: Skill[]) {
  const mockedGet = request.get as ReturnType<typeof vi.fn>
  mockedGet.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
    if (typeof url === "string" && url.endsWith("/versions")) {
      return Promise.resolve({ data: { skill_id: 1, skill_code: "x", current_version: "1.0.0", versions: [mockVersion] } })
    }
    if (typeof url === "string" && url.endsWith("/iteration-diff")) {
      return Promise.resolve({ data: mockDiff })
    }
    if (typeof url === "string" && url.endsWith("/readme")) {
      // 设计定稿②：迭代态新版 README 预览（GET /plaza/{id}/readme）
      return Promise.resolve({ data: { readme_zh: "# 广场新版 README", readme_en: "# Plaza new README" } })
    }
    if (typeof url === "string" && url === "/plaza") {
      return Promise.resolve({ data: { items: [mockPlazaItem], total: 1 } })
    }
    if (typeof url === "string" && url === "/skills/pending") {
      // 批次 7：待审提交列表（admin 审核工作台，独立分页）
      return Promise.resolve({ data: { items: [mockPending], total: 1, page: 1, page_size: 20 } })
    }
    if (typeof url === "string" && url.endsWith("/files")) {
      // 批次 7.3：审核文件预览（无 path 清单 / 带 path 单文件内容）
      if (config?.params?.path) {
        return Promise.resolve({ data: { path: "SKILL.md", size: 512, sha256: "a".repeat(64), encoding: "utf-8", content: "# 待审包正文" } })
      }
      return Promise.resolve({ data: { skill_id: 2, skill_code: "pending_skill", files: [{ path: "SKILL.md", size: 512 }] } })
    }
    return Promise.resolve({ data: { items, total: items.length } })
  })
  return mockedGet
}

function btnByText(wrapper: VueWrapper, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text))
}

// 精确匹配按钮文本（设计②后「迭代」为「忽略本次迭代」前缀，includes 会先命中前者）
function btnExact(wrapper: VueWrapper, text: string) {
  return wrapper.findAll("button").find((b) => b.text() === text)
}

describe("SkillPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountAs(role: "admin" | "developer", username: string, items: Skill[] = []) {
    routeGet(items)
    const store = useUserStore()
    store.$patch({ user: { id: 1, username, nickname: null, email: null, role_code: role, api_key_prefix: null, status: 1, locale: "zh-CN" } })
    const wrapper = mount(SkillPage, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    return wrapper
  }

  it("renders page header and toolbar", async () => {
    const wrapper = await mountAs("admin", "admin")
    expect(wrapper.find(".page-header h2").text()).toBe("Skill 管理")
    expect(wrapper.find(".search-input").exists()).toBe(true)
    expect(wrapper.find("button.btn-primary").text()).toContain("上传 Skill")
  })

  it("renders skill list and maps 8-state labels", async () => {
    const draft: Skill = { ...enabledSkill, id: 3, status: "DRAFT", skill_code: "draft_skill" }
    const wrapper = await mountAs("admin", "admin", [enabledSkill, draft])
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("已启用")
    expect(rows[1].text()).toContain("草稿")
  })

  it("query button triggers fetchSkills", async () => {
    const wrapper = await mountAs("admin", "admin")
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const before = mockedGet.mock.calls.length
    await wrapper.find("button.btn:not(.btn-primary)").trigger("click")
    await flushPromises()
    expect(mockedGet.mock.calls.length).toBeGreaterThan(before)
  })

  it("admin sees disable button on ENABLED and enable on DISABLED", async () => {
    const wrapper = await mountAs("admin", "root", [enabledSkill])
    expect(wrapper.find("tbody tr td.actions").text()).toContain("停用")
    const wrapper2 = await mountAs("admin", "root", [{ ...enabledSkill, status: "DISABLED" }])
    expect(wrapper2.find("tbody tr td.actions").text()).toContain("启用")
  })

  it("admin sees review button only on PENDING_REVIEW", async () => {
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    expect(wrapper.find("tbody tr td.actions").text()).toContain("审核")
    const wrapper2 = await mountAs("admin", "root", [enabledSkill])
    expect(wrapper2.find("tbody tr td.actions").text()).not.toContain("审核")
  })

  it("non-admin does not see review/disable buttons", async () => {
    const wrapper = await mountAs("developer", "root", [pendingSkill, enabledSkill])
    const actions = wrapper.findAll("tbody tr td.actions").map((c) => c.text()).join("|")
    expect(actions).not.toContain("审核")
    expect(actions).not.toContain("停用")
  })

  it("owner sees 分享管理 button; non-owner does not", async () => {
    const wrapper = await mountAs("developer", "dev01", [pendingSkill])
    expect(wrapper.find("tbody tr td.actions").text()).toContain("分享管理")
    const wrapper2 = await mountAs("developer", "other", [pendingSkill])
    expect(wrapper2.find("tbody tr td.actions").text()).not.toContain("分享管理")
  })

  it("disable skill calls PUT and refetches", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedPut.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("admin", "root", [enabledSkill])
    await wrapper.find("tbody tr td.actions button.btn-danger").trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/skills/1/status", { status: "DISABLED" })
  })

  it("RM button fetches versions and shows locale README", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", "root", [enabledSkill])
    await btnByText(wrapper, "RM")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/skills/1/versions")
    expect(wrapper.text()).toContain("中文说明")
  })

  it("skill list has no audit column (feedback: audit log moved into share sheet)", async () => {
    const wrapper = await mountAs("admin", "root", [enabledSkill])
    expect(wrapper.find("table thead").text()).not.toContain("审计")
  })

  it("share sheet shows per-version audit log and report detail", async () => {
    const wrapper = await mountAs("developer", "dev01", [pendingSkill])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    // 日志行：v1.0.0 · 日期 · 结论（audit_snapshot.passed → 通过）
    expect(wrapper.text()).toContain("审核日志")
    expect(wrapper.text()).toContain("v1.0.0")
    expect(wrapper.text()).toContain("2026-01-05")
    expect(wrapper.text()).toContain("通过")
    // 详情 → 该版本双语存档报告（按 locale 取中文）
    await btnByText(wrapper, "详情")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("审核报告：与广场无相似，推荐新增")
  })

  it("owner submit share posts /submit (no reshare confirm for private DRAFT)", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const draft: Skill = { ...enabledSkill, id: 4, status: "DRAFT", submitted_by: "dev01", share_status: "private" }
    const wrapper = await mountAs("developer", "dev01", [draft])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "提交分享")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/4/submit", { confirm_reshare: false })
  })

  it("owner withdraw posts /withdraw for PENDING_REVIEW", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("developer", "dev01", [pendingSkill])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "撤回审核")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/2/withdraw")
  })

  it("owner restore-to-draft posts /restore for WITHDRAWN (no file re-upload)", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const withdrawn: Skill = { ...pendingSkill, id: 6, status: "WITHDRAWN", submitted_by: "dev01" }
    const wrapper = await mountAs("developer", "dev01", [withdrawn])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "恢复为草稿")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/6/restore")
  })

  it("owner restore-to-draft posts /revise for REJECTED", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const rejected: Skill = { ...pendingSkill, id: 7, status: "REJECTED", submitted_by: "dev01" }
    const wrapper = await mountAs("developer", "dev01", [rejected])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "恢复为草稿")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/7/revise")
  })

  it("owner resolve iteration posts /resolve-iteration with choice", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const iter: Skill = { ...pendingSkill, id: 5, status: "SHARE_ITERATION", submitted_by: "dev01" }
    const wrapper = await mountAs("developer", "dev01", [iter])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    // 设计定稿②：「采纳合并」→「迭代」（文案改版，语义仍为内容级采纳）
    await btnExact(wrapper, "迭代")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/5/resolve-iteration", { choice: "iterate" })
  })

  it("设计②: 迭代态 Sheet 展示新版 README 预览与忽略按钮", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const iter: Skill = { ...pendingSkill, id: 5, status: "SHARE_ITERATION", submitted_by: "dev01", plaza_id: 55 }
    const wrapper = await mountAs("developer", "dev01", [iter])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    // 新版 README 预览（GET /plaza/{id}/readme，按 locale 取中文）
    expect(wrapper.text()).toContain("新版 README 预览（广场）")
    expect(wrapper.text()).toContain("# 广场新版 README")
    // 覆盖警示文案 +「忽略本次迭代」按钮
    expect(wrapper.text()).toContain("忽略本次迭代")
    await btnByText(wrapper, "忽略本次迭代")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/5/resolve-iteration", { choice: "keep" })
  })

  it("M4: iteration sheet fetches /iteration-diff and renders description with stats", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const iter: Skill = { ...pendingSkill, id: 5, status: "SHARE_ITERATION", submitted_by: "dev01" }
    const wrapper = await mountAs("developer", "dev01", [iter])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/skills/5/iteration-diff")
    // 差异描述 + 统计 + 来源标签（template：无性能提示）
    expect(wrapper.text()).toContain("存在行级差异：新增 2 行")
    expect(wrapper.text()).toContain("新增 +2 行 / 删除 -1 行")
    expect(wrapper.text()).toContain("语义相似度 87.0%")
    expect(wrapper.text()).toContain("模板生成")
    expect(wrapper.text()).not.toContain("性能有限")
    // 展开差异明细（unified diff）
    await btnByText(wrapper, "差异明细")!.trigger("click")
    await flushPromises()
    expect(wrapper.find(".diff-body").text()).toContain("# plaza")
  })

  it("M4: iteration diff generated_by=model shows performance hint", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const iter: Skill = { ...pendingSkill, id: 5, status: "SHARE_ITERATION", submitted_by: "dev01" }
    const wrapper = await mountAs("developer", "dev01", [iter])
    // mountAs 内 routeGet 会重置 mock：点击打开 Sheet 前覆盖为 model 版本
    mockedGet.mockImplementation((url: string) => {
      if (typeof url === "string" && url.endsWith("/iteration-diff")) {
        return Promise.resolve({
          data: {
            ...mockDiff,
            description_zh: "模型摘要",
            generated_by: "model",
            performance_hint_zh: "本地模型生成，性能有限，建议使用外部大模型（CC+MCP 通道）",
          },
        })
      }
      if (typeof url === "string" && url.endsWith("/versions")) {
        return Promise.resolve({ data: { skill_id: 1, skill_code: "x", current_version: "1.0.0", versions: [mockVersion] } })
      }
      return Promise.resolve({ data: { items: [], total: 0 } })
    })
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("模型摘要")
    expect(wrapper.text()).toContain("本地模型生成")
    expect(wrapper.find(".diff-hint").text()).toContain("性能有限")
  })

  it("M4: version rows show generated_by tag", async () => {
    const wrapper = await mountAs("developer", "dev01", [pendingSkill])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    // mockVersion.generated_by = "template" → 模板生成标签
    expect(wrapper.find(".log-row").text()).toContain("模板生成")
  })

  it("M4: README dialog shows performance hint when generated_by=model", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", "root", [enabledSkill])
    // mountAs 内 routeGet 会重置 mock：点击 RM 前覆盖为 model 版本存档
    mockedGet.mockImplementation((url: string) => {
      if (typeof url === "string" && url.endsWith("/versions")) {
        return Promise.resolve({
          data: {
            skill_id: 1,
            skill_code: "x",
            current_version: "1.0.0",
            versions: [{ ...mockVersion, generated_by: "model" }],
          },
        })
      }
      return Promise.resolve({ data: { items: [], total: 0 } })
    })
    await btnByText(wrapper, "RM")!.trigger("click")
    await flushPromises()
    expect(wrapper.find(".genby-hint").text()).toContain("性能有限")
  })

  it("admin review dialog loads archived report/readme and approve posts /review", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    // 双 Tab 均读版本存档：审核报告 = report_zh；README = readme_zh（el-tab-pane 非懒渲染，两 Tab 文本同在树内）
    expect(wrapper.text()).toContain("审核报告：与广场无相似，推荐新增")
    expect(wrapper.text()).toContain("# 中文说明")
    await btnByText(wrapper, "通过")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/2/review", { action: "approve", comment: "" })
  })

  it("场景①: review dialog shows merge workbench for original skill without plaza link", async () => {
    const original: Skill = { ...pendingSkill, origin: "ORIGINAL" }
    const wrapper = await mountAs("admin", "root", [original])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    // 设计定稿④：工作台入口对原创开放（废除 origin=PLAZA 限制）；无关联广场 → 快捷合并不出现
    expect(btnByText(wrapper, "合并工作台")).toBeTruthy()
    expect(btnByText(wrapper, "合并到广场")).toBeFalsy()
  })

  it("linked plaza copy shows quick merge and workbench", async () => {
    const linked: Skill = { ...pendingSkill, origin: "PLAZA", plaza_id: 10 }
    const wrapper = await mountAs("admin", "root", [linked])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    expect(btnByText(wrapper, "合并到广场")).toBeTruthy()
    expect(btnByText(wrapper, "合并工作台")).toBeTruthy()
  })

  it("merge workbench: build renders token/conflicts and publish posts resolutions", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    const buildData = {
      merge_token: "tok9",
      plaza_id: 10,
      source_skills: [{ skill_id: 2, skill_code: "pending_skill", skill_name: "Pending Skill", role: "primary", version: "1.0.0", submitted_by: "dev01" }],
      base_version: "1.0.0（当前）",
      new_version: "1.0.1",
      conflicts: [{
        path: "SKILL.md",
        candidates: [
          { source_skill_id: 2, skill_code: "pending_skill", role: "primary", sha256: "a", size: 10 },
          { source_skill_id: null, skill_code: "tool-a", role: "base", sha256: "b", size: 9 },
        ],
        default_source_skill_id: 2,
        resolution: null,
      }],
      audit_summary: { passed: true, critical_count: 0, warning_count: 0, suggestion_count: 0 },
      snapshot_path: "/tmp/x",
      status: "BUILT",
    }
    mockedPost.mockImplementation((url: string) => {
      if (url === "/plaza/merge/build") return Promise.resolve({ data: buildData })
      if (url === "/plaza/merge/tok9/publish") {
        return Promise.resolve({ data: { status: "PUBLISHED", new_version: "1.0.1", holders_marked: 1 } })
      }
      return Promise.resolve({ data: {} })
    })
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "合并工作台")!.trigger("click")
    await flushPromises()
    // 打开即拉取目标广场候选清单
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    expect(mockedGet).toHaveBeenCalledWith("/plaza", { params: { page: 1, page_size: 100 } })
    // 选择目标广场 → 构建（源 = 待审 Skill）
    await wrapper.find("select.merge-plaza-select").setValue("10")
    await btnByText(wrapper, "构建合并临时包")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/merge/build", expect.objectContaining({
      plaza_id: 10, source_skill_ids: [2],
    }))
    // 临时包信息：试用 token + 试用引导 + 冲突清单（默认主源裁决）
    expect(wrapper.text()).toContain("tok9")
    expect(wrapper.text()).toContain("get_skill_file(merge_token=")
    expect(wrapper.text()).toContain("SKILL.md")
    expect(wrapper.text()).toContain("基线 1.0.0（当前） → 新版 1.0.1")
    // 冲突改判 base 后发布
    await wrapper.find(".merge-conflict select").setValue("base")
    await btnByText(wrapper, "发布合并")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/merge/tok9/publish", expect.objectContaining({
      action: "publish", resolutions: { "SKILL.md": "base" },
    }))
  })

  it("merge workbench: discard drops temp package", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockImplementation((url: string) => {
      if (url === "/plaza/merge/build") {
        return Promise.resolve({
          data: {
            merge_token: "tok9", plaza_id: 10, source_skills: [], base_version: "1.0.0（当前）",
            new_version: "1.0.1", conflicts: null,
            audit_summary: { passed: true, critical_count: 0, warning_count: 0, suggestion_count: 0 },
            status: "BUILT",
          },
        })
      }
      if (url === "/plaza/merge/tok9/publish") {
        return Promise.resolve({ data: { status: "DISCARDED" } })
      }
      return Promise.resolve({ data: {} })
    })
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "合并工作台")!.trigger("click")
    await flushPromises()
    await wrapper.find("select.merge-plaza-select").setValue("10")
    await btnByText(wrapper, "构建合并临时包")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "丢弃")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/merge/tok9/publish", expect.objectContaining({
      action: "discard",
    }))
  })

  it("upload dialog: file-select row uses label-wrapped custom button (centering fix)", async () => {
    const wrapper = await mountAs("admin", "root", [])
    await btnByText(wrapper, "上传 Skill")!.trigger("click")
    await flushPromises()
    // 原生 file input 固有宽度含保留空白，盒子居中≠可见内容居中：
    // 以隐藏 input + label（复用 .btn 样式）承载，行宽即按钮宽，外层 align-items:center 真实居中
    const label = wrapper.find(".upload-area .file-btn")
    expect(label.exists()).toBe(true)
    expect(label.text()).toContain("选择文件")
    const input = label.find("input[type=file]")
    expect(input.attributes("accept")).toBe(".zip,.7z")
  })

  // ===== 批次 6.1/6.3：个人库重命名 + owner 启停（状态机通道）=====

  it("批次6.1: owner 稳定态个人 Skill 分享管理含重命名区，提交 PUT /skills/{id}", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedPut.mockResolvedValue({ data: {} })
    const draft: Skill = { ...enabledSkill, id: 4, status: "DRAFT", skill_code: "draft_skill", submitted_by: "dev01", register_method: "upload" }
    const wrapper = await mountAs("developer", "dev01", [draft])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("重命名将同步修改编码与磁盘目录")
    const renameInput = wrapper.find("input.form-input")
    expect(renameInput.exists()).toBe(true)
    await renameInput.setValue("demo-v2")
    await btnExact(wrapper, "重命名")!.trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/skills/4", { skill_code: "demo-v2" })
  })

  it("批次6.1: 新编码为空仅告警不提交", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    const draft: Skill = { ...enabledSkill, id: 4, status: "DRAFT", submitted_by: "dev01", register_method: "upload" }
    const wrapper = await mountAs("developer", "dev01", [draft])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    await btnExact(wrapper, "重命名")!.trigger("click")
    await flushPromises()
    expect(mockedPut).not.toHaveBeenCalled()
  })

  it("批次6.1: 过渡态（含装饰器）与广场关联不渲染重命名区", async () => {
    // PENDING_REVIEW 过渡态 + decorator 内置：先撤回方可重命名
    const wrapper = await mountAs("developer", "dev01", [pendingSkill])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).not.toContain("重命名将同步修改编码与磁盘目录")

    // 广场关联（origin=PLAZA / plaza_id 非空，稳定态 WITHDRAWN 仍禁改编码）
    const linked: Skill = { ...pendingSkill, id: 5, status: "WITHDRAWN", origin: "PLAZA", plaza_id: 55 }
    const wrapper2 = await mountAs("developer", "dev01", [linked])
    await btnByText(wrapper2, "分享管理")!.trigger("click")
    await flushPromises()
    expect(wrapper2.text()).not.toContain("重命名将同步修改编码与磁盘目录")
  })

  it("批次6.3: owner 可停用个人 Skill（启停经状态机通道）", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedPut.mockResolvedValue({ data: {} })
    const own: Skill = { ...enabledSkill, id: 4, skill_code: "my_own", submitted_by: "dev01", register_method: "upload" }
    const wrapper = await mountAs("developer", "dev01", [own])
    const actions = wrapper.find("tbody tr td.actions")
    expect(actions.text()).toContain("停用")
    await actions.find("button.btn-danger").trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/skills/4/status", { status: "DISABLED" })
  })

  it("批次6.3: 非本人个人 Skill 与广场复制行 dev 无启停按钮", async () => {
    const others: Skill = { ...enabledSkill, id: 5, skill_code: "other_personal", submitted_by: "dev02", register_method: "upload" }
    const plazaCopy: Skill = { ...enabledSkill, id: 6, skill_code: "copied", submitted_by: "dev01", register_method: "copy", origin: "PLAZA", plaza_id: 10 }
    const wrapper = await mountAs("developer", "dev01", [others, plazaCopy])
    const actions = wrapper.findAll("tbody tr td.actions").map((c) => c.text()).join("|")
    expect(actions).not.toContain("停用")
  })

  it("批次6.3: admin 可启停广场复制行", async () => {
    const plazaCopy: Skill = { ...enabledSkill, id: 6, skill_code: "copied", register_method: "copy", origin: "PLAZA", plaza_id: 10 }
    const wrapper = await mountAs("admin", "root", [plazaCopy])
    expect(wrapper.find("tbody tr td.actions").text()).toContain("停用")
  })

  // ===== 批次 7.2/7.3：双视图（我的 Skill / 待审提交 admin）+ 审核弹窗文件预览 =====

  it("批次7: admin 双页签渲染，待审页签 lazy 首次激活拉取 /skills/pending", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", "root", [])
    const tabs = wrapper.findAll(".el-tabs__item").map((t) => t.text())
    expect(tabs).toEqual(["我的 Skill", "待审提交"])
    // lazy：未激活前不拉取待审列表
    expect(mockedGet.mock.calls.some((c) => c[0] === "/skills/pending")).toBe(false)
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/skills/pending", { params: { page: 1, page_size: 20 } })
  })

  it("批次7: 非 admin 仅我的 Skill 单页签", async () => {
    const wrapper = await mountAs("developer", "dev01", [])
    expect(wrapper.findAll(".el-tabs__item").map((t) => t.text())).toEqual(["我的 Skill"])
  })

  it("批次7: 待审表格渲染提交人/通道/版本与同名比对裁决", async () => {
    const wrapper = await mountAs("admin", "root", [])
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    const table = wrapper.findAll("table")[1]
    expect(table.find("thead").text()).toContain("提交人")
    expect(table.find("thead").text()).toContain("通道")
    expect(table.find("thead").text()).toContain("同名比对")
    const row = table.find("tbody tr")
    expect(row.text()).toContain("dev02")
    expect(row.text()).toContain("MCP")
    expect(row.text()).toContain("v1.2.0")
    expect(row.text()).toContain("同名+功能似：建议合并")
    expect(row.text()).toContain("名异+功能似：合并候选")
    expect(row.text()).toContain("87.0%")
    expect(row.find("td.actions").text()).toContain("审核")
  })

  it("批次7.3: 审核弹窗文件预览——清单点击单文件下发内容", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", "root", [])
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    await wrapper.findAll("table")[1].find("tbody tr td.actions button").trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/skills/9/files")
    expect(wrapper.text()).toContain("文件预览")
    expect(wrapper.text()).toContain("点击文件查看内容")
    await wrapper.find(".file-list .file-item").trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/skills/9/files", { params: { path: "SKILL.md" } })
    expect(wrapper.find(".file-body").text()).toContain("# 待审包正文")
  })
})
