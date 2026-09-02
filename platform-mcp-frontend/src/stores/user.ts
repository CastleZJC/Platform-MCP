import { defineStore } from "pinia"
import { ref, computed } from "vue"
import request from "@/utils/request"
import type { User, LoginRequest } from "@/types"
import { setLocale, SUPPORTED_LOCALES } from "@/i18n"
import type { AppLocale } from "@/i18n"

// V3.0 M1: 后端 user.locale 为权威值 —— 登录成功 / 拉取 profile 后应用（重新登录生效）
function applyUserLocale(u: User | null): void {
  const l = u?.locale
  if (l && (SUPPORTED_LOCALES as readonly string[]).includes(l)) {
    setLocale(l as AppLocale)
  }
}

export const useUserStore = defineStore("user", () => {
  const user = ref<User | null>(null)
  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role_code === "admin")
  // V3.0 三角色：一般用户（无 database/server 权限，有 Skill 生态权限）
  const isRegularUser = computed(() => user.value?.role_code === "user")
  const canAccessResources = computed(() => user.value?.role_code === "admin" || user.value?.role_code === "developer")

  async function login(username: string, password: string) {
    const body: LoginRequest = { username, password }
    const res = await request.post("/auth/login", body)
    user.value = res.data as User
    applyUserLocale(user.value)
  }

  async function logout() {
    try { await request.post("/auth/logout") } catch { /* ignore */ }
    user.value = null
  }

  async function fetchProfile() {
    try {
      const res = await request.get("/auth/me")
      user.value = res.data as User
      applyUserLocale(user.value)
    } catch {
      user.value = null
    }
  }

  return { user, isLoggedIn, isAdmin, isRegularUser, canAccessResources, login, logout, fetchProfile }
})
