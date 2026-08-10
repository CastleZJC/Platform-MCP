# Platform-MCP

> 内部 MCP (Model Context Protocol) 能力平台
> 一期聚焦数据库 Skill — 通过 Claude Code 等调用方执行 SQL，配备 Web 管理台

## 项目概览

Platform-MCP 是一个内部 MCP 服务平台，提供：

- **Database Skill**：通过 MCP 工具执行本地 SQL 文件或 SQL 文本
- **双传输 MCP Server**：stdio（环境变量）+ streamable-http（Header）双入口
- **API Key 认证**：双存储（key_hash SHA-256 + key_encrypted AES-GCM）
- **Web 管理台**：数据源配置、用户管理、API Key 管理、审计日志
- **权限控制**：admin/developer 双角色，developer 禁 PROD
- **风险引擎**：4 级（LOW/MEDIUM/HIGH/CRITICAL），HIGH+ 需二次确认

## 快速启动

### 前置要求

- Python 3.11.9
- PostgreSQL 16.4（系统库）
- Oracle 11g / MySQL 5.6（目标库，可选）

### 后端启动

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动 FastAPI Web（默认端口 8000，可配置）
python -m platform_mcp.main

# 启动 MCP Server（mode 由 settings.mcp.transport 决定）
python -m platform_mcp.mcp_server
```

### 前端启动

```bash
cd Platform-MCP-frontend
npm install
npm run dev    # 默认端口 5173（占用自动递增）
```

访问 `http://localhost:5173`，默认账号：`admin` / `admin123`

### 数据库初始化

```bash
# 生成加密密钥 + Alembic 升级 + 检查 seed 用户
python scripts/_setup_local.py

# 种 database skill 到 pmcp_skill 表
python scripts/_seed_skill.py
```

## 技术栈

**后端**：Python 3.11.9 + FastAPI 0.115.0 + SQLAlchemy 2.0.35 + Alembic 1.13.2 + oracledb 2.4.1 + aiomysql 0.2.0

**前端**：Vue 3.5.34 + Vite 8.0.12 + TypeScript 6.0.2 + Element Plus 2.8.1 + Pinia 2.2.2 + Axios 1.7.4

**数据库**：PostgreSQL 16.4（系统），Oracle 11g / MySQL 5.6（目标）

## 架构（简化）

```
Claude Code ──stdio(env PLATFORM_MCP_API_KEY)──▶ MCP Server ──┐
           ╲                                        ├──▶ PostgreSQL / Oracle / MySQL
            ╲                                       │
Claude Code ──HTTP(header PLATFORM_MCP_API_KEY)──▶ ──┤
                                                │
Browser ──HTTP(session cookie)──▶ FastAPI Web ──┘
```

## 目录结构

```
Platform-MCP/
├── platform_mcp/           # 后端代码
│   ├── api/             # FastAPI 路由（9 模块）
│   ├── auth/            # 认证鉴权 + API Key
│   ├── datasource/      # 数据源管理
│   ├── skills/          # Skill 实现（database）
│   ├── mcp_server/      # MCP 协议 + 双传输
│   ├── audit/           # 审计日志
│   └── common/          # 公共组件
├── Platform-MCP-frontend/  # 前端代码（Vue 3）
├── tests/               # 后端测试（440 用例）
├── scripts/             # 工具脚本
├── alembic/             # 数据库迁移
├── documents/           # 设计文档
└── poc/                 # POC 验证
```

## 文档索引

| 文档 | 说明 |
|------|------|
| `CLAUDE.md` | Claude Code 工作指南（项目整体原则） |
| `documents/design/Python：# Platform-MCP 技术架构说明文档.md` | 技术架构（权威来源） |
| `documents/design/Python：# Platform-MCP 代码规范.md` | 编码规范 |
| `documents/design/Python：# Platform-MCP 部署规范.md` | 生产部署 |
| `documents/design/Python：# Platform-MCP 测试规范文档.md` | 测试策略 |
| `documents/design/文档审核指南.md` | 文档审核规则 |
| `documents/ui/Platform-MCP-portal.html` | UI 原型（单文件 HTML） |

## 测试

```bash
# 后端（440 用例，覆盖率 95.96%）
python -m pytest tests/ --ignore=tests/performance --cov=platform_mcp

# 前端（92 用例）
cd Platform-MCP-frontend
npm run test
```

## 配置

- `settings.yml`：主配置文件
- `settings-{env}.yml`：环境配置（dev/test/prod）
- `crypto-secret.key`：AES 密钥（`scripts/_setup_local.py` 生成）

## 许可

内部项目，不对外开放。
