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

// 拦截器运行期把 AxiosResponse 解包成 ApiResponse（调用方 res.data 即业务 payload）
// 类型上 axios 要求返回 AxiosResponse，故对解包结果做 unknown->AxiosResponse cast 对齐签名
request.interceptors.response.use(
  (res): AxiosResponse | Promise<AxiosResponse> => {
    const data = res.data as ApiResponse
    if (data.code !== 0) {
      ElMessage.error(data.message || i18n.global.t("common.requestFailed"))
      return Promise.reject(new Error(data.message))
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
