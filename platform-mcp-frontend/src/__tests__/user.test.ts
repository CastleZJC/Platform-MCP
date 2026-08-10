/** 5.5.2 Pinia Store 测试 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import { useUserStore } from "../stores/user"

vi.mock("@/utils/request", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

import request from "@/utils/request"

describe("useUserStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("initial state: user null, isLoggedIn false, isAdmin false", () => {
    const store = useUserStore()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(store.isAdmin).toBe(false)
  })

  it("login success sets user", async () => {
    const mocked = request.post as ReturnType<typeof vi.fn>
    mocked.mockResolvedValue({ data: { id: 1, username: "admin", role_code: "admin", status: 1 } })
    const store = useUserStore()
    await store.login("admin", "pass")
    expect(store.user).not.toBeNull()
    expect(store.user!.username).toBe("admin")
    expect(store.isLoggedIn).toBe(true)
  })

  it("login failure throws", async () => {
    const mocked = request.post as ReturnType<typeof vi.fn>
    mocked.mockRejectedValue(new Error("fail"))
    const store = useUserStore()
    await expect(store.login("admin", "wrong")).rejects.toThrow("fail")
    expect(store.user).toBeNull()
  })

  it("logout clears user", async () => {
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: "admin", role_code: "admin", status: 1 } })
    const mocked = request.post as ReturnType<typeof vi.fn>
    mocked.mockResolvedValue({})
    await store.logout()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
  })

  it("fetchProfile success updates user", async () => {
    const mocked = request.get as ReturnType<typeof vi.fn>
    mocked.mockResolvedValue({ data: { id: 1, username: "admin", role_code: "admin", status: 1 } })
    const store = useUserStore()
    await store.fetchProfile()
    expect(store.user).not.toBeNull()
    expect(store.user!.username).toBe("admin")
  })

  it("fetchProfile failure sets user null", async () => {
    const mocked = request.get as ReturnType<typeof vi.fn>
    mocked.mockRejectedValue(new Error("fail"))
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: "admin", role_code: "admin", status: 1 } })
    await store.fetchProfile()
    expect(store.user).toBeNull()
  })

  it("isAdmin true for admin role", () => {
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: "admin", role_code: "admin", status: 1 } })
    expect(store.isAdmin).toBe(true)
  })

  it("isAdmin false for developer role", () => {
    const store = useUserStore()
    store.$patch({ user: { id: 2, username: "dev", role_code: "developer", status: 1 } })
    expect(store.isAdmin).toBe(false)
  })
})
