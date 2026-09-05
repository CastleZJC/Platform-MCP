/**
 * V3.0 M5 组件测试 — NotifyPage（邮件提醒）
 * 覆盖：四组列表渲染（成员/无邮箱提示/待发送数）、启停 PUT、模板编辑保存 PUT、
 * 成员管理候选仅 admin、测试发送链路
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import ElementPlus from "element-plus"
import NotifyPage from "@/views/notify/NotifyPage.vue"

vi.mock("@/utils/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import request from "@/utils/request"

const mockGroups = [
  {
    notify_type: "skill_review",
    group_name: "Skill 审核组",
    subject_template: "【审核】{{user}}",
    body_template: "资源 {{resource}}",
    param_descriptions: { user: "操作人", resource: "资源" },
    enabled: 1,
    members: [
      { member_id: 11, user_id: 1, username: "admin", nickname: "管理员", email: "admin@x.com", has_email: true },
      { member_id: 12, user_id: 2, username: "admin2", nickname: null, email: null, has_email: false },
    ],
    unsent_count: 2,
    updated_at: "2026-09-05T12:00:00",
  },
  {
    notify_type: "user_mgmt",
    group_name: "用户管理组",
    subject_template: "【用户】{{user}}",
    body_template: "操作 {{action}}",
    param_descriptions: { user: "操作人" },
    enabled: 0,
    members: [],
    unsent_count: 0,
    updated_at: null,
  },
]

const mockUsers = [
  { id: 1, username: "admin", nickname: "管理员", email: "admin@x.com", role_code: "admin" },   // 已在组内 → 排除
  { id: 3, username: "dev01", nickname: "开发者", email: "dev@x.com", role_code: "developer" }, // 非 admin → 排除
  { id: 4, username: "admin3", nickname: null, email: null, role_code: "admin" },               // 唯一候选（无邮箱仍可入组）
]

function mockGetImpl(url: string) {
  if (url === "/notify/groups") return Promise.resolve({ data: mockGroups })
  if (url === "/notify/outbox") return Promise.resolve({ data: { items: [], total: 0 } })
  if (url.startsWith("/users")) return Promise.resolve({ data: { items: mockUsers, total: 3 } })
  return Promise.resolve({ data: null })
}

describe("NotifyPage（邮件提醒）", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountPage() {
    ;(request.get as ReturnType<typeof vi.fn>).mockImplementation(mockGetImpl)
    const wrapper = mount(NotifyPage, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    return wrapper
  }

  it("渲染四提醒事项组列表：组名/成员/无邮箱提示/待发送数", async () => {
    const wrapper = await mountPage()
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBeGreaterThanOrEqual(2)
    const firstRow = rows[0].text()
    expect(firstRow).toContain("Skill 审核")
    expect(firstRow).toContain("admin（管理员）")
    expect(firstRow).toContain("未配置邮箱") // admin2 无邮箱提示（F-37）
    expect(firstRow).toContain("2") // unsent_count
    // 第二组停用 + 空成员
    expect(rows[1].text()).toContain("已停用")
  })

  it("停用组提交 PUT enabled=0", async () => {
    const put = request.put as ReturnType<typeof vi.fn>
    put.mockResolvedValue({ data: null })
    const wrapper = await mountPage()
    await wrapper.findAll("tbody tr td.actions button").filter((b) => b.text() === "停用")[0].trigger("click")
    await flushPromises()
    expect(put).toHaveBeenCalledWith("/notify/groups/skill_review", { enabled: 0 })
  })

  it("模板编辑预填并保存提交 PUT 模板（F-39）", async () => {
    const put = request.put as ReturnType<typeof vi.fn>
    put.mockResolvedValue({ data: null })
    const wrapper = await mountPage()
    await wrapper.findAll("tbody tr td.actions button").filter((b) => b.text() === "模板编辑")[0].trigger("click")
    await flushPromises()
    const dialog = wrapper.find(".el-dialog")
    expect(dialog.text()).toContain("{{user}}") // 参数说明表展示占位符（script 侧拼接避免模板定界符冲突）
    // 修改主题模板（inputs[0]=组名 / [1]=主题，预填值校验）
    const inputs = dialog.findAll("input.el-input__inner")
    expect((inputs[1].element as HTMLInputElement).value).toBe("【审核】{{user}}")
    await inputs[1].setValue("【新主题】{{user}} 于 {{time}}")
    await dialog.findAll("button").filter((b) => b.text() === "保存")[0].trigger("click")
    await flushPromises()
    expect(put).toHaveBeenCalledWith("/notify/groups/skill_review", {
      group_name: "Skill 审核组",
      subject_template: "【新主题】{{user}} 于 {{time}}",
      body_template: "资源 {{resource}}",
    })
  })

  it("成员管理候选仅 admin 角色用户（F-37）", async () => {
    const wrapper = await mountPage()
    await wrapper.findAll("tbody tr td.actions button").filter((b) => b.text() === "成员管理")[0].trigger("click")
    await flushPromises()
    const options = wrapper.findAllComponents({ name: "ElOption" })
    // admin(1) 在组内排除；dev01 非 admin 排除；admin3(4) 无邮箱但可入组
    expect(options.length).toBe(1)
    expect(options[0].text()).toContain("admin3")
    expect(options[0].text()).toContain("未配置邮箱")
  })

  it("成员移除提交 DELETE", async () => {
    const del = request.delete as ReturnType<typeof vi.fn>
    del.mockResolvedValue({ data: null })
    const wrapper = await mountPage()
    await wrapper.findAll("tbody tr td.actions button").filter((b) => b.text() === "成员管理")[0].trigger("click")
    await flushPromises()
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "删除")[0].trigger("click")
    await flushPromises()
    expect(del).toHaveBeenCalledWith("/notify/groups/skill_review/members/1")
  })

  it("测试发送：合法收件人提交 POST /notify/test", async () => {
    const post = request.post as ReturnType<typeof vi.fn>
    post.mockResolvedValue({ data: { sent: 1, failed: 0, pending: 0 } })
    const wrapper = await mountPage()
    await wrapper.findAll("button").filter((b) => b.text() === "发送测试")[0].trigger("click")
    await flushPromises()
    const input = wrapper.find(".el-dialog input.el-input__inner")
    await input.setValue("ops@x.com")
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "发送")[0].trigger("click")
    await flushPromises()
    expect(post).toHaveBeenCalledWith("/notify/test", { recipient: "ops@x.com" })
  })

  it("测试发送：空收件人不发请求", async () => {
    const post = request.post as ReturnType<typeof vi.fn>
    const wrapper = await mountPage()
    await wrapper.findAll("button").filter((b) => b.text() === "发送测试")[0].trigger("click")
    await flushPromises()
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "发送")[0].trigger("click")
    await flushPromises()
    expect(post).not.toHaveBeenCalled()
  })
})
