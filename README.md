# Platform-MCP

> 内部 MCP (Model Context Protocol) 能力平台
> 双 Skill：Database（SQL 执行）+ Server（Linux SSH/SFTP）— 共 11 个 MCP 工具，通过 Claude Code 等调用方远程执行，配备 Web 管理台与全链路审计

## 项目概览

Platform-MCP 是一个内部 MCP 服务平台，提供：

- **Database Skill（5 tools）**：执行本地 SQL 文件 / SQL 文本 / 风险校验 / 数据源列举 / 异步状态查询
- **Server Skill（6 tools）**：Linux 远程 Shell 执行 / SFTP 上传下载 / 命令风控校验 / 服务器列举 / 异步状态查询
- **双传输 MCP Server**：stdio（环境变量）+ streamable-http（Header）双入口
- **API Key 认证**：双存储（key_hash SHA-256 校验 + key_encrypted AES-GCM admin reveal）
- **Web 管理台**：数据源管理 + 服务器管理 + 用户管理 + API Key 管理 + 审计日志 + 个人设置
- **权限控制**：admin/developer 双角色，developer 禁 PROD；服务器与数据源各自独立权限
- **风险引擎**：SQL 与 Shell 共用 4 级（LOW/MEDIUM/HIGH/CRITICAL），HIGH+ 需 `confirm_token` 反重放二次确认

## 快速启动

### 前置要求

- Python 3.11.9
- PostgreSQL 16.4（系统库）
- Oracle 11g / MySQL 5.6（目标库，可选）

### 后端启动

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 创建本地配置（必填 database.url）
cp settings.yml.example settings.yml
# 编辑 settings.yml，替换 <password> / HOST 为你的 PostgreSQL 实际值

# 3. 准备 PostgreSQL：创建库 + 用户
createdb platform_mcp
psql -d platform_mcp -c "CREATE USER pmcp WITH PASSWORD '<your-password>';"

# 4. 设置 Alembic DB URL（用于 migration；可写入 ~/.bashrc 持久化）
export PLATFORM_DB_URL="postgresql://pmcp:<password>@localhost:5432/platform_mcp"

# 5. 生成 crypto 密钥 + Alembic 升级 + 检查 seed 用户
python scripts/_setup_local.py

# 6. 种 database + server skill 到 pmcp_skill 表
python scripts/_seed_skill.py

# 7. 启动 FastAPI Web（默认端口 8000）
python -m platform_mcp.main

# 8. 启动 MCP Server（mode 由 settings.mcp.transport 决定）
python -m platform_mcp.mcp_server
```

### 前端启动

```bash
cd platform-mcp-frontend
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

**后端**：Python 3.11.9 + FastAPI 0.115.0 + SQLAlchemy 2.0.35 + Alembic 1.13.2 + oracledb 2.4.1 + aiomysql 0.2.0 + asyncssh 2.17.0（Server Skill SSH/SFTP）

**前端**：Vue 3.5.34 + Vite 8.0.12 + TypeScript 6.0.2 + Element Plus 2.8.1 + Pinia 2.2.2 + Axios 1.7.4

**数据库**：PostgreSQL 16.4（系统），Oracle 11g / MySQL 5.6（目标）

## 架构（简化）

```
Claude Code ──stdio(env PLATFORM_MCP_API_KEY)──▶ MCP Server ──┐
           ╲                                        ├──▶ PostgreSQL（系统库，ORM）
            ╲                                       │    Oracle / MySQL（Database Skill 目标）
Claude Code ──HTTP(header PLATFORM_MCP_API_KEY)──▶ ──┤    Linux SSH/SFTP（Server Skill 目标）
                                                │
Browser ──HTTP(session cookie)──▶ FastAPI Web ──┘
```

## 目录结构

```
Platform-MCP/
├── platform_mcp/                # 后端代码
│   ├── api/                     # FastAPI 路由（11 模块，含 servers）
│   ├── auth/                    # 认证鉴权 + API Key
│   ├── datasource/              # 数据源管理（DB Skill 目标）
│   ├── server/                  # 服务器管理（Linux SSH 目标，Server Skill 用）
│   ├── skills/
│   │   ├── database/            # Database Skill（5 tools：SQL 执行 + 风控）
│   │   ├── server/              # Server Skill（6 tools：SSH/SFTP + 风控）
│   │   └── common/              # 共享风控类型（risk_types + permission）
│   ├── mcp_server/              # MCP 协议 + 双传输 + 上下文/审计
│   ├── audit/                   # 审计日志
│   └── common/                  # 公共组件（database / crypto / response / 等）
├── platform-mcp-frontend/       # 前端代码（Vue 3，9 业务页面含服务器管理）
├── tests/                       # 后端测试（525 用例）
├── scripts/                     # 工具脚本
├── alembic/                     # 数据库迁移
├── documents/                   # 设计文档
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
| V1.1.5 | 2026-08-17 | hotfix | BUG20260817220800 execute_command 多语句静默截断（V1.1.0 引入，V1.1.4 发布当日复核发现）：`echo $$; exec <cmd>` 包装中 POSIX `exec` 用第一条命令替换 shell，`;`/`&&`/`||` 后命令全部静默丢弃（exit 0）——生产实证 `echo A; echo B; pwd; id` 仅回显 A。修复：`exec bash -c {shlex.quote(command)}` 完整承载命令串，审计 source_session PID 捕获语义不变。验证：段一全绿（pytest 801、mypy 0/76、vue-tsc 0、vitest 117）+ 生产实测多语句全量输出 + 五段链式命令按序全执行（详见 documents/bug/BUG20260817220800） | castle |
| V1.1.4 | 2026-08-17 | hotfix | BUG20260814163941 断点续传专项 + BUG20260817123100 SQL 多语句执行异常：**（1）断点续传**——SFTP 腿 `_sftp_put/get_resumable`（r+b/ab 断点续写 + 尺寸完整性校验 + 3 次自动重试，成功/耗尽均清理）；HTTP 腿分片上传 `/transfer/chunk`+`/transfer/merge`（合并尺寸校验，失败保留分片供补传）+ Range 下载 206 + 截断上传校验（收到字节 ≠ Content-Length → 400+清理）；Windows 工作站路径前置识别（报错内嵌双向 curl 中转指引，PLATFORM_MCP_API_KEY）。**（2）SQL 多语句**——text/file 统一 `split_statements` 分句（SQL*Plus `/` 碎片过滤）、多语句低风险逐条执行（statement_count/results[]）、含 HIGH/CRITICAL 直接拒绝 `MULTI_STMT_HIGH_RISK`、confirm_token 绑定 sql_hash 封死换 SQL 复用 + 重试指引、审计 error_code 透传（CONFIRM_REQUIRED 也如实记 error）。**（3）生产冒烟补漏**——uvicorn 真实断开时 `request.stream()` 抛 ClientDisconnect（非 OSError）逃逸 503 且部分落盘不清理（pytest ASGITransport 优雅结束流覆盖不到），upload/upload_chunk 改 400+清理，附 http.disconnect 回归用例。验证：11 工具生产实测 + 专项（100MB SFTP sha256 双端一致 / 20MB 分片中转全链路一致 / Range 206 / 截断 400 零残留）+ 段四标记行清理 0 残留（详见两份 BUG 文档） | castle |
| V1.0.1 | 2026-08-09 | hotfix | 审计日志失败记录完整性增强（合并两次细粒度修复为同日 hotfix）：**（1）error_code 强制捕获**——`call_log.py` PmcpMcpCallLog 构造补 `error_code=error_code`（修前 mcp_call_log 全表 error 行 0/5 有码）；`auth.py` login fail 补 `error_code="11001"`；`crypto.py` encrypt/verify fail 补 `error_code="15001"`；`profile.py` change-password fail 补 `error_code="11004"`。**（2）result_status 枚举统一**——web 层 6 文件 8 处 `'fail'` → `'error'`（auth/crypto/profile/datasources/servers）+ UI `statusLabel` 防御性同时识别 fail/error → 失败 + `audit/models.py` 列 comment 更新为 `(success/error)`。**（3）历史数据 backfill**——UPDATE fail→error 共 2 行 + NULL error_code 按错误信息模式匹配 backfill 6 行（11001/12001/10001/15001），最终态 0 fail 残留 + error 行 error_code 完整率 100%。生产验证：castle.zhang 4 行登录失败记录全 error/11001 ✓；castle.zhang MCP 失败 → audit_log + mcp_call_log 双表 error_code=12001 ✓ | castle |
| V1.0 | 2026-08-08 | 基线发布 | 一期 + Server Skill 二期专项全量上线：11 MCP tools（database 5 + server 6）、15 系统表、9 前端页面、双传输 MCP（stdio + streamable-http）、API Key 双存储（hash + encrypted） | castle |

## 测试

```bash
# 后端（525 用例，覆盖率 95.96%）
python -m pytest tests/ --ignore=tests/performance --cov=platform_mcp
mypy platform_mcp/    # 类型检查（V1.0 新增）

# 前端（110 用例）
cd platform-mcp-frontend
npm run test
```

## 配置

| 文件 | 用途 | 来源 |
|---|---|---|
| `settings.yml` | 基础配置（database.url 等，必填） | 从 `settings.yml.example` 复制 |
| `settings-dev.yml` | dev 环境覆盖（已含） | 已追踪，按需修改 `oracle_instant_client_dir` |
| `settings-prod.yml` | prod 环境覆盖 | 从 `settings-prod.yml.example` 复制（仅 prod 需要） |
| `crypto-secret.key` | AES 密钥（32 raw bytes） | `scripts/_setup_local.py` 自动生成 |
| `alembic.ini` | Alembic migration 配置 | 已追踪；DB URL 占位，可用 `PLATFORM_DB_URL` 环境变量覆盖 |

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
