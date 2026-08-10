/** 5.5.1 + 5.5.4 Router + role-based route tests */
import { describe, it, expect } from "vitest"
import router from "@/router/index"

describe("Router configuration", () => {
  it("defines all required routes", () => {
    const routes = router.getRoutes()
    const paths = routes.map(r => r.path)
    expect(paths).toContain("/login")
    expect(paths).toContain("/skills")
    expect(paths).toContain("/datasources")
    expect(paths).toContain("/audit")
    expect(paths).toContain("/crypto")
    expect(paths).toContain("/users")
    expect(paths).toContain("/profile")
    expect(paths).toContain("/mcp-guide")
  })

  it("has 8+ routes defined", () => {
    const routes = router.getRoutes()
    expect(routes.length).toBeGreaterThanOrEqual(8)
  })

  it("admin routes have adminOnly meta", () => {
    const routes = router.getRoutes()
    for (const p of ["/crypto", "/users"]) {
      const route = routes.find(r => r.path === p)
      expect(route?.meta?.adminOnly).toBe(true)
    }
  })

  it("non-admin routes do not have adminOnly meta", () => {
    const routes = router.getRoutes()
    for (const p of ["/skills", "/datasources", "/audit", "/profile", "/mcp-guide"]) {
      const route = routes.find(r => r.path === p)
      expect(route?.meta?.adminOnly).toBeFalsy()
    }
  })
})
