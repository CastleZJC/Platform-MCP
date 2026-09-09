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
import type { Skill, SkillVersion } from "@/types"

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

function routeGet(items: Skill[]) {
  const mockedGet = request.get as ReturnType<typeof vi.fn>
  mockedGet.mockImplementation((url: string) => {
    if (typeof url === "string" && url.endsWith("/versions")) {
      return Promise.resolve({ data: { skill_id: 1, skill_code: "x", current_version: "1.0.0", versions: [mockVersion] } })
    }
    if (typeof url === "string" && url.endsWith("/iteration-diff")) {
      return Promise.resolve({ data: mockDiff })
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
    await btnByText(wrapper, "采纳合并")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/skills/5/resolve-iteration", { choice: "iterate" })
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

  it("admin review dialog shows merge button for origin=PLAZA", async () => {
    const wrapper = await mountAs("admin", "root", [pendingSkill])
    await btnByText(wrapper, "审核")!.trigger("click")
    await flushPromises()
    expect(btnByText(wrapper, "合并到广场")).toBeTruthy()
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
})
