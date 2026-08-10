# Platform-MCP UI 样式规范

> **文档名称**：Platform-MCP UI 样式规范
> **基于文档**：《Platform-MCP 技术架构说明文档》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | V1.0 | 2026-08-08 12:00:00 | 正式发布 | 一期 + Server Skill 二期专项全量上线 | castle |
>
> **适用范围**：Platform-MCP 前端开发（Vue 3 + Element Plus + TypeScript）

---

## 零、前端开发态说明

### 0.1 项目结构

`Platform-MCP-frontend/` 是独立 Vite 项目，开发态默认端口 5173（占用自动递增到 5174/5175 等）。

### 0.2 开发态代理

所有页面通过 axios baseURL `/api/v1` 调后端，开发态靠 Vite proxy 转发：

```typescript
// vite.config.ts
server: {
  proxy: {
    '/api/v1': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

### 0.3 页面文件清单

| 页面 | 文件路径 |
|------|----------|
| 登录页 | `views/login/LoginPage.vue` |
| Skill 管理 | `views/skill/SkillPage.vue` |
| 数据源管理 | `views/datasource/DatasourcePage.vue` |
| 服务器管理 | `views/server/ServerPage.vue` |
| 审计日志 | `views/audit/AuditPage.vue` |
| 用户管理 | `views/user/UserPage.vue` |
| 个人设置 | `views/profile/ProfilePage.vue` |
| 密码加密 | `views/crypto/CryptoPage.vue` |
| MCP 接入指南 | `views/guide/McpGuidePage.vue` |

### 0.4 MainLayout 导航

`MainLayout.vue` 控制侧边栏分组：
- **管理中心**：Skill 管理、数据源管理、服务器管理、审计日志
- **系统管理**：用户管理、个人设置、密码加密
- **帮助**：MCP 接入指南

顶部面包屑自动生成当前路径导航。

---

## 一、设计令牌（Design Tokens）

### 1.1 CSS 变量 — 亮色主题（:root）

```css
:root {
  /* 主色 */
  --color-primary: #4f46e5;
  --color-primary-light: #6366f1;
  --color-primary-dark: #4338ca;

  /* 功能色 */
  --color-success: #059669;
  --color-warning: #d97706;
  --color-danger: #dc2626;
  --color-info: #2563eb;

  /* 表面 */
  --color-surface: #ffffff;
  --color-background: #f8fafc;
  --color-border: #e2e8f0;

  /* 文字 */
  --color-text: #1e293b;
  --color-text-secondary: #64748b;
  --color-text-muted: #94a3b8;

  /* 侧边栏 */
  --sidebar-bg: #1e1e2d;
  --sidebar-text: #a2a3b7;
  --sidebar-active-bg: #4f46e5;
  --sidebar-active-text: #ffffff;
  --sidebar-hover-bg: #2a2a3c;

  /* 尺寸 */
  --sidebar-width: 240px;
  --sidebar-brand-height: 56px;
  --sidebar-item-height: 40px;
  --header-height: 56px;
  --content-padding: 24px;

  /* 阴影 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);

  /* 圆角 */
  --radius-lg: 8px;
  --radius-md: 6px;
  --radius-sm: 4px;
}
```

### 1.2 CSS 变量 — 暗色主题（[data-theme="dark"]）

```css
[data-theme="dark"] {
  --color-primary: #818cf8;
  --color-primary-light: #6366f1;
  --color-primary-dark: #4338ca;
  --color-success: #34d399;
  --color-warning: #fbbf24;
  --color-danger: #f87171;
  --color-info: #60a5fa;
  --color-surface: #1e1e2e;
  --color-background: #151521;
  --color-border: #3a3a50;
  --color-text: #e2e8f0;
  --color-text-secondary: #94a3b8;
  --color-text-muted: #64748b;
  --sidebar-bg: #151523;
  --sidebar-active-bg: #818cf8;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
}
```

### 1.3 产品渐变

| 用途 | 值 |
|------|-----|
| 登录页背景 | `linear-gradient(135deg, #1e1b4b, #312e81, #4338ca)` |
| Logo 图标 | `linear-gradient(135deg, var(--primary), #7c3aed)` |

---

## 二、字体排版

### 2.1 字体族

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
```

### 2.2 字号层级

| 用途 | 字号 | 字重 | 行高 |
|------|------|------|------|
| 登录 Hero 标题 | 36px | 700 | 1.7 |
| 登录标题 | 24px | 600 | — |
| 页面标题 | 22px | 600 | — |
| 统计数值 | 28px | 700 | — |
| 正文 | 14px | 400 | 1.6 |
| 表格单元格 | 13px | 400 | — |
| 表格表头 | 12px | 600 | — |
| 导航项 | 13px | 400 | — |
| 按钮文字 | 13px | 500 | — |
| 徽章文字 | 12px | 500 | — |

---

## 三、间距系统

| 标度 | 值 | 用途 |
|------|-----|------|
| xs | 4px | 小组件间隙 |
| sm | 6px | 按钮间隙 |
| md | 8px | 面包屑、卡片操作 |
| lg | 12px | 导航间隙、筛选栏 |
| xl | 16px | 卡片间隙、内边距 |
| 2xl | 20px | 卡片内边距 |
| 3xl | 24px | 内容区域、模态框内边距 |

---

## 四、组件规范

### 4.1 按钮

| 变体 | 背景 | 文字 | 用途 |
|------|------|------|------|
| Primary | `var(--primary)` | `var(--on-primary)` | 主要操作 |
| Secondary | `var(--surface)` + `1px solid var(--border)` | `var(--text-primary)` | 次要操作 |
| Danger | `var(--danger)` | `#fff` | 危险操作 |

| 尺寸 | padding | 字号 | 最小高度 |
|------|---------|------|---------|
| Base | 8px 16px | 13px | 36px |
| Small | 6px 12px | 12px | 30px |

圆角：`var(--radius-sm)` (4px)。图标按钮：34px × 34px。

### 4.2 表单输入

| 属性 | 值 |
|------|-----|
| 高度 | 40px（登录 46px） |
| 内边距 | 0 12px |
| 边框 | 1px solid var(--border) |
| 圆角 | var(--radius-sm) (4px) |
| 焦点边框 | var(--primary) |
| 焦点光环 | 0 0 0 3px rgba(79,70,229,0.1) |

### 4.3 卡片

| 属性 | 值 |
|------|-----|
| 背景 | var(--surface) |
| 边框 | 1px solid var(--border) |
| 圆角 | var(--radius) (8px) |
| 悬停阴影 | var(--shadow-md) |

### 4.4 数据表格

| 属性 | 值 |
|------|-----|
| 表头背景 | var(--surface-alt) |
| 表头字号 | 12px/600 |
| 单元格字号 | 13px |
| 单元格内边距 | 12px 16px |
| 行悬停 | var(--surface-alt) |

### 4.5 模态框

| 属性 | 值 |
|------|-----|
| 宽度 | 90%，最大 700px |
| 最大高度 | 85vh |
| 圆角 | var(--radius) (8px) |

### 4.6 徽章（Badge）

| 变体 | 背景 | 文字 |
|------|------|------|
| Success | var(--success-light) | var(--success) |
| Warning | var(--warning-light) | var(--warning) |
| Danger | var(--danger-light) | var(--danger) |
| Info | var(--info-light) | var(--info) |

内边距：2px 10px，圆角：10px，字号：12px/500。

### 4.7 侧边栏导航

| 属性 | 值 |
|------|-----|
| 宽度 | 240px |
| 背景 | #1e1e2d |
| 产品区高度 | 56px |
| 导航项最小高度 | 40px |
| 激活背景 | var(--sidebar-active) |
| 图标尺寸 | 18px × 18px |

---

## 五、布局模式

### 5.1 登录页

双栏布局：左侧 60% 产品视觉区（产品名称、功能亮点）+ 右侧 40% 登录表单，底部版权说明。角色由用户名自动映射（admin/developer 双角色绑定用户账号），无需用户手动选择。

### 5.2 主应用

| 区域 | 规格 |
|------|------|
| 侧边栏 | 240px 固定宽度 |
| 头部 | 56px 高度，sticky |
| 内容区域 | padding: 24px |

### 5.3 响应式断点

| 断点 | 变化 |
|------|------|
| ≤ 1200px | 卡片网格 2 列 |
| ≤ 768px | 侧边栏隐藏（移动端滑出），登录左面板隐藏 |

---

## 六、图标规范

| 属性 | 值 |
|------|-----|
| 格式 | SVG，stroke 线条风格 |
| stroke-width | 2 |
| viewBox | 0 0 24 24 |

---

## 七、交互动效

### 7.1 过渡时长

| 速度 | 时长 | 用途 |
|------|------|------|
| 快 | 0.15s | 按钮、输入框 |
| 正常 | 0.2s | 背景、边框 |
| 慢 | 0.25s | 侧滑面板 |

### 7.2 Z-index 层级

| 层级 | 值 |
|------|-----|
| 头部 | 50 |
| 侧边栏 | 100 |
| 模态框遮罩 | 400 |
| Toast | 999 |

---

## 八、Platform-MCP 页面适配

### 8.1 一期 9 个核心页面（V1.0 含 Server Skill）

| 页面 | 优先级 | 关键 UI 要素 |
|------|--------|-------------|
| 登录页 | P0 | 双栏布局，角色由用户名自动映射 |
| Skill 管理页 | P0 | Skill 列表表格，启停开关，审核状态徽章，新增入口 |
| 数据源管理页 | P0 | 数据源列表，连接测试按钮，环境标识徽章 |
| 服务器管理页 | P0 | 服务器列表，SSH 连接测试，环境标识徽章，新增入口（仅 admin 可见） |
| 密码加密页 | P0 | 明文输入 → 密文输出，一键复制 |
| 审计日志页 | P0 | 时间/操作类型/用户筛选，日志详情弹窗 |
| 用户管理页 | P1 | 用户列表，角色分配（admin/developer） |
| 个人设置页 | P1 | 头像下拉菜单进入，显示名称/邮箱/修改密码 |
| MCP 接入指南页 | P1 | Claude Code 配置步骤，JSON 配置示例，FAQ |

### 8.2 侧边栏分组

| 分组 | 包含页面 | 可见角色 |
|------|---------|---------|
| 管理中心 | Skill 管理、数据源管理、服务器管理、审计日志 | admin + developer |
| 系统管理 | 密码加密、用户管理 | 仅 admin |
| 帮助 | MCP 接入指南 | admin + developer |

### 8.3 双角色显隐规则

| 页面 | admin | developer |
|------|-------|-----------|
| Skill 管理 | 查看 + 启停 + 审核 + 新增 | 查看 + 新增（待审核） |
| 数据源管理 | 查看 + 编辑 + 测试 + 新增 | 仅查看 + 测试连接 |
| 服务器管理 | 查看 + 编辑 + 测试 + 新增 | 仅查看 + 测试连接（新增按钮置灰） |
| 密码加密 | 可见 | 不可见 |
| 用户管理 | 可见 | 不可见 |
| 审计日志 | 全部记录 | 仅自己记录 |

---


### 8.6 二期功能 UI 呈现规范（V1.0）

二期功能（Skill 新增/上传、系统配置 CRUD、datasource 权限分配）在前端 `SkillPage.vue:94` 为 disabled + `title="二期功能"`。**UI 原型（`documents/ui/Platform-MCP-portal.html`）保留为完全可用 + `tag-warning` 二期标签**，与前端实际行为有意区分，便于产品评审完整看到二期边界。

**规范**：

| 元素 | 样式 | 行为 |
|---|---|---|
| 二期 nav 入口 | `.tag.tag-warning` 标 "二期" 文字 | 可点击进入页面 |
| 二期 button | 按钮右侧 `.tag.tag-warning` 标 "二期功能" | 可点击触发 modal |
| 二期 modal | 顶部加 `.tag.tag-warning` 提示 | mock 提交（`alert('二期功能：...')`） |

**禁止**：将二期功能在 UI 原型中置灰或隐藏，会丢失产品评审价值。


## 九、Element Plus 主题定制

中文语言包：`element-plus/es/locale/lang/zh-cn`
主题色覆盖：通过 CSS 变量覆盖默认主题
主题切换：`html.dark` 类名 + CSS 变量 + localStorage 持久化

---

## 十、设计一致性检查清单

- [ ] 颜色使用 CSS 变量，禁止硬编码色值
- [ ] 间距使用规范标度（4/6/8/12/16/20/24px）
- [ ] 圆角使用 var(--radius) 或 var(--radius-sm)
- [ ] 字号使用规范层级
- [ ] 暗色主题下所有组件可正常显示
- [ ] 角色权限控制菜单显隐正确
- [ ] 表格行悬停有高亮
