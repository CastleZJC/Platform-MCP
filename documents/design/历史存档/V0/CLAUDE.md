# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Platform-MCP is an internal MCP (Model Context Protocol) capability platform. Phase 1 focuses on database Skill — executing SQL via MCP tools called from Claude Code, with a Web management portal for datasource config, user/auth, encryption, and audit logging.

**Project state**: Phase 1-5 complete + Server Skill 二期专项（Linux SSH/SFTP）已落地。Application code, tests (**525 backend** pytest + **110 frontend** vitest), and management portal all implemented. API Key authentication and dual-transport (stdio + streamable-http) MCP Server are live. 11 MCP tools across 2 skill packages (database 5 + server 6). POC verification tests remain in `poc/`.

## Architecture

**Dual-entry monolithic Python app with shared business logic:**

```
Claude Code ──stdio(env PLATFORM_MCP_API_KEY)──▶ MCP Server (mcp_server/__init__.py)  ──┐
                       ╲                                                                ├──▶ skills/ datasource/ audit/ common/ (shared logic)
                        ╲                                                              │
Claude Code ──HTTP(header PLATFORM_MCP_API_KEY)──▶ MCP Server (streamable-http)         ──┤
                                                                              │       │
Browser ──HTTP(session cookie)──▶ FastAPI Web (main.py)                       ──┐    ├──▶ PostgreSQL 16.4 (system DB, ORM)
                                                                                │    ├──▶ Oracle 11g (target DB, thick mode, raw driver)
                                                                                │    └──▶ MySQL 5.6 (target DB, aiomysql)
                            ↕ API Key 校验 (validate_api_key)                   │
                            pmcp_api_key (key_hash + key_encrypted)  ◀──────────┘
```

- **MCP Server** (`mcp_server/__init__.py`): dual transport. stdio mode (env var) OR streamable-http mode (ASGI middleware reads `PLATFORM_MCP_API_KEY` header). `settings.mcp.transport` switches modes.
- **FastAPI Web** (`main.py`): REST API for management portal (auth, datasource CRUD, API Key management, encryption, audit queries). Runs via Gunicorn + Uvicorn workers.
- **Shared logic**: Both entries use the same skill registry (`mcp_server/skill/registry.py`), SQL executor (`skills/database/executor.py`), risk engine (`skills/database/risk.py`), datasource manager (`datasource/manager.py`), and crypto module (`common/crypto.py`).
- **Identity propagation**: API Key 校验结果存入 `contextvars.ContextVar` (`mcp_server/__init__.py:_mcp_identity_var`)。`McpContext.operator` 从中读取，未校验时回退 `mcp://{settings.mcp.operator_role}`。HTTP 模式每请求独立，stdio 模式进程级绑定.
- **Key constraint**: Database Skill logic must not leak into `mcp_server` — it only handles protocol, param normalization, context wrapping, and response formatting.

> 详见：`技术架构说明文档.md §配置系统与共享基础设施`

## API Key Authentication

API Key 是 MCP 层用户级认证的唯一机制，区别于 Web 层的 session cookie 认证。

| 层 | 认证机制 | 凭证载体 |
|----|---------|---------|
| Web (FastAPI) | Session (server-side) | `session_id` cookie |
| MCP (stdio) | API Key 校验 | `PLATFORM_MCP_API_KEY` 环境变量 |
| MCP (streamable-http) | API Key 校验 | `PLATFORM_MCP_API_KEY` HTTP Header |

**Key 存储设计** (`pmcp_api_key` 表，migration `ce0101a947f3` + `cf0101a947f4`):
- `key_hash` (SHA-256, 不可逆): 用于校验
- `key_encrypted` (AES-GCM, 可逆): 用于 admin reveal 明文（hash-only 历史记录此列为 NULL，reveal 返回 code=1 提示需 reset）
- `key_prefix`: raw_key[:10]，用于列表识别
- Key 格式：`pmcp_` + `secrets.token_urlsafe(32)`（约 48 字符）

**Self-or-admin reveal** (`GET /api-keys/full/{user_id}`): admin 可查任意用户明文；普通用户只能查自己。`get_full_key_by_user` 按 `inserted_at DESC` 取最新活跃 key。

**Admin 重置** (`POST /api-keys/reset/{user_id}`): 撤销该用户所有活跃 key + 生成新 key。

## Planned Module Layout

| Package | Responsibility |
|---|---|
| `platform_mcp.api` | FastAPI REST endpoints (10 modules: auth/users/datasources/servers/api_keys/skills/audit/crypto/profile/guide). `/api/v1/health` 注册在 `main.py:114`（非独立 api 模块）。 |
| `platform_mcp.auth` | Login, user/role/permission, session, **API Key (models + service)** |
| `platform_mcp.datasource` | Datasource CRUD, environment mgmt, password encryption |
| `platform_mcp.server` | Server CRUD (Linux SSH targets), credential encryption, mirrors `datasource/` |
| `platform_mcp.mcp_server` | MCP protocol, tool registration, skill routing, **dual-transport + auth middleware** |
| `platform_mcp.skills.database` | SQL executor, risk engine, MCP tools (execute_sql_file, execute_sql_text, validate_sql, list_datasources, get_execution_status) |
| `platform_mcp.skills.server` | SSH/SFTP executor, shell risk engine, MCP tools (execute_command, upload_file, download_file, list_servers, validate_command, get_server_execution_status) |
| `platform_mcp.skills.common` | Shared risk types (RiskLevel/RiskResult) + env permission check, used by database + server |
| `platform_mcp.audit` | Audit log recording, call stats, service status |
| `platform_mcp.common` | Exceptions, response models, enums, utilities |

Dependency direction: `api → auth / datasource / skills → audit → common`. No reverse dependencies.

## 一期已完成功能 vs 二期规划（避免擅自二期，文档与代码对齐）

### 一期已完成
- Database Skill（5 tools：execute_sql_text/file、validate_sql、list_datasources、get_execution_status）
- API Key 双存储（`key_hash` SHA-256 + `key_encrypted` AES-GCM admin reveal）
- 双传输 MCP Server（stdio + streamable-http，`PLATFORM_MCP_API_KEY` 环境变量 / HTTP Header）
- 审计日志全覆盖（25 处 `write_audit_log` 调用，7 个 api 模块）
- 角色级权限（admin / developer 双角色，developer 禁 PROD）
- 风险引擎 4 级（LOW/MEDIUM/HIGH/CRITICAL，HIGH+ 需要 `confirm_token` 反重放）
- 异步执行（**自动判定**：SQL 内容 >5000 字符 或 多语句文件 >3 条 → 自动转异步返回 execution_id；用户无需选 `async_exec` 参数 + 状态轮询 + 30 分钟 TTL）

### 一期后增补（Server Skill 二期专项，2026-08-07）
- **Server Skill（Linux SSH/SFTP，6 tools）**：execute_command / upload_file / download_file / list_servers / validate_command / get_server_execution_status
- **新增模块**：`platform_mcp/server/`（model + manager）+ `platform_mcp/skills/server/`（skill + connection + executor + risk + confirm）+ `platform_mcp/skills/common/`（risk_types + permission，database 与 server 共用）
- **新增依赖**：`asyncssh==2.17.0`（pure Python，复用 cryptography）
- **新增表**：`pmcp_server` + `pmcp_server_permission`（migration `ch0101a947f6`）
- **Shell 风控 4 级**：CRITICAL（rm -rf /、mkfs、dd、fork bomb、shutdown...）/ HIGH（sudo、systemctl stop...）/ MEDIUM（curl、nohup、| sh...）/ LOW（ls、cat、grep...）；PROD 自动升 CRITICAL
- **新增 API**：`/api/v1/servers`（5 端点：list/create/update/status/test，镜像 datasource）
- **新增前端页**：`ServerPage.vue`（菜单"服务器管理"，角色过滤同 datasource）
- **审计 resource_type**：`server` 已加入 AuditPage 标签映射

### 二期规划（一期不实施，文档与代码已对齐）
| # | 功能 | 开发计划位置 | 当前实现状态 |
|---|---|---|---|
| 1 | Skill 表单/源码上传 | L497 | `api/skills.py:create_skill` 返回 501；前端 `SkillPage.vue:94` 置灰按钮 title="二期功能" |
| 2 | 数据源权限分配（用户↔环境↔数据源三维） | L498 | 表 `pmcp_datasource_permission` 已建 + ORM 已定义（`datasource/models.py:32`），业务逻辑/API 二期补 |
| 3 | 系统配置管理 API（CRUD `pmcp_system_config`） | L499 | 表已建 + ORM 已定义（`common/models.py:9`），REST API 二期补（一期用 YAML 配置） |

### 不做规划（第三期或独立需求）
- SQL 类型级权限控制（用户对某数据源只能 SELECT，不能 DDL/DML）

## Development Commands

```bash
# Backend
pip install -e ".[dev]"                    # Install with dev dependencies

python -m pytest tests/ -q                 # Run all tests
python -m pytest tests/unit/test_crypto.py -q   # Run single test file
python -m pytest tests/ -k "test_encrypt" -q    # Run tests matching name
python -m pytest tests/ --ignore=tests/performance --cov=platform_mcp --cov-report=term-missing -q  # Coverage (excludes perf)
python -m pytest --cov=platform_mcp --cov-report=json -q && python scripts/check_coverage.py  # Per-module coverage gates

python -m platform_mcp.main                   # Start FastAPI web server (port 8000)
python -m platform_mcp.mcp_server             # Start MCP server (mode per settings.mcp.transport)

# Alembic migrations
python -m alembic upgrade head             # Apply pending migrations
python -m alembic revision -m "msg" --autogenerate  # Create new revision

# Frontend
cd Platform-MCP-frontend
npm install
npm run dev                                # Start Vite dev server (port 5173, auto-increment if taken)
npx vitest run --coverage                  # Run frontend tests with coverage
> 详见：`测试规范文档.md §测试架构`

# Local seed / verify scripts (run from repo root, DB must be up)
python scripts/_setup_local.py             # 生成 crypto-secret.key + Alembic upgrade head + 检查 seed 用户
python scripts/_seed_skill.py              # 种 database skill 到 pmcp_skill 表（5 tools）
python scripts/_import_poc_datasources.py  # 导入 Oracle APP-SAMPLE-1 + MySQL APP-SAMPLE-2 数据源
python scripts/_check_admin.py             # 校验 admin 用户密码哈希
python scripts/_reset_admin_pwd.py         # 重置 admin 密码为 admin123（bcrypt）
python scripts/_verify_imports.py          # 验证所有新模块可成功 import（非数据校验）
python scripts/_test_mcp_auth.py           # 测 MCP 全链路：API Key 认证 + 数据源 + SQL 执行
```

## Tech Stack (pinned versions)

**Backend:** Python 3.11.9 (locked across all environments), FastAPI 0.115.0, Pydantic 2.8.2, SQLAlchemy 2.0.35 (AsyncSession + asyncpg), Alembic 1.13.2, oracledb 2.4.1, aiomysql 0.2.0, cryptography 43.0.1, mcp SDK 1.9.4, loguru 0.7.2, httpx 0.27.2, tenacity 9.0.0, PyYAML 6.0.2, Uvicorn 0.30.6, Gunicorn 23.0.0, psycopg2-binary 2.9.9 (scripts/ 同步脚本用), sqlparse 0.5.0 (SQL 文件多语句分句)

**Frontend:** Vue 3.5.34 + Vite 8.0.12 + TypeScript 6.0.2 + Element Plus 2.8.1 + Pinia 2.2.2 + Axios 1.7.4

**Databases:** PostgreSQL 16.4 (system), Oracle 11g (target), MySQL 5.6 (target)

**Infra:** Rocky Linux 9.4, Nginx 1.26.1, systemd, no Docker/K8s

## Critical Architectural Decisions

- **Oracle 11g requires thick mode**: `oracledb` thin mode only supports Oracle 12.1+. Use `oracledb.init_oracle_client(lib_dir=...)` then wrap sync calls with `asyncio.run_in_executor` for FastAPI async endpoints.
- **No sync drivers in async endpoints**: All DB access in FastAPI must use async drivers (asyncpg for PostgreSQL, aiomysql for MySQL, run_in_executor for Oracle thick mode).
- **SQLAlchemy 2.0 style only**: Use `select()` not `session.query()`, `AsyncSession` only, no 1.x patterns.
- **Pydantic v2 style only**: `@field_validator`, `model_dump()`, `model_config = ConfigDict(...)`.
- **Target DB connections are ephemeral**: No long-lived connection pools for Oracle/MySQL. Use `asynccontextmanager` for connect→execute→close per request, with `asyncio.Semaphore` per datasource (default max 5 concurrent).
- **System DB (PostgreSQL) uses SQLAlchemy ORM**: Target DBs (Oracle/MySQL) use raw driver calls, not ORM.
- **Session-based web auth** (not JWT): Server-side sessions with cookie-based session ID. Frontend uses `withCredentials: true`. MCP 层用 API Key（hash + encrypted 双存储）。
- **MCP API Key 双存储**: `key_hash` 用于校验（不可逆），`key_encrypted` 用于 admin reveal（AES 可逆）。新增 key 必须同时写两列（`generate_api_key` 已处理）。
- **每环境独立 crypto key**：`crypto-secret.key`（32 raw bytes）按 dev / test / prod 环境独立生成，**绝不跨环境共享或拷贝**；`.gitignore` 已通过 `*.key` 规则排除；权限 `0600`；环境间迁移加密数据时必须用源 key 解密 + 目标 key 重新加密（不传输明文，例见 `remote/import_poc_inline.py`）。

## 部署原则（Production Deployment Principle）

**核心原则：必须无问题上生产（No issues to production）**

部署到生产环境前必须满足以下全部条件，**缺一不可，不得带病上线**：

1. **类型检查全过**：后端 `mypy`（如启用）+ 前端 `vue-tsc -b` 必须 0 错误。
2. **构建成功**：后端 `pip install -e .` + 前端 `npm run build`（含 vue-tsc）必须成功，不允许跳过 vue-tsc 仅跑 vite build。
3. **测试全过**：后端 pytest + 前端 vitest 全部通过，**包括 teardown 阶段的 unhandled rejection**；测试断言与组件代码必须同步（不允许"测试期望 4 实际 5"这类陈旧断言）。
4. **无死代码**：未使用的 import / 变量 / 函数必须删除（TS6133 strict 不可禁用）。
5. **生产代码 async 必须正确**：所有 `async` 函数内的异步调用必须正确 `await`，不允许 fire-and-forget。
6. **类型不撒谎**：runtime 行为与 TS/Python 类型签名必须一致；如不一致，必须修正类型签名（如 `request.ts` interceptor 用 `as unknown as AxiosResponse` cast 而非 `any`）。
7. **依赖图完整**：`pyproject.toml` 必须列出全部直接依赖（含 passlib 验证 bcrypt 哈希所需的 `bcrypt` 包）；`pip install` 必须 full resolver 模式（**不能 `--no-deps`**）成功。
8. **冒烟全过**：健康检查、前端首页、MCP 鉴权、MCP 接入 4 项必须 curl 实测通过。
9. **服务自启**：crontab `@reboot` 必须配置；备份 cron（每日 pg_dump）必须配置。

**禁止行为**：
- 禁止跳过 vue-tsc / pytest / vitest
- 禁止用 `as any` 掩盖类型错误
- 禁止保留"pre-existing issue"借口（部署期发现的所有问题必须修复或显式决策后才能上线）
- 禁止传明文敏感数据跨环境（必须 re-encrypt）
- 禁止 crypto key 跨环境复用

**遇到问题的处理流程**：
1. 优先修代码（生产代码 > 测试代码 > 文档）
2. 修复后必须回归（重跑 vue-tsc + 全量测试）
3. 文档同步更新（部署规范、CLAUDE.md、deployment-record-*.md）
4. 真正的决策点（如版本冲突需选型、依赖包不可用）才中断请用户决策

## Key Conventions

- **Git commits**: `<type>: <description in Chinese> yyyymmdd by castle` (types: feat/fix/refactor/docs/test/chore)
- **Unified response format**: 5 fields — `code`, `message`, `data`, `trace_id`, `timestamp` (Unix ms)
- **Encryption ciphertext format**: `AES:base64(iv+ciphertext+tag)` prefix in DB fields; `AES-CBC:...` for legacy; no prefix = plaintext passthrough
- **High-risk SQL confirmation**: `confirm_token` (one-time server-generated token, anti-replay) — NOT a boolean flag
- **Risk levels**: LOW / MEDIUM / HIGH / CRITICAL — HIGH and CRITICAL require confirm_token
- **Environment config**: `settings-{env}.yml` files (dev/test/prod), crypto key in separate `crypto-secret.key` file（**每环境独立，不跨环境复用** — 详见 §部署原则）
- **Coverage gates**: skills.database, mcp_server, auth, common ≥90%; other modules ≥80%
- **Audit resource_type 规范化**（前端 `AuditPage.vue:resourceTypeLabel` 映射）：`auth`/`sql`/`datasource`/`permission`/`crypto`/`config` 六类（MCP 调用走单独的 `pmcp_mcp_call_log` 表，audit_log 不存 `mcp` 类型）
- **API Key 掩码统一**：前端用 `utils/format.ts:maskApiKey(prefix)` → `pmcp_a******yz`（前 7+******+后 2）。**禁止** 各页面各自实现掩码函数（DRY 原则）。

## Frontend

> 详见：`UI 样式规范.md`

## POC Commands

> 详见：`poc/README.md`

## Skill System Design

> 详见：`技术架构说明文档.md §Skill System Design`

## MCP接入指南 API

> 详见：`技术架构说明文档.md §MCP 接入指南 API`

## UI Prototype

`documents/ui/Platform-MCP-portal.html` — Single-file HTML prototype of the management portal with full navigation, role-based visibility (admin/developer), datasource management, skill management, audit logs, and user management。前端所有页面必须严格对齐此原型。

## Documentation

Architecture and design docs in Chinese are in `documents/design/`:

| Document | Content |
|---|---|
| `Python：# Platform-MCP 技术架构说明文档.md` | Full technical architecture (authoritative source) |
| `Python：# Platform-MCP 架构说明（正式版）.md` | Formal architecture for project review |
| `Python：# Platform-MCP 代码规范.md` | Coding standards (Python/SQL/Vue/TS) |
| `Python：# Platform-MCP 部署规范.md` | Production deployment specification |
| `Python：# Platform-MCP 加解密方案说明.md` | AES-256-GCM encryption scheme |
| `Python：# Platform-MCP 开发计划文档.md` | 5-stage development plan |
| `Python：# Platform-MCP 数据库脚本规范.md` | SQL naming, Alembic migration rules |
| `Python：# Platform-MCP 测试规范文档.md` | Testing strategy and standards |
| `Python：# Platform-MCP UI 样式规范.md` | UI style guide |
| `Python：# Platform-MCP 问题汇总明细.md` | 开发避坑指南：DDL/后端/前端/MCP/部署/测试/文档 七类约 60 条问题清单（每条现象/根因/解决/参考四段式） |
| `文档审核指南.md` | 文档审核规则：配置/交互闭环校验 + 每轮审核独立开始 |

Archived drafts (Java track, GPT/GLM/MiniMax reviews) are in `documents/design/历史存档/`.

---

**附录**：模块级规范文档索引
- 技术架构：`技术架构说明文档.md`
- 代码规范：`代码规范.md`
- 部署规范：`部署规范.md`
- 测试规范：`测试规范文档.md`
- UI 规范：`UI 样式规范.md`
- 数据库脚本：`数据库脚本规范.md`
- 加解密方案：`加解密方案说明.md`
- 开发计划：`开发计划文档.md`
- 问题汇总：`问题汇总明细.md`
- 文档审核：`文档审核指南.md`
- POC 说明：`poc/README.md`

## 文档审核标准

> 详见：`文档审核指南.md`
