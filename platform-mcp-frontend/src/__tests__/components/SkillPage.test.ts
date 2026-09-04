/**
 * 5.5.3 组件测试 — SkillPage（P1-1 / V3.0 M2.7 增强）
 * 覆盖：渲染、8 状态标签、角色/归属门控、README 弹窗、分享管理 Sheet、审核弹窗（报告+推荐+README）、
 *       审计报告读取 data.reports（回归修复：此前误读 data.rules 致弹窗恒空）
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
import type { Skill, SkillVersion, SkillAuditRule } from "@/types"

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
  audit_snapshot: null,
  created_at: null,
}

const mockRule: SkillAuditRule = {
  rule_id: "R-SECRET",
  severity: "critical",
  file_path: "a.py",
  line_number: 3,
  description: "硬编码密钥",
  suggestion: "移除",
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

// 按 URL 路由的 GET mock：list / versions / audit-report
function routeGet(items: Skill[]) {
  const mockedGet = request.get as ReturnType<typeof vi.fn>
  mockedGet.mockImplementation((url: string) => {
    if (typeof url === "string" && url.endsWith("/versions")) {
      return Promise.resolve({ data: { skill_id: 1, skill_code: "x", current_version: "1.0.0", versions: [mockVersion] } })
    }
    if (typeof url === "string" && url.endsWith("/audit-report")) {
      return Promise.resolve({ data: { skill_id: 1, skill_code: "x", audit_status: "passed", audit_summary: null, reports: [mockRule] } })
    }
    return Promise.resolve({ data: { items, total: items.length } })
  })
  return mockedGet
}

function btnByText(wrapper: VueWrapper, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text))
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

  it("audit detail dialog reads data.reports (regression: was data.rules)", async () => {
    const wrapper = await mountAs("admin", "root", [enabledSkill])
    // 审计列的“详情”按钮（el-button link）
    const detailBtn = wrapper.findAll("tbody tr td .el-button").find((b) => b.text().includes("详情"))!
    await detailBtn.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("R-SECRET")
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

  it("owner resolve iteration posts /resolve-iteration with choice", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const iter: Skill = { ...pendingSkill, id: 5, status: "SHARE_ITERATION", submitted_by: "dev01" }
    const wrapper = await mountAs("developer", "dev01", [iter])
    await btnByText(wrapper, "分享管理")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "采纳合并")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/5/resolve-iteration", { choice: "iterate" })
  })

  it("admin review dialog loads report+versions and approve posts /review", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    // 报告 tab 展示 rule_id（来自 data.reports）
    expect(wrapper.text()).toContain("R-SECRET")
    await btnByText(wrapper, "通过")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/2/review", { action: "approve", comment: "" })
  })

  it("admin review dialog shows merge button for origin=PLAZA", async () => {
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    expect(btnByText(wrapper, "合并到广场")).toBeTruthy()
  })
})
