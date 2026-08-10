<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import request from "@/utils/request"
import { copyToClipboard } from "@/utils/clipboard"

interface ToolInfo { tool_name: string; display_name: string; description: string; risk_level: string }
interface SkillGroup {
  skill_code: string
  skill_name: string
  description: string | null
  register_method: string | null
  tool_count: number
  tools: ToolInfo[]
}
interface WhitelistInfo {
  local_dirs: string[]
  local_dirs_warning: string
  remote_per_server: string
}

const devConfigJson = ref("")
const prodConfigJson = ref("")
const prodReplaceHints = ref<string[]>([])
const skills = ref<SkillGroup[]>([])
const usage = ref<{ title: string; user_says: string; behavior: string }[]>([])
const usageTips = ref<string[]>([])
const whitelistInfo = ref<WhitelistInfo | null>(null)

async function fetchConfig() {
  const res = await request.get("/guide/config")
  const data = res.data as any
  devConfigJson.value = JSON.stringify(data.dev?.mcpServers, null, 2)
  prodConfigJson.value = JSON.stringify(data.prod?.mcpServers, null, 2)
  prodReplaceHints.value = data.prod?.replace_hints || []
}

async function fetchTools() {
  const res = await request.get("/guide/tools")
  skills.value = res.data as SkillGroup[]
}

async function fetchUsage() {
  const res = await request.get("/guide/usage")
  const data = res.data as any
  usage.value = data?.scenarios || []
  usageTips.value = data?.tips || []
  whitelistInfo.value = data?.current_whitelist || null
}

async function copyDevConfig() {
  const ok = await copyToClipboard(devConfigJson.value)
  ElMessage[ok ? "success" : "error"](ok ? "已复制 dev 配置" : "复制失败，请手动选中复制")
}

async function copyProdConfig() {
  const ok = await copyToClipboard(prodConfigJson.value)
  ElMessage[ok ? "success" : "error"](ok ? "已复制 prod 配置" : "复制失败，请手动选中复制")
}

function registerMethodLabel(m: string | null) {
  if (!m) return "—"
  const map: Record<string, string> = { decorator: "装饰器注册", form: "页面新增", upload: "源码上传" }
  return map[m] || m
}

function riskTagClass(level: string) {
  if (level === "CRITICAL" || level === "HIGH") return "tag-danger"
  if (level === "MEDIUM") return "tag-warning"
  return "tag-success"
}

const faqs = [
  { q: "MCP Server 启动失败 — module not found", a: "确认 Platform-MCP 已安装: pip install -e . 检查 PLATFORM_MCP_ENV 环境变量是否设置" },
  { q: "Oracle 连接错误 DPY-3010", a: "Oracle 11g 需要 thick 模式。确认 instant_client_dir 配置指向正确的 Oracle Instant Client 目录" },
  { q: "Tools 在 Claude Code 中不可见", a: "检查 Claude Code 的 MCP 配置 JSON 格式是否正确，command 路径是否为 python 的完整路径" },
  { q: "数据库连接测试超时", a: "检查网络连通性和防火墙规则，确认目标数据库允许从本机 IP 连接" },
  { q: "权限不足错误", a: "PROD 环境数据源仅 admin 角色可调用。确认当前角色和数据源环境标识正确" },
]

onMounted(() => { fetchConfig(); fetchTools(); fetchUsage() })
</script>

<template>
  <div>
    <div class="page-header">
      <h2>MCP 接入指南</h2>
      <p>如何将 Platform-MCP 接入 Claude Code 等 MCP 客户端</p>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
      <!-- prod: streamable-http -->
      <div class="card" style="border-left:3px solid var(--color-primary)">
        <div class="guide-section">
          <h3 style="display:flex;align-items:center;gap:8px"><span class="tag tag-success" style="font-size:12px">推荐</span> 远程服务器部署</h3>
          <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">streamable-http 模式，适用于已部署到 Linux 服务器的生产环境。</p>
          <ol class="guide-steps">
            <li>获取部署服务器的实际 IP 或域名（如 <code>192.168.1.100</code> / <code>mcp.example.com</code>），替换下方配置中的 <code>&lt;your-server-ip&gt;</code></li>
            <li>在 Web 管理端登录 → "个人设置" 查看你的 API Key</li>
            <li>复制 API Key，替换下方配置中的 <code>&lt;your-api-key&gt;</code></li>
            <li>将配置写入 Claude Code 配置文件：<code style="background:var(--color-background);padding:1px 4px;border-radius:2px">~/.claude.json</code></li>
            <li>重启 Claude Code 即可自动连接</li>
          </ol>
          <p style="font-size:13px;font-weight:500;color:var(--color-text);margin-top:16px;margin-bottom:8px">配置写入 ~/.claude.json：</p>
          <div class="code-block">
            <button class="btn btn-sm" style="position:absolute;top:8px;right:8px;background:rgba(255,255,255,0.1);color:#fff;border-color:transparent" @click="copyProdConfig">复制</button>
            <pre>{{ prodConfigJson || '{}' }}</pre>
          </div>
          <div v-if="prodReplaceHints.length > 0" style="margin-top:12px;padding:8px 12px;background:var(--color-background);border-radius:4px;font-size:12px;color:var(--color-text-secondary)">
            <div style="font-weight:500;color:var(--color-text);margin-bottom:4px">替换提示：</div>
            <ul style="margin:0;padding-left:20px">
              <li v-for="h in prodReplaceHints" :key="h" style="margin-bottom:2px;font-family:monospace">{{ h }}</li>
            </ul>
          </div>
        </div>
      </div>
      <!-- dev: stdio -->
      <div class="card" style="border-left:3px solid var(--color-warning)">
        <div class="guide-section">
          <h3 style="display:flex;align-items:center;gap:8px"><span class="tag tag-warning" style="font-size:12px">仅限本机</span> 本地开发调试</h3>
          <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">stdio 模式，Claude Code 与本机 MCP Server 通过子进程通信。不对外开放。</p>
          <ol class="guide-steps">
            <li>确认本机已安装 Python 3.11.9+ 及所有依赖</li>
            <li>在本机运行 <code>python -m platform_mcp.mcp_server</code> 确认可启动</li>
            <li>将配置写入 Claude Code 配置文件：<code style="background:var(--color-background);padding:1px 4px;border-radius:2px">~/.claude.json</code></li>
          </ol>
          <p style="font-size:13px;font-weight:500;color:var(--color-text);margin-top:16px;margin-bottom:8px">配置示例（仅本机开发）：</p>
          <div class="code-block">
            <button class="btn btn-sm" style="position:absolute;top:8px;right:8px;background:rgba(255,255,255,0.1);color:#fff;border-color:transparent" @click="copyDevConfig">复制</button>
            <pre>{{ devConfigJson || '{}' }}</pre>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>使用建议</h3>
        <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">
          通过 Claude Code 调用 Platform-MCP 执行 SQL 或 Shell/SFTP 操作时，可以用以下方式指定数据源/服务器，Claude 会按场景自动解析并选择对应 skill（database / server）。
        </p>
        <table class="data-table">
          <thead><tr><th style="width:160px">场景</th><th style="width:300px">示例指令</th><th>Claude 行为</th></tr></thead>
          <tbody>
            <tr v-for="s in usage" :key="s.title">
              <td>{{ s.title }}</td>
              <td class="text-mono">{{ s.user_says }}</td>
              <td>{{ s.behavior }}</td>
            </tr>
            <tr v-if="usage.length === 0"><td colspan="3" style="text-align:center;color:var(--color-text-secondary);padding:24px 0">加载中...</td></tr>
          </tbody>
        </table>
        <ul style="margin-top:16px;font-size:13px;color:var(--color-text-secondary);padding-left:20px">
          <li v-for="t in usageTips" :key="t" style="margin-bottom:4px">{{ t }}</li>
        </ul>
        <div v-if="whitelistInfo" style="margin-top:16px;padding:12px;background:var(--color-background);border-radius:4px;border-left:3px solid var(--color-warning)">
          <div style="font-weight:500;color:var(--color-text);margin-bottom:6px">当前路径白名单状态</div>
          <div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:4px">
            <span style="font-weight:500">本地（settings.allowed_sql_dirs）：</span>
            <code style="background:var(--color-border);padding:1px 4px;border-radius:2px">{{ whitelistInfo.local_dirs.length ? JSON.stringify(whitelistInfo.local_dirs) : '[]（空）' }}</code>
          </div>
          <div style="font-size:12px;color:var(--color-warning);margin-bottom:4px">{{ whitelistInfo.local_dirs_warning }}</div>
          <div style="font-size:12px;color:var(--color-text-secondary)">{{ whitelistInfo.remote_per_server }}</div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>已注册 Skill 及可用 Tool</h3>
        <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">MCP Server 启动后，以下 Skill 的 Tool 将自动注册到 MCP 客户端，可直接调用。</p>
        <table class="data-table">
          <thead><tr>
            <th>Skill 编码</th><th>Skill 名称</th><th>注册方式</th><th>Tool 数量</th><th>支持 Tool 列表</th><th>说明</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in skills" :key="s.skill_code">
              <td class="text-mono">{{ s.skill_code }}</td>
              <td>{{ s.skill_name }}</td>
              <td><span class="tag tag-primary">{{ registerMethodLabel(s.register_method) }}</span></td>
              <td>{{ s.tool_count }}</td>
              <td>
                <span v-for="t in s.tools" :key="t.tool_name" class="tag"
                  :class="riskTagClass(t.risk_level)" :title="`${t.display_name} — ${t.description}（风险: ${t.risk_level}）`"
                  style="margin:2px;display:inline-flex">
                  {{ t.tool_name }}
                </span>
                <span v-if="s.tools.length === 0" style="color:var(--color-text-muted)">—</span>
              </td>
              <td>{{ s.description || '—' }}</td>
            </tr>
            <tr v-if="skills.length === 0"><td colspan="6" style="text-align:center;color:var(--color-text-secondary);padding:24px 0">尚未注册 Skill</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="guide-section">
        <h3>环境要求</h3>
        <table class="data-table">
          <thead><tr><th>项目</th><th>要求</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td>Python</td><td>3.11.9+</td><td>后端运行环境锁定版本</td></tr>
            <tr><td>Oracle Instant Client</td><td>11g 64-bit</td><td>连接 Oracle 数据源必需（thick 模式）</td></tr>
            <tr><td>目标数据库网络</td><td>可达</td><td>MCP Server 需连通 Oracle / MySQL 端口</td></tr>
            <tr><td>目标服务器网络</td><td>可达</td><td>MCP Server 需连通目标 Linux 服务器的 SSH/SFTP 端口</td></tr>
            <tr><td>MCP 客户端</td><td>Claude Code / Desktop</td><td>支持 stdio + streamable-http 的 MCP 客户端</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="guide-section">
        <h3>常见问题</h3>
        <div class="faq-item" v-for="(faq, i) in faqs" :key="i" @click="($event.currentTarget as HTMLElement)?.classList?.toggle('open')">
          <div class="faq-q">{{ faq.q }}</div>
          <div class="faq-a">{{ faq.a }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.faq-a { display: none; }
.faq-item.open .faq-a { display: block; }
</style>
