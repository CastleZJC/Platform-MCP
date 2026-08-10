import { defineStore } from "pinia"
import { ref, computed } from "vue"
import request from "@/utils/request"
import type { User, LoginRequest } from "@/types"

export const useUserStore = defineStore("user", () => {
  const user = ref<User | null>(null)
  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role_code === "admin")

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

  return { user, isLoggedIn, isAdmin, login, logout, fetchProfile }
})
