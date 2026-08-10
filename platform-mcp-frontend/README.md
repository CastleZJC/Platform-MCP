# Platform-MCP-frontend

Platform-MCP 管理台前端（Vue 3 + Element Plus）

## 技术栈

- **框架**：Vue 3.5.34 + TypeScript 6.0.2
- **构建工具**：Vite 8.0.12
- **UI 组件库**：Element Plus 2.8.1
- **状态管理**：Pinia 2.2.2
- **HTTP 客户端**：Axios 1.7.4

## 开发启动

```bash
# 安装依赖
npm install

# 启动开发服务器（默认端口 5173，占用自动递增到 5174/5175 等）
npm run dev

# 构建
npm run build

# 测试（92 用例）
npm run test
```

访问前端页面：`http://localhost:5173`（或实际绑定端口）

## 后端代理配置

开发态通过 Vite proxy 转发 `/api/*` 请求到后端服务。

代理配置在 `vite.config.ts`：

```typescript
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',  // 后端地址（可按需调整）
      changeOrigin: true,
    },
  },
}
```

**部署时**：生产环境由 Nginx 处理反向代理，无需 Vite proxy。

## 目录结构

```
src/
├── views/          # 页面组件
│   ├── login/      # 登录页
│   ├── skill/      # Skill 管理
│   ├── datasource/ # 数据源管理
│   ├── audit/      # 审计日志
│   ├── user/       # 用户管理
│   ├── profile/    # 个人设置
│   ├── crypto/     # 密码加密
│   └── guide/      # MCP 接入指南
├── stores/         # Pinia stores
├── utils/          # 工具函数
├── router/         # 路由配置
├── components/     # 公共组件
└── styles/         # 全局样式
```

## UI 规范

所有页面必须严格对齐 `documents/ui/Platform-MCP-portal.html` 原型。

详见：`documents/design/Python：# Platform-MCP UI 样式规范.md`

## 默认账号

- 用户名：`admin`
- 密码：`admin123`