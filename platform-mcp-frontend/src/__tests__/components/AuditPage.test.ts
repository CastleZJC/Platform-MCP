/**
 * 5.5.3 组件测试 — AuditPage（P1-1）
 * 覆盖：渲染、统计卡片、查询、详情、admin vs developer 权限
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import AuditPage from "@/views/audit/AuditPage.vue"
import type { AuditLog } from "@/types"

vi.mock("@/utils/request", () => ({
  default: { get: vi.fn() },
}))

import request from "@/utils/request"
import { useUserStore } from "@/stores/user"

const mockLogs: AuditLog[] = [
  {
    id: 1,
    trace_id: "t1",
    operator: "admin",
    resource_type: "auth",
    request_summary: "用户登录成功",
    result_status: "success",
    risk_level: null,
    duration_ms: 50,
    inserted_at: "2026-01-01T10:00:00Z",
  } as unknown as AuditLog,
  {
    id: 2,
    trace_id: "t2",
    operator: "dev01",
    resource_type: "mcp",
    request_summary: "execute_sql_text",
    result_status: "success",
    risk_level: "HIGH",
    duration_ms: 1200,
    inserted_at: "2026-01-01T11:00:00Z",
  } as unknown as AuditLog,
]

const mockStats = {
  total_operations: 100,
  mcp_calls: 30,
  sql_executions: 50,
  high_risk_blocks: 5,
  trends: {
    total_operations_vs_yesterday: 10,
    mcp_calls_vs_yesterday: 5,
    sql_executions_vs_yesterday: -3,
    high_risk_blocks_vs_yesterday: 0,
  },
}

describe("AuditPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountAs(role: "admin" | "developer", items: AuditLog[] = []) {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockImplementation((url: string) => {
      if (url === "/audit/stats") return Promise.resolve({ data: mockStats })
      if (url === "/datasources") return Promise.resolve({ data: { items: [], total: 0 } })
      if (url.startsWith("/audit/logs/")) return Promise.resolve({ data: items[0] || {} })
      return Promise.resolve({ data: { items, total: items.length } })
    })
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: role, role_code: role, status: 1 } })
    const wrapper = mount(AuditPage)
    await flushPromises()
    return wrapper
  }

  it("renders page header", async () => {
    const wrapper = await mountAs("admin")
    expect(wrapper.find(".page-header h2").text()).toBe("审计日志")
  })

  it("renders stats cards from /audit/stats", async () => {
    const wrapper = await mountAs("admin")
    expect(wrapper.find(".stats-row").exists()).toBe(true)
    const cards = wrapper.findAll(".stat-card")
    expect(cards.length).toBeGreaterThanOrEqual(4)
  })

  it("renders log rows on mount", async () => {
    const wrapper = await mountAs("admin", mockLogs)
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("admin")
    // request_summary 不在列表显示，改为验证 resource_type
    expect(rows[1].text()).toContain("mcp")
  })

  it("admin sees operator filter", async () => {
    const wrapper = await mountAs("admin")
    const inputs = wrapper.findAll("input")
    const hasOperator = inputs.some(i => i.attributes("placeholder")?.includes("操作人"))
    expect(hasOperator).toBe(true)
  })

  it("developer does not see operator filter", async () => {
    const wrapper = await mountAs("developer")
    const inputs = wrapper.findAll("input")
    const hasOperator = inputs.some(i => i.attributes("placeholder")?.includes("操作人"))
    expect(hasOperator).toBe(false)
  })

  it("HIGH risk renders with danger tag class", async () => {
    const wrapper = await mountAs("admin", mockLogs)
    const dangerTags = wrapper.findAll(".tag-danger")
    expect(dangerTags.length).toBeGreaterThanOrEqual(1)
  })

  it("stats trends show up/down arrows", async () => {
    const wrapper = await mountAs("admin")
    const trendEls = wrapper.findAll(".stat-trend")
    expect(trendEls.length).toBeGreaterThanOrEqual(4)
  })

  it("empty logs shows placeholder row", async () => {
    const wrapper = await mountAs("admin", [])
    const placeholder = wrapper.find("tbody tr td[colspan]")
    expect(placeholder.exists()).toBe(true)
  })
})
