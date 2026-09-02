/**
 * V3.0 M0 组件测试 — GroupPage（统一组）
 * 覆盖：列表渲染（三类成员计数）、成员对话框按类提交、用户分配、CRUD 动作
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
    group_name: "DEV核心组",
    description: "开发核心",
    env_code: "DEV",
    status: 1,
    user_count: 2,
    datasource_count: 3,
    server_count: 1,
    created_at: "2026-09-02",
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

  it("渲染统一组列表与三类成员计数列", async () => {
    const wrapper = await mountGroups(mockGroups)
    expect(wrapper.find("tbody tr").text()).toContain("DEV核心组")
    const header = wrapper.find("thead").text()
    expect(header).toContain("组员数")
    expect(header).toContain("数据源数")
    expect(header).toContain("服务器数")
    expect(wrapper.find("tbody tr").text()).toContain("2")
  })

  it("成员对话框仅提交有变化的成员类型", async () => {
    const get = request.get as ReturnType<typeof vi.fn>
    get.mockImplementation((url: string) => {
      if (url.includes("/members")) {
        return Promise.resolve({
          data: {
            group_id: 1, group_name: "DEV核心组",
            users: [{ id: 1, username: "admin", nickname: "管理员" }],
            datasources: [{ id: 10, datasource_code: "ds", datasource_name: "DS", db_type: "oracle", env_code: "DEV" }],
            servers: [],
          },
        })
      }
      return Promise.resolve({ data: { items: mockGroups, total: 1 } })
    })
    const wrapper = await mountGroups(mockGroups)
    await wrapper.findAll("tbody tr td.actions button")[0].trigger("click")
    await flushPromises()
    // 仅修改数据源输入（user/server 保持预填）
    const inputs = wrapper.findAll(".el-dialog input.el-input__inner")
    const dsInput = inputs[1]
    await dsInput.setValue("10,11")
    const put = request.put as ReturnType<typeof vi.fn>
    put.mockClear()
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "保存")[0].trigger("click")
    await flushPromises()
    expect(put).toHaveBeenCalledTimes(1)
    expect(put).toHaveBeenCalledWith("/groups/1/members", { resource: "datasource", ids: [10, 11] })
  })

  it("用户分配提交覆盖式 group_ids", async () => {
    const get = request.get as ReturnType<typeof vi.fn>
    get.mockImplementation((url: string) => {
      if (url.startsWith("/groups/users/2")) return Promise.resolve({ data: { group_ids: [1] } })
      return Promise.resolve({ data: { items: [], total: 0 } })
    })
    const wrapper = await mountGroups([])
    const userInput = wrapper.find("input.user-id-input")
    await userInput.setValue("2")
    await wrapper.findAll("button").filter((b) => b.text() === "用户分配")[0].trigger("click")
    await flushPromises()
    const textarea = wrapper.find(".el-dialog textarea")
    await textarea.setValue("1,4")
    const put = request.put as ReturnType<typeof vi.fn>
    put.mockClear()
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "保存")[0].trigger("click")
    await flushPromises()
    expect(put).toHaveBeenCalledWith("/groups/users/2", { group_ids: [1, 4] })
  })

  it("新建组提交 POST /groups", async () => {
    const post = request.post as ReturnType<typeof vi.fn>
    post.mockResolvedValue({ data: { id: 9 } })
    const wrapper = await mountGroups([])
    await wrapper.findAll("button").filter((b) => b.text().includes("新建组"))[0].trigger("click")
    const nameInput = wrapper.find(".el-dialog input.el-input__inner")
    await nameInput.setValue("UAT组")
    await wrapper.findAll(".el-dialog button").filter((b) => b.text() === "提交")[0].trigger("click")
    await flushPromises()
    expect(post).toHaveBeenCalledWith("/groups", expect.objectContaining({ group_name: "UAT组", env_code: "DEV" }))
  })

  it("删除组提交 DELETE /groups/{id}", async () => {
    const del = request.delete as ReturnType<typeof vi.fn>
    del.mockResolvedValue({ data: null })
    const wrapper = await mountGroups(mockGroups)
    await wrapper.findAll("tbody tr td.actions button").filter((b) => b.text() === "删除")[0].trigger("click")
    await flushPromises()
    expect(del).toHaveBeenCalledWith("/groups/1")
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
