<script setup lang="ts">
import { computed, onMounted } from "vue"
import { useRouter, useRoute } from "vue-router"
import { useUserStore } from "@/stores/user"

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

onMounted(async () => {
  if (!userStore.isLoggedIn) {
    await userStore.fetchProfile()
  }
})

const menuGroups = computed(() => {
  const groups = [
    { label: "管理中心", items: [
      { path: "/skills", label: "Skill 管理", icon: "&#9733;" },
      { path: "/datasources", label: "数据源管理", icon: "&#9881;" },
      { path: "/servers", label: "服务器管理", icon: "&#9000;" },
      { path: "/audit", label: "审计日志", icon: "&#128196;" },
    ]},
  ]
  if (userStore.isAdmin) {
    groups.push({ label: "系统管理", items: [
      { path: "/crypto", label: "密码加密", icon: "&#128272;" },
      { path: "/users", label: "用户管理", icon: "&#128100;" },
    ]})
  }
  groups.push({ label: "帮助", items: [
    { path: "/mcp-guide", label: "MCP 接入指南", icon: "&#128218;" },
  ]})
  return groups
})

const breadcrumb = computed(() => {
  const nameMap: Record<string, string> = {
    Skills: "Skill 管理", Datasources: "数据源管理", Servers: "服务器管理", Audit: "审计日志",
    Crypto: "密码加密", Users: "用户管理", Profile: "个人设置", McpGuide: "MCP 接入指南",
  }
  return nameMap[route.name as string] || ""
})

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
            首页 / <span>{{ breadcrumb }}</span>
          </div>
        </div>
        <div class="header-right">
          <span class="role-badge" :class="userStore.isAdmin?'admin':'developer'">{{ userStore.isAdmin?'系统管理员':'开发人员' }}</span>
          <el-dropdown trigger="click">
            <div class="header-user">
              <div class="avatar">{{ (userStore.user?.nickname || userStore.user?.username || '?').charAt(0) }}</div>
              <span class="user-name">{{ userStore.user?.nickname || userStore.user?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="goProfile">个人设置</el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
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
/* content */
.content { flex: 1; overflow-y: auto; padding: 20px 24px; background: var(--color-background); }
</style>
