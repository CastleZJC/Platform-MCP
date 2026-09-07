<script setup lang="ts">
import { computed, onMounted } from "vue"
import { useRouter, useRoute } from "vue-router"
import { useI18n } from "vue-i18n"
import { useUserStore } from "@/stores/user"
import { setLocale, currentLocale, LOCALE_OPTIONS } from "@/i18n"
import type { AppLocale } from "@/i18n"
import request from "@/utils/request"

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

onMounted(async () => {
  if (!userStore.isLoggedIn) {
    await userStore.fetchProfile()
  }
})

const menuGroups = computed(() => {
  const groups: { label: string; items: { path: string; label: string; icon: string }[] }[] = []
  // V3.0 M3.1：功能广场（全角色可见，含 Skill 广场 + 黑名单双二级页签）
  groups.push({ label: t("layout.menuPlaza"), items: [
    { path: "/plaza", label: t("layout.menuPlazaEntry"), icon: "&#127978;" },
  ]})
  // V3.0 三角色：管理中心仅 admin/developer 可见（一般用户仅功能广场 + 帮助）
  if (userStore.canAccessResources) {
    groups.push({ label: t("layout.menuAdmin"), items: [
      { path: "/skills", label: t("layout.menuSkills"), icon: "&#9733;" },
      { path: "/datasources", label: t("layout.menuDatasources"), icon: "&#9881;" },
      { path: "/servers", label: t("layout.menuServers"), icon: "&#9000;" },
      { path: "/audit", label: t("layout.menuAudit"), icon: "&#128196;" },
    ]})
  }
  if (userStore.isAdmin) {
    groups.push({ label: t("layout.menuSystem"), items: [
      { path: "/crypto", label: t("layout.menuCrypto"), icon: "&#128272;" },
      { path: "/users", label: t("layout.menuUsers"), icon: "&#128100;" },
      { path: "/groups", label: t("layout.menuGroups"), icon: "&#128193;" },       // V2.1 交付，V3.0 M0 启用（勘误 4）
      { path: "/notify", label: t("layout.menuNotify"), icon: "&#9993;" },       // V3.0 M5 邮件提醒（仅 Web，置于系统配置上方）
      { path: "/system-config", label: t("layout.menuSystemConfig"), icon: "&#9881;" },  // V2.1 交付，V3.0 M0 启用（勘误 4）
    ]})
  }
  groups.push({ label: t("layout.menuHelp"), items: [
    { path: "/mcp-guide", label: t("layout.menuGuide"), icon: "&#128218;" },
  ]})
  return groups
})

const breadcrumb = computed(() => {
  const nameMap: Record<string, string> = {
    Skills: t("layout.breadcrumbSkills"),
    Datasources: t("layout.breadcrumbDatasources"),
    Servers: t("layout.breadcrumbServers"),
    Audit: t("layout.breadcrumbAudit"),
    Crypto: t("layout.breadcrumbCrypto"),
    Users: t("layout.breadcrumbUsers"),
    Groups: t("layout.breadcrumbGroups"),
    SystemConfig: t("layout.breadcrumbSystemConfig"),
    Notify: t("layout.breadcrumbNotify"),
    Profile: t("layout.breadcrumbProfile"),
    McpGuide: t("layout.breadcrumbGuide"),
    Plaza: t("layout.breadcrumbPlaza"),
  }
  return nameMap[route.name as string] || ""
})

// V3.0 M1: 三角色徽章（admin / developer / user）
const roleBadgeClass = computed(() => {
  const rc = userStore.user?.role_code
  if (rc === "admin") return "admin"
  if (rc === "user") return "user"
  return "developer"
})
const roleBadgeText = computed(() => {
  const rc = userStore.user?.role_code
  if (rc === "admin") return t("layout.roleAdmin")
  if (rc === "user") return t("layout.roleUser")
  return t("layout.roleDeveloper")
})

// V3.0 M1: 语言切换 —— 即时生效 + 持久化至账户（下次登录自动生效）
const locale = computed<AppLocale>(() => currentLocale())
async function handleLangChange(v: AppLocale) {
  setLocale(v)
  try {
    await request.put("/profile", { locale: v })
  } catch { /* 持久化失败不影响即时切换 */ }
}

async function handleLogout() {
  await userStore.logout()
  router.push("/login")
}

function goProfile() {
  router.push("/profile")
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="s-logo">M</div>
        <span>Platform-MCP</span>
      </div>
      <nav class="sidebar-nav">
        <template v-for="group in menuGroups" :key="group.label">
          <div class="nav-group-title">{{ group.label }}</div>
          <router-link
            v-for="item in group.items" :key="item.path" :to="item.path"
            class="nav-item" active-class="active"
          >
            <span class="nav-icon" v-html="item.icon"></span>
            <span>{{ item.label }}</span>
          </router-link>
        </template>
      </nav>
    </aside>
    <div class="main-area">
      <header class="header">
        <div class="header-left">
          <div class="breadcrumb">
            {{ t("layout.breadcrumbHome") }} / <span>{{ breadcrumb }}</span>
          </div>
        </div>
        <div class="header-right">
          <el-select
            :model-value="locale"
            class="lang-select"
            size="small"
            :aria-label="t('layout.language')"
            @change="handleLangChange"
          >
            <el-option v-for="loc in LOCALE_OPTIONS" :key="loc.value" :label="loc.nativeName" :value="loc.value" />
          </el-select>
          <span class="role-badge" :class="roleBadgeClass">{{ roleBadgeText }}</span>
          <el-dropdown trigger="click">
            <div class="header-user">
              <div class="avatar">{{ (userStore.user?.nickname || userStore.user?.username || '?').charAt(0) }}</div>
              <span class="user-name">{{ userStore.user?.nickname || userStore.user?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="goProfile">{{ t("layout.profile") }}</el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">{{ t("layout.logout") }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout { display: flex; height: 100vh; overflow: hidden; }
/* sidebar — 完全对齐原型 §sidebar */
.sidebar {
  width: var(--sidebar-width); background: var(--sidebar-bg);
  display: flex; flex-direction: column; flex-shrink: 0; overflow-y: auto;
}
.sidebar.collapsed { width: 64px; }
.sidebar-header {
  height: var(--header-height); display: flex; align-items: center; padding: 0 20px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.sidebar-header .s-logo {
  width: 32px; height: 32px; background: var(--sidebar-active-bg); border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 13px; margin-right: 10px;
}
.sidebar-header span { color: #fff; font-size: 15px; font-weight: 600; letter-spacing: 0.5px; }
.sidebar.collapsed .sidebar-header span { display: none; }
.sidebar-nav { flex: 1; padding: 12px 0; }
.nav-group-title {
  padding: 12px 20px 6px; font-size: 11px;
  color: rgba(255,255,255,0.35); letter-spacing: 1px; font-weight: 600;
}
.sidebar.collapsed .nav-group-title { display: none; }
.nav-icon { width: 20px; text-align: center; font-size: 15px; flex-shrink: 0; }
.nav-item {
  display: flex; align-items: center; padding: 0 20px; height: 44px;
  color: rgba(255,255,255,0.65); cursor: pointer; transition: all 0.2s;
  gap: 10px; font-size: 14px; margin: 2px 8px; border-radius: 6px;
  text-decoration: none;
}
.nav-item:hover { background: rgba(255,255,255,0.06); color: #fff; }
.nav-item.active { background: var(--sidebar-active-bg); color: #fff; font-weight: 500; }
/* main area */
.main-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
/* header — 完全对齐原型 §header */
.header {
  height: var(--header-height); background: var(--color-surface);
  border-bottom: 1px solid var(--color-background);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px; flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 8px; }
.breadcrumb { color: var(--color-text-secondary); font-size: 13px; }
.breadcrumb span { color: var(--color-text); font-weight: 500; }
.header-right { display: flex; align-items: center; gap: 16px; }
.lang-select { width: 100px; }
.header-user {
  display: flex; align-items: center; gap: 8px; cursor: pointer;
  padding: 4px 8px; border-radius: var(--radius-sm); transition: background 0.2s;
}
.header-user:hover { background: var(--color-background); }
.avatar {
  width: 32px; height: 32px; background: var(--color-primary); border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 13px; font-weight: 500;
}
.user-name { font-size: 14px; color: var(--color-text); }
.role-badge { font-size: 11px; padding: 1px 6px; border-radius: 3px; font-weight: 500; }
.role-badge.admin { background: #fee2e2; color: #dc2626; }
.role-badge.developer { background: #e0e7ff; color: #4f46e5; }
.role-badge.user { background: #dcfce7; color: #16a34a; }
/* content */
.content { flex: 1; overflow-y: auto; padding: 20px 24px; background: var(--color-background); }
</style>
