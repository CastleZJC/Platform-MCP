/**
 * 5.5.3 组件测试 — PlazaPage（V3.0 M3.1 功能广场页 + 反馈批次：列精简/停用/黑名单 RM）
 * 覆盖：双页签渲染、广场列表（编码/名称/涉库标记，不渲染版本/分享者/描述列）、
 *       语义搜索（similarity 列 + /plaza/search）、重置、详情弹窗、README 弹窗（/plaza/{id}/readme + locale）、
 *       添加至我的（/plaza/{id}/copy）、屏蔽（/plaza/block）、admin 停用（/plaza/{id}/disable）与已停用行口径、
 *       黑名单页签（/plaza/blocked，无类型列）与撤销屏蔽（/plaza/unblock）、黑名单 RM（广场/个人双链路）。
 *
 * 说明：与 SkillPage 测试一致 —— ElementPlus 弹窗内容挂在 wrapper 组件树内，经 wrapper.text() 断言；
 *       ElMessageBox.confirm/prompt 经 spy mock 直接 resolve，避免 document.body DOM 交互。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import ElementPlus, { ElMessageBox } from "element-plus"
import type { MessageBoxData } from "element-plus"
import PlazaPage from "@/views/plaza/PlazaPage.vue"
import { useUserStore } from "@/stores/user"
import type { PlazaSkill, BlockedSkill } from "@/types"

// 批次 6.2：ApiError 命名导出一并 mock（PlazaPage 以 instanceof ApiError 分支 10006 复制冲突），
// 测试侧 new ApiError(...) 与组件侧拿到的是同一工厂类实例，instanceof 判定成立
vi.mock("@/utils/request", () => {
  class ApiError extends Error {
    code: number
    data: unknown
    constructor(message: string, code: number, data: unknown) {
      super(message)
      this.code = code
      this.data = data
    }
  }
  return {
    default: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
    ApiError,
  }
})

import request, { ApiError } from "@/utils/request"

const plainSkill: PlazaSkill = {
  plaza_id: 1,
  skill_code: "oracle-backup",
  skill_name: "Oracle 备份",
  description: "数据库备份工具",
  version: "1.0",
  involve_flags: [],
  iteration_note: null,
  status: "PUBLISHED",
  uploader: { username: "dev01", nickname: "开发者一号" },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
}

const dbSkill: PlazaSkill = {
  plaza_id: 2,
  skill_code: "db-admin",
  skill_name: "数据库管理",
  description: "直连 DML",
  version: "2.1",
  involve_flags: ["database"],
  iteration_note: "修复连接泄漏",
  status: "PUBLISHED",
  uploader: { username: "admin", nickname: null },
  created_at: "2026-01-03T00:00:00Z",
  updated_at: null,
}

// 按 URL 路由的 GET mock：search / blocked / readme / versions / list
type RouteGetOpts = {
  list?: PlazaSkill[]
  search?: PlazaSkill[]
  blocked?: BlockedSkill[]
  readme?: { zh: string; en: string }
  skillVersions?: { version: string; readme_zh: string | null; readme_en: string | null }[]
  plazaVersions?: { version: string; source_version: string | null; file_count: number; audit_passed: boolean | null; created_at: string | null }[]
}
function routeGet(opts: RouteGetOpts = {}) {
  const mockedGet = request.get as ReturnType<typeof vi.fn>
  mockedGet.mockImplementation((url: string) => {
    if (typeof url === "string" && url.endsWith("/readme")) {
      const r = opts.readme ?? { zh: "# 中文README", en: "# English README" }
      return Promise.resolve({ data: { plaza_id: 1, skill_code: "oracle-backup", skill_name: "Oracle 备份", readme_zh: r.zh, readme_en: r.en } })
    }
    if (typeof url === "string" && /\/plaza\/\d+\/versions$/.test(url)) {
      // 版本历史弹窗（批次4）：id 倒序，current_version=生效版本（可能≠最新归档版=回滚态）
      const versions = opts.plazaVersions ?? []
      return Promise.resolve({ data: { plaza_id: 1, current_version: versions[versions.length - 1]?.version ?? "", versions } })
    }
    if (typeof url === "string" && url.endsWith("/versions")) {
      const versions = opts.skillVersions ?? []
      return Promise.resolve({ data: { skill_id: 7, skill_code: "my-skill", current_version: versions[0]?.version ?? null, versions } })
    }
    if (typeof url === "string" && url.endsWith("/plaza/search")) {
      const items = opts.search ?? []
      return Promise.resolve({ data: { query: "q", total: items.length, items } })
    }
    if (typeof url === "string" && url.endsWith("/plaza/blocked")) {
      const items = opts.blocked ?? []
      return Promise.resolve({ data: { items, total: items.length } })
    }
    const items = opts.list ?? []
    return Promise.resolve({ data: { items, total: items.length, page: 1, page_size: 20 } })
  })
  return mockedGet
}

function btnByText(wrapper: VueWrapper, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text))
}

describe("PlazaPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountAs(role: "admin" | "developer" | "user", opts: Parameters<typeof routeGet>[0] = {}) {
    routeGet(opts)
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: "u1", nickname: null, email: null, role_code: role, api_key_prefix: null, status: 1, locale: "zh-CN" } })
    const wrapper = mount(PlazaPage, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    return wrapper
  }

  it("渲染页头与双页签", async () => {
    const wrapper = await mountAs("admin", { list: [plainSkill] })
    expect(wrapper.find(".page-header h2").text()).toBe("功能广场")
    const tabs = wrapper.findAll(".el-tabs__item").map((t) => t.text())
    expect(tabs).toContain("Skill 广场")
    expect(tabs).toContain("Skill 黑名单")
  })

  it("广场列表渲染编码/名称，不渲染版本/分享者/描述列", async () => {
    const wrapper = await mountAs("admin", { list: [plainSkill, dbSkill] })
    const rows = wrapper.findAll(".plaza-table tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("oracle-backup")
    expect(rows[0].text()).toContain("Oracle 备份")
    // 反馈口径：版本轨迹/分享者/描述仅内部保留，不展示给用户（README 在操作列）
    expect(wrapper.find(".plaza-table thead").text()).not.toContain("版本")
    expect(wrapper.find(".plaza-table thead").text()).not.toContain("分享者")
    expect(wrapper.find(".plaza-table thead").text()).not.toContain("描述")
    expect(rows[0].text()).not.toContain("开发者一号")
    expect(rows[0].text()).not.toContain("数据库备份工具")
  })

  it("涉库项渲染涉库标记，普通项显示占位", async () => {
    const wrapper = await mountAs("admin", { list: [plainSkill, dbSkill] })
    const rows = wrapper.findAll(".plaza-table tbody tr")
    expect(rows[1].text()).toContain("涉库")
    expect(rows[0].text()).toContain("-")
  })

  it("admin 停用：确认后 POST /plaza/{id}/disable 并刷新列表", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill] })
    mockedGet.mockClear()
    await btnByText(wrapper, "停用")!.trigger("click")
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalled()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/1/disable")
    expect(mockedGet).toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it("非 admin 不渲染停用按钮", async () => {
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    expect(btnByText(wrapper, "停用")).toBeUndefined()
  })

  it("admin 取消停用确认不发请求", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockRejectedValue("cancel")
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill] })
    await btnByText(wrapper, "停用")!.trigger("click")
    await flushPromises()
    expect(mockedPost).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it("已停用项渲染已停用标签且无操作按钮", async () => {
    const disabledRow: PlazaSkill = { ...plainSkill, plaza_id: 3, skill_code: "old-tool", skill_name: "已停用工具", status: "DISABLED" }
    const wrapper = await mountAs("admin", { list: [plainSkill, disabledRow] })
    const rows = wrapper.findAll(".plaza-table tbody tr")
    expect(rows[1].text()).toContain("已停用")
    expect(rows[1].find("button").exists()).toBe(false)
    expect(rows[0].text()).toContain("已发布")
  })

  it("搜索命中 /plaza/search 并展示 similarity 列", async () => {
    const searched: PlazaSkill = { ...plainSkill, similarity: 0.85 }
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: "u1", nickname: null, email: null, role_code: "admin", api_key_prefix: null, status: 1, locale: "zh-CN" } })
    const mockedGet = routeGet({ search: [searched] })
    const wrapper = mount(PlazaPage, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.find(".search-input").setValue("Oracle 备份")
    await btnByText(wrapper, "搜索")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/plaza/search", { params: { q: "Oracle 备份", top_k: 50 } })
    // searchMode 下表头出现相似度列，且分值格式化为三位小数
    expect(wrapper.text()).toContain("相似度")
    expect(wrapper.text()).toContain("0.850")
  })

  it("重置清空搜索并回到列表模式", async () => {
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: "u1", nickname: null, email: null, role_code: "admin", api_key_prefix: null, status: 1, locale: "zh-CN" } })
    const mockedGet = routeGet({ list: [plainSkill], search: [plainSkill] })
    const wrapper = mount(PlazaPage, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.find(".search-input").setValue("abc")
    await btnByText(wrapper, "搜索")!.trigger("click")
    await flushPromises()
    mockedGet.mockClear()
    await btnByText(wrapper, "重置")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/plaza", { params: { page: 1, page_size: 20 } })
  })

  it("详情按钮打开弹窗展示迭代说明", async () => {
    const wrapper = await mountAs("admin", { list: [dbSkill] })
    await btnByText(wrapper, "详情")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("修复连接泄漏")
    expect(wrapper.text()).toContain("数据库管理")
  })

  it("RM 按钮读取 /plaza/{id}/readme 并按 locale 展示中文", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill], readme: { zh: "# 中文README正文", en: "# EN body" } })
    await btnByText(wrapper, "RM")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/plaza/1/readme")
    expect(wrapper.text()).toContain("中文README正文")
    expect(wrapper.text()).not.toContain("EN body")
  })

  it("添加至我的：确认后 POST /plaza/{id}/copy", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalled()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/1/copy")
    confirmSpy.mockRestore()
  })

  it("添加至我的：取消确认不发请求", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockRejectedValue("cancel")
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    expect(mockedPost).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  // ===== 批次 6.2：10006 编码冲突二选一（覆盖本人已有副本 / 换码重试）=====

  const conflictData = { conflict_skill_id: 9, conflict_code: "oracle-backup", overwrite_available: true }

  it("复制冲突 10006：打开二选一弹窗展示冲突编码", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockRejectedValueOnce(new ApiError("skill_code 冲突", 10006, conflictData))
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("编码冲突")
    expect(wrapper.text()).toContain("个人库已存在编码 oracle-backup 的 Skill")
    expect(btnByText(wrapper, "覆盖已有副本")).toBeTruthy()
    expect(btnByText(wrapper, "换码重试")).toBeTruthy()
    confirmSpy.mockRestore()
  })

  it("复制冲突 10006：他人占用（overwrite 不可用）不渲染覆盖按钮", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockRejectedValueOnce(new ApiError("skill_code 冲突", 10006, { ...conflictData, overwrite_available: false }))
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    expect(btnByText(wrapper, "覆盖已有副本")).toBeUndefined()
    expect(btnByText(wrapper, "换码重试")).toBeTruthy()
    confirmSpy.mockRestore()
  })

  it("覆盖已有副本：POST /plaza/{id}/copy 带 conflict_resolution=overwrite", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost
      .mockRejectedValueOnce(new ApiError("skill_code 冲突", 10006, conflictData))
      .mockResolvedValueOnce({ data: {} })
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "覆盖已有副本")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenLastCalledWith("/plaza/1/copy", { conflict_resolution: "overwrite" })
    confirmSpy.mockRestore()
  })

  it("换码重试：新编码为空仅告警不再次提交", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockRejectedValueOnce(new ApiError("skill_code 冲突", 10006, conflictData))
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    await btnByText(wrapper, "换码重试")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledTimes(1) // 仅首次 copy，空编码重试未提交
    confirmSpy.mockRestore()
  })

  it("换码重试：POST retry+new_code；再遇 10006 刷新冲突数据保持弹窗", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost
      .mockRejectedValueOnce(new ApiError("skill_code 冲突", 10006, conflictData))
      .mockRejectedValueOnce(new ApiError("skill_code 冲突", 10006, { conflict_skill_id: 11, conflict_code: "my-tool-v2", overwrite_available: true }))
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    await btnByText(wrapper, "添加至我的")!.trigger("click")
    await flushPromises()
    await wrapper.find("input.form-input").setValue("my-tool-v2")
    await btnByText(wrapper, "换码重试")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenLastCalledWith("/plaza/1/copy", { conflict_resolution: "retry", new_code: "my-tool-v2" })
    // 第二次 10006：弹窗保持打开且冲突数据刷新为新占用编码
    expect(wrapper.text()).toContain("个人库已存在编码 my-tool-v2 的 Skill")
    confirmSpy.mockRestore()
  })

  it("屏蔽：prompt 输入原因后 POST /plaza/block", async () => {
    const promptSpy = vi.spyOn(ElMessageBox, "prompt").mockResolvedValue({ value: "不需要", action: "confirm" } as unknown as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("user", { list: [plainSkill] })
    await btnByText(wrapper, "屏蔽")!.trigger("click")
    await flushPromises()
    expect(promptSpy).toHaveBeenCalled()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/block", { plaza_id: 1, reason: "不需要" })
    promptSpy.mockRestore()
  })

  it("屏蔽：原因为空时以 null 提交", async () => {
    const promptSpy = vi.spyOn(ElMessageBox, "prompt").mockResolvedValue({ value: "", action: "confirm" } as unknown as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("user", { list: [plainSkill] })
    await btnByText(wrapper, "屏蔽")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/block", { plaza_id: 1, reason: null })
    promptSpy.mockRestore()
  })

  it("切换到黑名单页签拉取 /plaza/blocked 并渲染清单（无类型列）", async () => {
    const blocked: BlockedSkill[] = [
      { id: 1, target_type: "plaza", target_id: 5, skill_code: "oracle-backup", skill_name: "Oracle 备份", reason: "不需要", created_at: "2026-01-01T00:00:00Z" },
      { id: 2, target_type: "skill", target_id: 7, skill_code: "my-skill", skill_name: "我的技能", reason: null, created_at: null },
    ]
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill], blocked })
    // 点击第二个页签（Skill 黑名单）
    const tabs = wrapper.findAll(".el-tabs__item")
    await tabs[1].trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/plaza/blocked", { params: { page: 1, page_size: 20 } })
    expect(wrapper.find(".blocked-table thead").text()).not.toContain("类型")
    expect(wrapper.text()).toContain("oracle-backup")
    expect(wrapper.text()).toContain("my-skill")
  })

  it("撤销屏蔽：广场项 POST /plaza/unblock 带 plaza_id", async () => {
    const blocked: BlockedSkill[] = [
      { id: 1, target_type: "plaza", target_id: 5, skill_code: "oracle-backup", skill_name: "Oracle 备份", reason: null, created_at: null },
    ]
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("admin", { list: [plainSkill], blocked })
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    await btnByText(wrapper, "撤销屏蔽")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/unblock", { plaza_id: 5 })
  })

  it("撤销屏蔽：个人项 POST /plaza/unblock 带 skill_id", async () => {
    const blocked: BlockedSkill[] = [
      { id: 2, target_type: "skill", target_id: 7, skill_code: "my-skill", skill_name: "我的技能", reason: null, created_at: null },
    ]
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: {} })
    const wrapper = await mountAs("user", { list: [], blocked })
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    await btnByText(wrapper, "撤销屏蔽")!.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/unblock", { skill_id: 7 })
  })

  it("黑名单 RM：广场项读取 /plaza/{id}/readme 展示中文", async () => {
    const blocked: BlockedSkill[] = [
      { id: 1, target_type: "plaza", target_id: 5, skill_code: "oracle-backup", skill_name: "Oracle 备份", reason: null, created_at: null },
    ]
    const wrapper = await mountAs("admin", { list: [], blocked, readme: { zh: "# 广场存档正文", en: "# EN body" } })
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    await btnByText(wrapper, "RM")!.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("广场存档正文")
    expect(wrapper.text()).not.toContain("EN body")
  })

  it("黑名单 RM：个人项读取 /skills/{id}/versions 最新存档", async () => {
    const blocked: BlockedSkill[] = [
      { id: 2, target_type: "skill", target_id: 7, skill_code: "my-skill", skill_name: "我的技能", reason: null, created_at: null },
    ]
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("user", {
      list: [],
      blocked,
      skillVersions: [{ version: "1.0.0", readme_zh: "# 个人存档正文", readme_en: "# EN" }],
    })
    await wrapper.findAll(".el-tabs__item")[1].trigger("click")
    await flushPromises()
    mockedGet.mockClear()
    await btnByText(wrapper, "RM")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/skills/7/versions")
    expect(wrapper.text()).toContain("个人存档正文")
  })

  it("广场为空时展示占位文案", async () => {
    const wrapper = await mountAs("user", { list: [] })
    expect(wrapper.text()).toContain("广场暂无可见 Skill")
  })

  // ===== 批次4：版本历史弹窗 + 回滚（admin）=====

  const plazaVersionRows = [
    { version: "1.0.1", source_version: "1.0.1", file_count: 3, audit_passed: true, created_at: "2026-01-05T00:00:00Z" },
    { version: "0.9.0", source_version: "0.9.0", file_count: 2, audit_passed: true, created_at: "2026-01-01T00:00:00Z" },
  ]

  it("admin 版本列表：拉取 /plaza/{id}/versions 渲染行与当前生效标记", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill], plazaVersions: plazaVersionRows })
    await btnByText(wrapper, "版本列表")!.trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledWith("/plaza/1/versions")
    const rows = wrapper.findAll(".version-table tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("v1.0.1")
    expect(rows[1].text()).toContain("v0.9.0")
    expect(rows[1].text()).toContain("当前生效")  // 生效版本（0.9.0）标记，最新归档（1.0.1）无标记
    expect(rows[0].text()).not.toContain("当前生效")
    // 当前生效行回滚按钮禁用，其余行可用
    expect(rows[1].find("button").attributes("disabled")).toBeDefined()
    expect(rows[0].find("button").attributes("disabled")).toBeUndefined()
  })

  it("admin 回滚：确认后 POST /plaza/{id}/versions/{version}/rollback", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as MessageBoxData)
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: { to_version: "1.0.1", holders_marked: 1 } })
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill], plazaVersions: plazaVersionRows })
    await btnByText(wrapper, "版本列表")!.trigger("click")
    await flushPromises()
    mockedGet.mockClear()
    await wrapper.findAll(".version-table tbody tr")[0].find("button").trigger("click")
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalled()
    expect(mockedPost).toHaveBeenCalledWith("/plaza/1/versions/1.0.1/rollback")
    expect(mockedGet).toHaveBeenCalled()  // 回滚成功后刷新广场列表
    confirmSpy.mockRestore()
  })

  it("admin 回滚：取消确认不发请求", async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, "confirm").mockRejectedValue("cancel")
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    const wrapper = await mountAs("admin", { list: [plainSkill], plazaVersions: plazaVersionRows })
    await btnByText(wrapper, "版本列表")!.trigger("click")
    await flushPromises()
    await wrapper.findAll(".version-table tbody tr")[0].find("button").trigger("click")
    await flushPromises()
    expect(mockedPost).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it("非 admin 不渲染版本列表按钮", async () => {
    const wrapper = await mountAs("developer", { list: [plainSkill] })
    expect(btnByText(wrapper, "版本列表")).toBeUndefined()
  })
})
