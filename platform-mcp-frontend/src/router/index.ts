import { createRouter, createWebHistory } from "vue-router"
import { useUserStore } from "@/stores/user"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "Login",
      component: () => import("@/views/login/LoginPage.vue"),
      meta: { public: true },
    },
    {
      path: "/",
      component: () => import("@/layouts/MainLayout.vue"),
      redirect: "/skills",
      children: [
        { path: "skills", name: "Skills", component: () => import("@/views/skill/SkillPage.vue") },
        { path: "datasources", name: "Datasources", component: () => import("@/views/datasource/DatasourcePage.vue") },
        { path: "servers", name: "Servers", component: () => import("@/views/server/ServerPage.vue") },
        { path: "audit", name: "Audit", component: () => import("@/views/audit/AuditPage.vue") },
        { path: "crypto", name: "Crypto", component: () => import("@/views/crypto/CryptoPage.vue"), meta: { adminOnly: true } },
        { path: "users", name: "Users", component: () => import("@/views/user/UserPage.vue"), meta: { adminOnly: true } },
        { path: "profile", name: "Profile", component: () => import("@/views/profile/ProfilePage.vue") },
        { path: "mcp-guide", name: "McpGuide", component: () => import("@/views/guide/McpGuidePage.vue") },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/skills" },
  ],
})

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()
  if (to.meta.public) return next()
  // 刷新页面后 Pinia 内存丢失，userStore.user 为 null。但 session cookie 仍在浏览器，
  // /auth/me 会基于 cookie 重建会话。先尝试 fetchProfile，成功则继续；失败（401）才退 /login。
  if (!userStore.isLoggedIn) {
    await userStore.fetchProfile()
  }
  if (!userStore.isLoggedIn) return next("/login")
  if (to.meta.adminOnly && !userStore.isAdmin) return next("/skills")
  next()
})

export default router
