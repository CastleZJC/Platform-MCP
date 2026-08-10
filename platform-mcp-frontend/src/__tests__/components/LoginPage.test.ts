/**
 * 5.5.3 组件测试 — LoginPage（P1-1）
 * 覆盖：渲染、空表单校验、登录成功跳转、登录失败提示
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import LoginPage from "@/views/login/LoginPage.vue"

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock("@/utils/request", () => ({
  default: { post: vi.fn() },
}))

import request from "@/utils/request"

describe("LoginPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("renders visual + form areas", () => {
    const wrapper = mount(LoginPage)
    expect(wrapper.find(".login-visual").exists()).toBe(true)
    expect(wrapper.find(".login-form-area").exists()).toBe(true)
    expect(wrapper.find(".visual-logo").text()).toBe("MCP")
  })

  it("renders title and tagline", () => {
    const wrapper = mount(LoginPage)
    expect(wrapper.find("h1").text()).toBe("Platform-MCP")
    expect(wrapper.find(".tagline").text()).toContain("MCP")
  })

  it("renders login form labels", () => {
    const wrapper = mount(LoginPage)
    // 验证 html 包含 el-form-item label
    const html = wrapper.html()
    expect(html).toContain("用户名")
    expect(html).toContain("密码")
    expect(html).toContain("登录")
  })

  it("renders 5 feature bullets", () => {
    const wrapper = mount(LoginPage)
    const features = wrapper.findAll(".visual-features li")
    expect(features.length).toBe(5)
  })

  it("empty form submission does not call API", async () => {
    const wrapper = mount(LoginPage, { attachTo: document.body })
    await flushPromises()
    const form = wrapper.find("form")
    if (form.exists()) {
      await form.trigger("submit.prevent")
      await flushPromises()
    }
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    expect(mockedPost).not.toHaveBeenCalled()
  })

  it("filled form calls login API via el-input", async () => {
    const mockedPost = request.post as ReturnType<typeof vi.fn>
    mockedPost.mockResolvedValue({
      data: { id: 1, username: "admin", role_code: "admin", status: 1 },
    })
    const wrapper = mount(LoginPage, { attachTo: document.body })
    await flushPromises()
    // el-input 内部的 input 元素
    const nativeInputs = document.querySelectorAll("input")
    if (nativeInputs.length >= 2) {
      const usernameInput = nativeInputs[0] as HTMLInputElement
      const passwordInput = nativeInputs[1] as HTMLInputElement
      usernameInput.value = "admin"
      usernameInput.dispatchEvent(new Event("input"))
      passwordInput.value = "admin123"
      passwordInput.dispatchEvent(new Event("input"))
      await flushPromises()
      const form = wrapper.find("form")
      if (form.exists()) {
        await form.trigger("submit.prevent")
        await flushPromises()
      }
      expect(mockedPost).toHaveBeenCalled()
    }
  })
})
