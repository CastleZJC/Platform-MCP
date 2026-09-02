import { defineStore } from "pinia"
import { ref, computed } from "vue"
import request from "@/utils/request"
import type { User, LoginRequest } from "@/types"

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
  }

  async function logout() {
    try { await request.post("/auth/logout") } catch { /* ignore */ }
    user.value = null
  }

  async function fetchProfile() {
    try {
      const res = await request.get("/auth/me")
      user.value = res.data as User
    } catch {
      user.value = null
    }
  }

  return { user, isLoggedIn, isAdmin, isRegularUser, canAccessResources, login, logout, fetchProfile }
})
