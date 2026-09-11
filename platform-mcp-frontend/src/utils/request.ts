import axios, { type AxiosResponse } from "axios"
import { ElMessage } from "element-plus"
import router from "@/router"
import { i18n } from "@/i18n"
import type { ApiResponse } from "@/types"

const request = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
  withCredentials: true,
})

// 业务错误（code!=0）：保留 code/data 供调用方分支处理（如 10006 复制冲突二选一），统一弹错仍在拦截器
export class ApiError extends Error {
  code: number
  data: unknown

  constructor(message: string, code: number, data: unknown) {
    super(message)
    this.code = code
    this.data = data
  }
}

// 拦截器运行期把 AxiosResponse 解包成 ApiResponse（调用方 res.data 即业务 payload）
// 类型上 axios 要求返回 AxiosResponse，故对解包结果做 unknown->AxiosResponse cast 对齐签名
request.interceptors.response.use(
  (res): AxiosResponse | Promise<AxiosResponse> => {
    const data = res.data as ApiResponse
    if (data.code !== 0) {
      ElMessage.error(data.message || i18n.global.t("common.requestFailed"))
      return Promise.reject(new ApiError(data.message || "", data.code, data.data))
    }
    return data as unknown as AxiosResponse
  },
  (error) => {
    if (error.response?.status === 401) {
      router.push("/login")
    } else {
      ElMessage.error(error.response?.data?.message || i18n.global.t("common.networkError"))
    }
    return Promise.reject(error)
  }
)

export default request
