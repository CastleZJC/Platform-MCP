<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { useUserStore } from "@/stores/user"
import { ElMessage } from "element-plus"

const router = useRouter()
const userStore = useUserStore()
const username = ref("")
const password = ref("")
const loading = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning("请输入用户名和密码")
    return
  }
  loading.value = true
  try {
    await userStore.login(username.value, password.value)
    ElMessage.success("登录成功")
    router.push("/skills")
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "登录失败"
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-visual">
      <div class="visual-content">
        <div class="visual-logo">MCP</div>
        <h1>Platform-MCP</h1>
        <p class="tagline">MCP 统一能力服务平台</p>
        <ul class="visual-features">
          <li>统一 MCP Skill 管理与调度</li>
          <li>多数据源安全接入与 SQL 执行</li>
          <li>多服务器安全接入与 SSH/SFTP 执行</li>
          <li>全链路审计与风险管控</li>
          <li>企业级权限与加密体系</li>
        </ul>
      </div>
    </div>
    <div class="login-form-area">
      <div class="login-card">
        <div class="login-logo">
          <div class="logo-icon">MCP</div>
          <h2>Platform-MCP 管理平台</h2>
          <p>登录以访问管理控制台</p>
        </div>
        <el-form @submit.prevent="handleLogin" label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="username" placeholder="请输入用户名" size="large" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="password" type="password" placeholder="请输入密码" size="large" show-password />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" size="large" :loading="loading" style="width:100%" native-type="submit">登 录</el-button>
          </el-form-item>
        </el-form>
      </div>
      <p class="copyright">&copy; 2026 castle.zhang. All rights reserved.</p>
    </div>
  </div>
</template>

<style scoped>
.login-page { display: flex; min-height: 100vh; position: relative; }
/* 左侧产品区 — 完全对齐原型 */
.login-visual {
  width: 60%;
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #4338ca 100%);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  position: relative; overflow: hidden;
}
.login-visual::before {
  content: ''; position: absolute; width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(79,70,229,0.12) 0%, transparent 70%);
  top: -150px; right: -100px; border-radius: 50%;
}
.login-visual::after {
  content: ''; position: absolute; width: 400px; height: 400px;
  background: radial-gradient(circle, rgba(79,70,229,0.08) 0%, transparent 70%);
  bottom: -100px; left: -80px; border-radius: 50%;
}
.visual-content { position: relative; z-index: 1; text-align: center; color: #fff; padding: 40px; }
.visual-logo {
  width: 72px; height: 72px; background: var(--sidebar-active-bg);
  border-radius: 16px; display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 22px; margin-bottom: 24px;
}
.visual-content h1 { font-size: 32px; font-weight: 700; letter-spacing: 2px; margin-bottom: 12px; }
.visual-content .tagline { font-size: 15px; color: rgba(255,255,255,0.65); line-height: 1.6; }
.visual-features { margin-top: 40px; text-align: left; display: inline-block; list-style: none; }
.visual-features li {
  padding: 8px 0; font-size: 14px; color: rgba(255,255,255,0.75);
  display: flex; align-items: center; gap: 10px;
}
.visual-features li::before {
  content: ''; width: 6px; height: 6px; background: var(--sidebar-active-bg);
  border-radius: 50%; flex-shrink: 0;
}
/* 右侧表单区 — 完全对齐原型 */
.login-form-area {
  width: 40%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; background: var(--color-surface); position: relative;
}
.login-card { width: 380px; padding: 0; }
.login-logo { text-align: center; margin-bottom: 36px; }
.login-logo .logo-icon {
  width: 48px; height: 48px; background: var(--color-primary);
  border-radius: var(--radius-md); display: inline-flex; align-items: center;
  justify-content: center; color: #fff; font-weight: 700; font-size: 18px; margin-bottom: 12px;
}
.login-logo h2 { font-size: 22px; color: var(--color-text); font-weight: 600; letter-spacing: 1px; }
.login-logo p { color: var(--color-text-secondary); font-size: 13px; margin-top: 6px; }
.copyright {
  position: absolute; bottom: 24px; left: 0; width: 100%;
  text-align: center; font-size: 12px; color: var(--color-text-muted);
}
/* Element Plus form label — 对齐原型 .form-group label */
:deep(.el-form-item__label) {
  font-size: 13px; font-weight: 500; color: var(--color-text); padding-bottom: 0;
}
:deep(.el-form-item) { margin-bottom: 22px; }
</style>
