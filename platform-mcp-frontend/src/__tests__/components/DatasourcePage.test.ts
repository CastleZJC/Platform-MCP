/**
 * 5.5.3 组件测试 — DatasourcePage（P1-1）
 * 覆盖：渲染、查询、状态转换、连接测试、admin vs developer 权限
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import DatasourcePage from "@/views/datasource/DatasourcePage.vue"
import type { Datasource } from "@/types"

vi.mock("@/utils/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

import request from "@/utils/request"
import { useUserStore } from "@/stores/user"

const mockDatasources: Datasource[] = [
  {
    id: 1,
    datasource_code: "APP-SAMPLE-1",
    datasource_name: "Oracle Prod",
    db_type: "oracle",
    env_code: "PROD",
    host: "db.oracle.prod",
    port: 1521,
    instance_name: "ORCL",
    service_name: "",
    database: "",
    username: "app_user",
    max_concurrent: 5,
    query_timeout: 300,
    status: 1,
    remark: "Prod",
    created_at: "2026-01-01",
  },
  {
    id: 2,
    datasource_code: "APP-SAMPLE-2",
    datasource_name: "MySQL Dev",
    db_type: "mysql",
    env_code: "DEV",
    host: "db.mysql.dev",
    port: 3306,
    instance_name: "",
    service_name: "",
    database: "appdb",
    username: "dev",
    max_concurrent: 5,
    query_timeout: 300,
    status: 0,
    remark: "Dev",
    created_at: "2026-01-01",
  },
]

describe("DatasourcePage", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountAs(role: "admin" | "developer", items: Datasource[] = []) {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items, total: items.length } })
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: role, role_code: role, status: 1 } })
    const wrapper = mount(DatasourcePage)
    await flushPromises()
    return wrapper
  }

  it("renders page header and toolbar", async () => {
    const wrapper = await mountAs("admin")
    expect(wrapper.find(".page-header h2").text()).toBe("数据源管理")
    expect(wrapper.find(".search-input").exists()).toBe(true)
    expect(wrapper.findAll("select.form-select").length).toBe(3)
  })

  it("renders datasource list on mount", async () => {
    const wrapper = await mountAs("admin", mockDatasources)
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("APP-SAMPLE-1")
    expect(rows[1].text()).toContain("APP-SAMPLE-2")
  })

  it("shows empty message when no datasource", async () => {
    const wrapper = await mountAs("admin", [])
    const emptyRow = wrapper.find("tbody tr td[colspan='9']")
    expect(emptyRow.text()).toContain("暂无数据源")
  })

  it("admin sees create button", async () => {
    const wrapper = await mountAs("admin")
    const createBtn = wrapper.find(".toolbar-right button.btn-primary")
    expect(createBtn.exists()).toBe(true)
    expect(createBtn.text()).toContain("新增数据源")
  })

  it("developer does not see create button", async () => {
    const wrapper = await mountAs("developer")
    const createBtn = wrapper.find(".toolbar-right button.btn-primary")
    expect(createBtn.exists()).toBe(false)
  })

  it("admin sees edit and disable buttons on ENABLED row", async () => {
    const wrapper = await mountAs("admin", [mockDatasources[0]])
    const actionCell = wrapper.find("tbody tr td.actions")
    expect(actionCell.text()).toContain("编辑")
    expect(actionCell.text()).toContain("停用")
  })

  it("admin sees enable button on DISABLED row", async () => {
    const wrapper = await mountAs("admin", [mockDatasources[1]])
    const actionCell = wrapper.find("tbody tr td.actions")
    expect(actionCell.text()).toContain("启用")
  })

  it("developer only sees test button", async () => {
    const wrapper = await mountAs("developer", [mockDatasources[0]])
    const actionCell = wrapper.find("tbody tr td.actions")
    expect(actionCell.text()).toContain("测试")
    expect(actionCell.text()).not.toContain("编辑")
    expect(actionCell.text()).not.toContain("停用")
  })

  it("disable datasource calls PUT status=0", async () => {
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedPut.mockResolvedValue({})
    const wrapper = await mountAs("admin", [mockDatasources[0]])
    const disableBtn = wrapper.find("tbody tr td.actions button.btn-danger")
    await disableBtn.trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/datasources/1/status", { status: 0 })
  })

  it("test connection calls POST", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({ data: { success: true, latency_ms: 50 } })
    const wrapper = await mountAs("developer", [mockDatasources[0]])
    const testBtn = wrapper.find("tbody tr td.actions button.btn-success")
    await testBtn.trigger("click")
    await flushPromises()
    expect(mockedPost).toHaveBeenCalledWith("/datasources/1/test")
  })
})
