/** 5.5.1 Axios request wrapper tests */
import { describe, it, expect, vi } from "vitest"
import request from "@/utils/request"

// Mock element-plus and router
vi.mock("element-plus", () => ({
  ElMessage: {
    error: vi.fn(),
  },
}))

vi.mock("@/router", () => ({
  default: {
    push: vi.fn(),
  },
}))

// axios 类型未暴露 AxiosInterceptorManager.handlers，运行期实际存在
// 统一用 any cast 取出已注册的 fulfilled/rejected
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getInterceptors() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const h = (request.interceptors.response as any).handlers as Array<{
    fulfilled?: (v: unknown) => unknown
    rejected?: (e: unknown) => unknown
  }>
  return h[0]
}

describe("request util", () => {
  it("has baseURL set to /api/v1", () => {
    expect(request.defaults.baseURL).toBe("/api/v1")
  })

  it("has withCredentials enabled", () => {
    expect(request.defaults.withCredentials).toBe(true)
  })

  it("响应拦截器 code非0 显示错误消息", async () => {
    const { ElMessage } = await import("element-plus")
    const successHandler = getInterceptors().fulfilled!

    const mockResponse = {
      data: { code: 11001, message: "未登录", data: null },
    }

    await expect(successHandler(mockResponse)).rejects.toThrow("未登录")
    expect(ElMessage.error).toHaveBeenCalledWith("未登录")
  })

  it("响应拦截器 code非0 返回rejected Promise", async () => {
    const successHandler = getInterceptors().fulfilled!

    const mockResponse = {
      data: { code: 500, message: "server error", data: null },
    }

    await expect(successHandler(mockResponse)).rejects.toThrow("server error")
  })

  it("错误拦截器 401 跳转登录页", async () => {
    const router = (await import("@/router")).default
    const errorHandler = getInterceptors().rejected!

    const error401 = { response: { status: 401 } }

    await expect(errorHandler(error401)).rejects.toBe(error401)
    expect(router.push).toHaveBeenCalledWith("/login")
  })

  it("错误拦截器 其他错误 显示消息", async () => {
    const { ElMessage } = await import("element-plus")
    const errorHandler = getInterceptors().rejected!

    const error500 = { response: { status: 500, data: { message: "Internal Error" } } }

    await expect(errorHandler(error500)).rejects.toBe(error500)
    expect(ElMessage.error).toHaveBeenCalledWith("Internal Error")
  })

  it("响应拦截器 code为0 返回data", async () => {
    const successHandler = getInterceptors().fulfilled!

    const mockData = { code: 0, message: "ok", data: { id: 1 } }
    const mockResponse = { data: mockData }

    const result = await successHandler(mockResponse)
    expect(result).toEqual(mockData)
  })
})
