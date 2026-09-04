/**
 * V3.0 M0 组件测试 — GroupPage（统一组）
 * 覆盖：列表渲染（成员名单列）、成员对话框三类多选按类提交、CRUD 动作（无删除）
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import ElementPlus from "element-plus"
import GroupPage from "@/views/group/GroupPage.vue"
import type { Group } from "@/types"

vi.mock("@/utils/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import request from "@/utils/request"

const mockGroups: Group[] = [
  {
    id: 1,
    group_name: "OA系统组",
    description: "跨环境混挂",
    status: 1,
    user_count: 1,
    datasource_count: 2,
    server_count: 0,
    user_names: ["admin"],
    datasource_names: ["OA-DEV库", "OA-PROD库"],
    server_names: [],
    created_at: "2026-09-04",
  },
]

describe("GroupPage（统一组）", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountGroups(items: Group[] = []) {
    (request.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { items, total: items.length } })
    const wrapper = mount(GroupPage, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    return wrapper
  }

  it("渲染统一组列表与成员名单列", async () => {
    const wrapper = await mountGroups(mockGroups)
    expect(wrapper.find("tbody tr").text()).toContain("OA系统组")
    const header = wrapper.find("thead").text()
    expect(header).toContain("成员")
    const cell = wrapper.find("tbody tr td.member-cell").text()
    expect(cell).toContain("admin")
    expect(cell).toContain("OA-DEV库")
    expect(cell).toContain("OA-PROD库")
  })

  it("成员对话框仅提交有变化的成员类型", async () => {
    const get = request.get as ReturnType<typeof vi.fn>
    get.mockImplementation((url: string) => {
      if (url.includes("/members")) {
        return Promise.resolve({
          data: {
            group_id: 1, group_name: "OA系统组",
            users: [{ id: 1, username: "admin", nickname: "管理员" }],
            datasources: [{ id: 10, datasource_code: "ds", datasource_name: "DS", db_type: "oracle", env_code: "DEV" }],
            servers: [],
          },
        })
      }
      if (url.startsWith("/users")) {
        return Promise.resolve({ data: { items: [
          { id: 1, username: "admin", nickname: "管理员" },
          { id: 2, username: "castle", nickname: null },
        ], total: 2 } })
      }
      if (url.startsWith("/datasources")) {
        return Promise.resolve({ data: { items: [
          { id: 10, datasource_code: "ds", datasource_name: "DS", db_type: "oracle", env_code: "DEV" },
          { id: 11, datasource_code: "ds2", datasource_name: "DS2", db_type: "mysql", env_code: "PROD" },
        ], total: 2 } })
      }
      if (url.startsWith("/servers")) {
        return Promise.resolve({ data: { items: [], total: 0 } })
      }
      return Promise.resolve({ data: { items: mockGroups, total: 1 } })
    })
    const wrapper = await mountGroups(mockGroups)
    await wrapper.findAll("tbody tr td.actions button")[0].trigger("click")
    await flushPromises()
    // 仅修改数据源多选（user/server 保持预填）
    const selects = wrapper.findAllComponents({ name: "ElSelect" })
    expect(selects.length).toBe(3)
    await selects[1].vm.$emit("update:modelValue", [10, 11])
    const put = request.put as ReturnType<typeof vi.fn>
    put.mockClear()
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "保存")[0].trigger("click")
    await flushPromises()
    expect(put).toHaveBeenCalledTimes(1)
    expect(put).toHaveBeenCalledWith("/groups/1/members", { resource: "datasource", ids: [10, 11] })
  })

  it("新建组提交 POST /groups（无环境维度）", async () => {
    const post = request.post as ReturnType<typeof vi.fn>
    post.mockResolvedValue({ data: { id: 9 } })
    const wrapper = await mountGroups([])
    await wrapper.findAll("button").filter((b) => b.text().includes("新建组"))[0].trigger("click")
    const nameInput = wrapper.find(".el-dialog input.el-input__inner")
    await nameInput.setValue("UAT组")
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "提交")[0].trigger("click")
    await flushPromises()
    expect(post).toHaveBeenCalledWith("/groups", { group_name: "UAT组", description: "" })
  })

  it("操作列不提供删除按钮（组仅可停用）", async () => {
    const wrapper = await mountGroups(mockGroups)
    const buttons = wrapper.findAll("tbody tr td.actions button").map((b) => b.text())
    expect(buttons).not.toContain("删除")
    expect(buttons).toContain("停用")
  })

  it("停用组提交 status=0", async () => {
    const put = request.put as ReturnType<typeof vi.fn>
    put.mockResolvedValue({ data: null })
    const wrapper = await mountGroups(mockGroups)
    await wrapper.findAll("tbody tr td.actions button").filter((b) => b.text() === "停用")[0].trigger("click")
    await flushPromises()
    expect(put).toHaveBeenCalledWith("/groups/1", { status: 0 })
  })
})
