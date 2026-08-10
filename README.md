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
│   ├── api/             # FastAPI 路由（10 模块）
│   ├── auth/            # 认证鉴权 + API Key
│   ├── datasource/      # 数据源管理
│   ├── skills/          # Skill 实现（database）
│   ├── mcp_server/      # MCP 协议 + 双传输
│   ├── audit/           # 审计日志
│   └── common/          # 公共组件
├── Platform-MCP-frontend/  # 前端代码（Vue 3）
├── tests/               # 后端测试（525 用例）
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
| `CLAUDE.md` § 文档审核标准 | 文档审核规则（嵌入 CLAUDE.md） |
| `documents/ui/Platform-MCP-portal.html` | UI 原型（单文件 HTML） |

## 版本迭代

> **基线 V1.0 = 2026-08-08**。后续生产发布（含 hotfix、迭代版本、配置类变更上线）必须在此表追加一行——详见 `CLAUDE.md §部署原则 #10`。

| 版本 | 日期 | 类型 | 摘要 | 修改人 |
|------|------|------|------|--------|
| V1.0.1 | 2026-08-09 | hotfix | 审计日志失败记录完整性增强（合并两次细粒度修复为同日 hotfix）：**（1）error_code 强制捕获**——`call_log.py` PmcpMcpCallLog 构造补 `error_code=error_code`（修前 mcp_call_log 全表 error 行 0/5 有码）；`auth.py` login fail 补 `error_code="11001"`；`crypto.py` encrypt/verify fail 补 `error_code="15001"`；`profile.py` change-password fail 补 `error_code="11004"`。**（2）result_status 枚举统一**——web 层 6 文件 8 处 `'fail'` → `'error'`（auth/crypto/profile/datasources/servers）+ UI `statusLabel` 防御性同时识别 fail/error → 失败 + `audit/models.py` 列 comment 更新为 `(success/error)`。**（3）历史数据 backfill**——UPDATE fail→error 共 2 行 + NULL error_code 按错误信息模式匹配 backfill 6 行（11001/12001/10001/15001），最终态 0 fail 残留 + error 行 error_code 完整率 100%。生产验证：castle.zhang 4 行登录失败记录全 error/11001 ✓；castle.zhang MCP 失败 → audit_log + mcp_call_log 双表 error_code=12001 ✓ | castle |
| V1.0 | 2026-08-08 | 基线发布 | 一期 + Server Skill 二期专项全量上线：11 MCP tools（database 5 + server 6）、15 系统表、9 前端页面、双传输 MCP（stdio + streamable-http）、API Key 双存储（hash + encrypted）。生产已部署 192.168.1.100，23/23 验证用例全过（详见 `documents/aduit/20260808_mcp_verify_report_2.md`） | castle |

## 测试

```bash
# 后端（525 用例，覆盖率 95.96%）
python -m pytest tests/ --ignore=tests/performance --cov=platform_mcp
mypy platform_mcp/    # 类型检查（V1.0 新增）

# 前端（110 用例）
cd Platform-MCP-frontend
npm run test
```

## 配置

- `settings.yml`：主配置文件
- `settings-{env}.yml`：环境配置（dev/test/prod）
- `crypto-secret.key`：AES 密钥（`scripts/_setup_local.py` 生成）

## 许可

本项目基于 **MIT License** 开源，详见 [LICENSE](LICENSE)。

### 第三方依赖开源许可

本项目使用以下开源组件，各组件遵循其原始许可协议：

| 类别 | 组件 | 许可协议 |
|---|---|---|
| 后端框架 | FastAPI、Pydantic、SQLAlchemy、Alembic、Uvicorn、Gunicorn、loguru | MIT |
| 数据库驱动 | oracledb | Apache 2.0 |
|  | aiomysql | MIT |
|  | psycopg2-binary | LGPL-3.0 |
| 加密 | cryptography | Apache-2.0 OR BSD-3-Clause |
| HTTP 客户端 | httpx | BSD-3-Clause |
| MCP 协议 | mcp SDK | MIT |
| 配置/工具 | PyYAML、tenacity、sqlparse | MIT / BSD / Apache-2.0 |
| 前端框架 | Vue、Vite、Pinia、Vue Router、Axios | MIT |
| 类型系统 | TypeScript | Apache-2.0 |
| UI 组件库 | Element Plus | MIT |

### 商业数据库许可说明

Platform-MCP 支持连接 Oracle 11g 与 MySQL 5.6 作为**目标数据库**，使用方需自行获取相应数据库的合法授权与许可，本项目不包含也不提供任何商业数据库的许可。Oracle 驱动（oracledb）的 thick 模式依赖 Oracle Instant Client，需另行下载并遵守 Oracle 的许可协议。
