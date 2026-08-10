/**
 * 组件测试 — ServerPage
 * 覆盖：渲染、查询、状态转换、连接测试、admin vs developer 权限
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import ServerPage from "@/views/server/ServerPage.vue"
import type { Server } from "@/types"

vi.mock("@/utils/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

import request from "@/utils/request"
import { useUserStore } from "@/stores/user"

const mockServers: Server[] = [
  {
    id: 1,
    server_code: "APP-SAMPLE-1",
    server_name: "Linux DEV",
    host: "192.168.1.100",
    ssh_port: 22,
    username: "appuser",
    env_code: "DEV",
    status: 1,
    max_concurrent: 3,
    command_timeout: 300,
    allowed_paths: '["/tmp", "/home/appuser"]',
    forbidden_paths: '["/etc"]',
    remark: "DEV",
    has_password: true,
    has_ssh_key: false,
    created_at: "2026-08-07T12:00:00Z",
  },
  {
    id: 2,
    server_code: "APP-SAMPLE-2",
    server_name: "Linux UAT",
    host: "10.0.0.191",
    ssh_port: 22,
    username: "ops",
    env_code: "UAT",
    status: 0,
    max_concurrent: 2,
    command_timeout: 600,
    allowed_paths: null,
    forbidden_paths: null,
    remark: "",
    has_password: false,
    has_ssh_key: true,
    created_at: "2026-08-07T12:00:00Z",
  },
]

describe("ServerPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountAs(role: "admin" | "developer", items: Server[] = []) {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items, total: items.length } })
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: role, role_code: role, status: 1 } })
    const wrapper = mount(ServerPage)
    await flushPromises()
    return wrapper
  }

  it("renders page header", async () => {
    const wrapper = await mountAs("admin")
    expect(wrapper.find(".page-header h2").text()).toBe("服务器管理")
  })

  it("renders server list on mount", async () => {
    const wrapper = await mountAs("admin", mockServers)
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("APP-SAMPLE-1")
    expect(rows[1].text()).toContain("APP-SAMPLE-2")
  })

  it("shows empty message when no server", async () => {
    const wrapper = await mountAs("admin", [])
    const emptyRow = wrapper.find("tbody tr td[colspan='10']")
    expect(emptyRow.text()).toContain("暂无服务器")
  })

  it("admin sees create button", async () => {
    const wrapper = await mountAs("admin")
    const createBtn = wrapper.find(".toolbar-right button.btn-primary")
    expect(createBtn.exists()).toBe(true)
    expect(createBtn.text()).toContain("新增服务器")
  })

  it("developer does not see create button", async () => {
    const wrapper = await mountAs("developer")
    expect(wrapper.find(".toolbar-right button.btn-primary").exists()).toBe(false)
  })

  it("admin sees edit and disable on ENABLED row", async () => {
    const wrapper = await mountAs("admin", [mockServers[0]])
    const cell = wrapper.find("tbody tr td.actions")
    expect(cell.text()).toContain("编辑")
    expect(cell.text()).toContain("停用")
  })

  it("admin sees enable on DISABLED row", async () => {
    const wrapper = await mountAs("admin", [mockServers[1]])
    const cell = wrapper.find("tbody tr td.actions")
    expect(cell.text()).toContain("启用")
  })

  it("developer only sees test button", async () => {
    const wrapper = await mountAs("developer", [mockServers[0]])
    const cell = wrapper.find("tbody tr td.actions")
    expect(cell.text()).toContain("测试")
    expect(cell.text()).not.toContain("编辑")
    expect(cell.text()).not.toContain("停用")
  })

  it("disable calls PUT status=0", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedPut.mockResolvedValue({})
    const wrapper = await mountAs("admin", [mockServers[0]])
    const btn = wrapper.find("tbody tr td.actions button.btn-danger")
    await btn.trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/servers/1/status", { status: 0 })
  })

  it("enable calls PUT status=1", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedPut.mockResolvedValue({})
    const wrapper = await mountAs("admin", [mockServers[1]])
    const btn = wrapper.find("tbody tr td.actions button.btn-primary")
    await btn.trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/servers/2/status", { status: 1 })
  })

  it("test connection calls POST", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: { success: true, latency_ms: 42, echo: "Platform-MCP-ok" } })
    const wrapper = await mountAs("developer", [mockServers[0]])
    const btn = wrapper.find("tbody tr td.actions button.btn-success")
    await btn.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/servers/1/test")
  })

  it("auth badge shows Password when has_password", async () => {
    const wrapper = await mountAs("admin", [mockServers[0]])
    const authCell = wrapper.findAll("tbody tr td")[6]
    expect(authCell.text()).toContain("Password")
  })

  it("auth badge shows SSH Key when has_ssh_key", async () => {
    const wrapper = await mountAs("admin", [mockServers[1]])
    const authCell = wrapper.findAll("tbody tr td")[6]
    expect(authCell.text()).toContain("SSH Key")
  })

  it("env tag renders correctly", async () => {
    const wrapper = await mountAs("admin", mockServers)
    const tags = wrapper.findAll("tbody tr .tag")
    expect(tags[0].text()).toBe("DEV")
    expect(tags[1].text()).toBe("UAT")
  })

  it("PROD env tag uses tag-danger class", async () => {
    const prodServer: Server = { ...mockServers[0], env_code: "PROD" }
    const wrapper = await mountAs("admin", [prodServer])
    const tag = wrapper.find("tbody tr .tag")
    expect(tag.classes()).toContain("tag-danger")
  })

  it("renders search input with placeholder", async () => {
    const wrapper = await mountAs("admin")
    const input = wrapper.find(".search-input")
    expect(input.attributes("placeholder")).toContain("搜索")
  })

  it("fetches servers on mount with page params", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    await mountAs("admin", mockServers)
    expect(mockedGet).toHaveBeenCalledWith("/servers", expect.objectContaining({
      params: expect.objectContaining({ page: 1, page_size: 20 }),
    }))
  })

  it("renders host and ssh_port in mono font cells", async () => {
    const wrapper = await mountAs("admin", [mockServers[0]])
    const monoCells = wrapper.findAll("tbody tr td.text-mono")
    const texts = monoCells.map(c => c.text())
    expect(texts.some(t => t.includes("192.168.1.100"))).toBe(true)
    expect(texts.some(t => t.includes("22"))).toBe(true)
  })
})
