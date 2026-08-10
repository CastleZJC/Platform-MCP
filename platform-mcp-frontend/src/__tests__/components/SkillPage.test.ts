/**
 * 5.5.3 组件测试 — SkillPage（P1-1）
 * 覆盖：渲染、查询、状态转换、审核流程
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import SkillPage from "@/views/skill/SkillPage.vue"
import type { Skill } from "@/types"

vi.mock("@/utils/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

import request from "@/utils/request"

const mockSkills: Skill[] = [
  {
    id: 1,
    skill_code: "database",
    skill_name: "Database Skill",
    description: "SQL execution",
    status: "ENABLED",
    tool_count: 5,
    register_method: "decorator",
    submitted_by: "admin",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: 2,
    skill_code: "pending_skill",
    skill_name: "Pending Skill",
    description: "Pending review",
    status: "PENDING_REVIEW",
    tool_count: 2,
    register_method: "decorator",
    submitted_by: "dev01",
    created_at: "2026-01-02T00:00:00Z",
  },
]

describe("SkillPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders page header and toolbar", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: [], total: 0 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    expect(wrapper.find(".page-header h2").text()).toBe("Skill 管理")
    expect(wrapper.find(".search-input").exists()).toBe(true)
    expect(wrapper.find("button.btn-primary[disabled]").exists()).toBe(true)
  })

  it("renders skill list on mount", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: mockSkills, total: 2 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    const rows = wrapper.findAll("tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("database")
    // PENDING_REVIEW 被中文映射为"待审核"
    expect(rows[1].text()).toContain("待审核")
  })

  it("query button triggers fetchSkills", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: [], total: 0 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledTimes(1)
    await wrapper.find("button.btn:not(.btn-primary)").trigger("click")
    await flushPromises()
    expect(mockedGet).toHaveBeenCalledTimes(2)
  })

  it("ENABLED skill shows disable button", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: [mockSkills[0]], total: 1 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    const actionCell = wrapper.find("tbody tr td.actions")
    expect(actionCell.text()).toContain("停用")
  })

  it("DISABLED skill shows enable button", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const disabled = { ...mockSkills[0], status: "DISABLED" }
    mockedGet.mockResolvedValue({ data: { items: [disabled], total: 1 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    const actionCell = wrapper.find("tbody tr td.actions")
    expect(actionCell.text()).toContain("启用")
  })

  it("PENDING_REVIEW skill shows review button", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: [mockSkills[1]], total: 1 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    const actionCell = wrapper.find("tbody tr td.actions")
    expect(actionCell.text()).toContain("审核")
  })

  it("disable skill calls PUT and refetches", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    const mockedPut = request.put as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: [mockSkills[0]], total: 1 } })
    mockedPut.mockResolvedValue({})
    const wrapper = mount(SkillPage)
    await flushPromises()
    mockedGet.mockClear()
    await wrapper.find("tbody tr td.actions button.btn-danger").trigger("click")
    await flushPromises()
    expect(mockedPut).toHaveBeenCalledWith("/skills/1/status", { status: "DISABLED" })
    expect(mockedGet).toHaveBeenCalled()
  })

  it("new skill button is disabled (phase 2)", async () => {
    const mockedGet = request.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValue({ data: { items: [], total: 0 } })
    const wrapper = mount(SkillPage)
    await flushPromises()
    const btn = wrapper.find("button.btn-primary[disabled]")
    expect(btn.attributes("title")).toBe("二期功能")
  })
})
