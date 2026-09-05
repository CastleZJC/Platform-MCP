# CLAUDE.md

本文件为**跨工具通用项目规则**（非 Claude Code 专用）：任何在本仓库工作的 AI 编码工具 / IDE（Claude Code、Qoder 等）均应遵循此处的架构约束、开发命令、部署原则、脱敏规范与审核标准。文件名沿用 `CLAUDE.md` 仅为历史兼容。**本文件是项目规则的唯一权威载体，后续任何规则调整均直接更新本文件，不新建 / 不迁移到其它 IDE 原生规则文件。**

> **职责分工（2026-09-05 精简）**：本文件只保留 AI 工作必需的规则、约束与命令；与规范文档重复的技术细节已下沉，规范文档为对应领域的权威载体——
> - 架构 / 技术选型 / 模块职责 / Skill 系统 / MCP 能力 / V3.0 与三期设计 → 《技术架构说明文档》（权威来源）
> - 编码规范 / git commit 格式 / 统一响应格式 → 《代码规范》
> - 测试命令 / 覆盖率门禁 → 《测试规范文档》
> - 部署 / Infra / crypto 密钥管理 → 《部署规范》《加解密方案说明》
>
> 规则类内容（部署原则、远程脱敏规范、文档审核标准）以本文件为权威，不外迁。

## Project Overview

Platform-MCP is an internal MCP (Model Context Protocol) capability platform——双入口单体（FastAPI Web + MCP Server 共享业务逻辑），PostgreSQL 16.4 系统库 + Oracle 11g / MySQL 5.6 目标库。

**当前状态（V3.0 M0-M6 全部落地，2026-09-05）**：31 MCP tools（database 5 + server 6 + skill 生态/双通道 16 + 双端承接 4；ToolMeta.roles 三角色过滤 admin 31 / developer 30 / 一般用户 19）；系统表 27 张（Alembic head=010）；三角色（admin / developer / user）；i18n 中/英（前端 vue-i18n 全站 key 化 + 后端 RESOURCES 48 key）；运行时配置中心（KNOWN_KEYS 注册表 + 30s 快照缓存 + 热切换）；Skill 生命周期 8 状态 varchar 状态机 + 版本化双语存档 + 广场（BGE-M3 语义搜索 / 黑名单 / admin 停用）+ 本地生成模型栈（Qwen3-4B 纯 CPU，模板兜底）+ 分享迭代 diff；邮件组提醒 ×4（outbox 模式）；三期 KB 骨架（5 表 + RAG/GRAPH 抽象 + api 501 占位）。

**Tests**: 1554 backend pytest（`--ignore=tests/performance` 门禁口径）+ 174 frontend vitest + mypy 0 errors (108 files)。POC verification tests remain in `poc/`（本地专用，未入库）。

> 里程碑细节（一期→Server 专项→V2.1→V3.0 M0-M6 各项交付、V3.0 设计、三期 KB 规划）：见《技术架构说明文档》§8.2.1 / §19.5 / §19.6 与 `README.md §版本迭代`。

## Architecture

**Dual-entry monolithic Python app with shared business logic**（详见架构 §4.2 / §7）：

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

- **MCP Server** (`mcp_server/__init__.py`): dual transport（stdio 环境变量 / streamable-http Header），`settings.mcp.transport` 切换模式；streamable-http 模式同端口挂载 `/transfer/*` 文件中转端点（写入限定 `datasource.sftp_exchange_dir`，见 `documents/bug/BUG20260814163941-SFTP交互链路断裂.md`）。
- **FastAPI Web** (`main.py`): 管理台 REST API，Gunicorn + Uvicorn workers。
- **Identity propagation**: API Key 校验结果存入 `contextvars.ContextVar`（`mcp_server/__init__.py:_mcp_identity_var`）。`McpContext.operator` 从中读取，未校验时回退 `mcp://{settings.mcp.operator_role}`。HTTP 模式每请求独立，stdio 模式进程级绑定。
- **Key constraint**: Database/Server Skill 业务逻辑不得泄漏进 `mcp_server` —— 它只处理协议、参数归一化、上下文包装、响应格式化（架构 §8.1）。
- **Shared logic**: 双入口共用 skill registry、SQL/SSH executor、risk engine、datasource/server manager、crypto（架构 §7）。

## API Key Authentication

API Key 是 MCP 层用户级认证的唯一机制（Web 层用 session cookie，架构 §8.7 / §12.1）：

| 层 | 认证机制 | 凭证载体 |
|----|---------|---------|
| Web (FastAPI) | Session (server-side) | `session_id` cookie |
| MCP (stdio) | API Key 校验 | `PLATFORM_MCP_API_KEY` 环境变量 |
| MCP (streamable-http) | API Key 校验 | `PLATFORM_MCP_API_KEY` HTTP Header |

存储设计（`pmcp_api_key` 表：`key_hash` SHA-256 校验 + `key_encrypted` AES-GCM admin reveal + `key_prefix`=raw_key[:10]；格式 `pmcp_` + `secrets.token_urlsafe(32)`）：详见架构 §8.7 / §14.1。AI 必须知道的行为要点：

- `GET /api-keys/full/{user_id}`：self-or-admin（admin 可查任意用户明文，普通用户仅自己）；`get_full_key_by_user` 按 `inserted_at DESC` 取最新活跃 key；hash-only 历史记录（key_encrypted 为 NULL）reveal 返回 code=1 提示需 reset。
- `POST /api-keys/reset/{user_id}`：撤销该用户所有活跃 key + 生成新 key。
- 新增 key 必须双列同写（`generate_api_key` 已处理）。

## Module Layout

| Package | Responsibility |
|---|---|
| `platform_mcp.api` | FastAPI REST（15 模块：auth/users/datasources/servers/api_keys/skills/groups/system_config/audit/crypto/profile/guide/plaza/notify/kb）；`/api/v1/health` 注册在 `main.py` |
| `platform_mcp.auth` | 登录、用户/角色/权限、session、API Key（models + service） |
| `platform_mcp.datasource` / `platform_mcp.server` | 数据源 / 服务器 CRUD（镜像结构），凭证加密 |
| `platform_mcp.group` | 统一组模型（`pmcp_group` + 3 成员表，V3.0 M0） |
| `platform_mcp.mcp_server` | MCP 协议、双传输 + 鉴权中间件、工具注册与角色过滤；`transfer.py` / `call_log.py` / `context.py` / `tool_wrapper.py` |
| `platform_mcp.skills.database` / `skills.server` | 5 + 6 个 MCP tools（executor / risk / confirm） |
| `platform_mcp.skills.common` | 共享风控类型（RiskLevel/RiskResult）+ env permission，database 与 server 共用 |
| `platform_mcp.skills.audit` / `readme` / `upload` / `versioning` | 14 条合规审计引擎 + 脱敏、README 生成、Skill 包上传链路、版本化双语存档（generated_by 留痕） |
| `platform_mcp.skills.plaza` / `plaza_service` / `embedding` / `ecosystem` | 广场领域服务（可见性/语义搜索/黑名单）、BGE-M3 `EmbeddingStore` 双实现、MCP 生态工具 + ToolMeta.roles 三角色过滤 |
| `platform_mcp.skills.llm` | 本地生成模型栈（QwenLlamaCppProvider 单槽互斥 + 中英 prompt + 重放校验 + 后台异步任务） |
| `platform_mcp.audit` | 审计日志记录、调用统计 |
| `platform_mcp.common` | 异常、响应模型、枚举、工具类 + 运行时配置中心 `runtime_config.py`（KNOWN_KEYS + 30s 快照缓存 + 热切换） |
| `platform_mcp.i18n` | 多语种资源字典 RESOURCES（48 key × zh-CN/en-US 1:1）+ split_bilingual + `get_text` 参数插值 |
| `platform_mcp.notify` | 邮件组提醒 ×4（dispatch / outbox 周期 flush / SMTP 走运行时配置中心，migration 009） |
| `platform_mcp.review` | 可复用审核流服务（service + state_machine；Skill 与三期 KB 共用） |
| `platform_mcp.kb` | 三期知识库骨架：五表 ORM + RAG/GRAPH 抽象 + 7 切片枚举 + `api/kb.py` 501 占位（migration 010；三期实现业务） |

Dependency direction: `api → auth / datasource / skills → audit → common`. No reverse dependencies.

## 能力里程碑与边界（防擅自二期/三期）

> 完整演进与工具清单见架构 §8.2.1（V2.1+V3.0 生态工具）/ §8.3（database 5 tools）/ §8.3.1（server 6 tools）/ §19.5（V3.0 设计）/ §19.6（三期 KB）；发布流水以 `README.md §版本迭代` 为准。

- **一期**：Database Skill 5 tools + API Key 双存储 + 双传输 MCP + 审计全覆盖 + 风险 4 级 confirm_token + 异步执行
- **Server 专项（二期）**：Server Skill 6 tools（SSH/SFTP）+ `platform_mcp/server/` + `skills/server/` + Shell 风控 4 级（PROD 自动升 CRITICAL）
- **V2.1**：Skill 源码上传注册（14 条合规审计 + 脱敏 + README 生成 + 审核流）+ 分组管理 + 系统配置 CRUD
- **V3.0 M0-M6**：统一组模型 / 三角色 / i18n 中英 / 运行时配置中心 / Skill 生命周期 8 状态 + 版本化双语存档 / 广场 + BGE-M3 语义搜索 / 本地生成模型栈 + 迭代 diff / 邮件组提醒 ×4 / KB 骨架 501 占位

关键行为要点（架构文档未展开，AI 必须知道）：

- **异步自动判定**：SQL 内容 >5000 字符 或 多语句文件 >3 条 → 自动转异步返回 execution_id（用户无需选 async_exec），状态轮询 TTL 30 分钟。
- **多语句含 HIGH/CRITICAL**：PROD 直接拒绝（`MULTI_STMT_HIGH_RISK`），DEV/UAT 整批 confirm（confirm_token 绑定整批内容 hash，篡改任一语句即失效；遇错即停）。
- **PL/SQL 块整块执行**：块内分号屏蔽防拆碎、`END;` 保留；块判定剥前导注释/BOM 后匹配；分句过滤仅注释语句；文件读取 `utf-8-sig`；Oracle 超时 `conn.break_()` OOB 打断 + 服务端会话终止（BUG20260824090000）。
- **审计 48 处 `write_audit_log`**（M5 起邮件捕捉点经其单一咽喉路由，PROD+HIGH/CRITICAL db/server 操作 Web+MCP 双入口）。

**不做规划（远期或独立需求，未经用户决策不得实施）**：

- SQL 类型级权限控制（用户对某数据源只能 SELECT，不能 DDL/DML）
- 内置 Skill 包扩展（config/file/log/deploy——V3.0 起转向用户 Skill 广场生态，内置维持 database + server）
- 角色权限管理页（预置三角色，权限随角色硬编码，无需独立页面）

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
cd platform-mcp-frontend
npm install
npm run dev                                # Start Vite dev server (port 5173, auto-increment if taken)
npx vitest run --coverage                  # Run frontend tests with coverage
> 详见：`测试规范文档.md §测试架构`

# Local seed / verify scripts (run from repo root, DB must be up)
python scripts/_setup_local.py             # 生成 crypto-secret.key + Alembic upgrade head + 检查 seed 用户
python scripts/_seed_skill.py              # 种 database + server skill 到 pmcp_skill 表（5 + 6 tools）
python scripts/_import_poc_datasources.py  # 导入 Oracle APP-SAMPLE-1 + MySQL APP-SAMPLE-2 数据源（本地专用脚本，未入库）
python scripts/_check_admin.py             # 校验 admin 用户密码哈希
python scripts/_reset_admin_pwd.py         # 重置 admin 密码为 admin123（bcrypt）
python scripts/_verify_imports.py          # 验证所有新模块可成功 import（非数据校验）
python scripts/_check_audit.py             # 抽查：打印最新 2 条审计日志（确认写入）
python scripts/_repair_audit_resource_type.py  # 一次性修复：历史 SQL 执行审计 resource_type datasource→sql 回填
python scripts/_test_mcp_auth.py           # 测 MCP 全链路：API Key 认证 + 数据源 + SQL 执行（本地专用脚本，未入库）
python scripts/_init_llm_weights.py        # 校验 Qwen GGUF 权重（魔数/体积/SHA-256/--probe 加载探测）
```

## 技术栈（指针）

钉版依赖清单以《代码规范》§十一 为权威，实际以 `pyproject.toml` / `platform-mcp-frontend/package.json` 为准。V3.0 增量依赖入 `[project.optional-dependencies] model` 组（fastembed BGE-M3 向量、llama-cpp-python Qwen 生成，`pip install .[model]`；aiosmtplib 邮件），权重未配置时 lazy import 自动降级。Infra：Rocky Linux 9.4 + Nginx 1.26.1 + systemd，无 Docker/K8s（部署规范 §1-§2）。

## 关键架构约束（详见架构 §5.6 / §6 / §9 / §12）

- **Oracle 11g 必须 thick mode**：`oracledb.init_oracle_client(lib_dir=...)` + `run_in_executor`；async 端点禁同步驱动（PG=asyncpg、MySQL=aiomysql、Oracle=executor）。
- **SQLAlchemy 2.0 style only**（`select()` / AsyncSession，禁 1.x `session.query()`）；**Pydantic v2 style only**（`@field_validator` / `model_dump()` / `ConfigDict`）。
- **目标库连接即用即断**：asynccontextmanager connect→execute→close，每数据源并发信号量（默认 5，经运行时配置 `datasource.default_max_concurrent` 热切换）；系统库走 ORM、目标库裸驱动非 ORM。
- **Web 认证 = 服务端 session cookie**（非 JWT）；MCP = API Key 双存储。
- **crypto key 每环境独立**：`crypto-secret.key`（32 raw bytes）0600、绝不跨环境复用，环境间迁移必须 re-encrypt 不传明文——详见部署规范 §5.3 / 加解密方案 §5。

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
10. **版本迭代记录（强制）**：每次生产发布（含 hotfix、迭代版本、配置类变更上线）必须更新 `README.md §版本迭代` 表，新增一行记录：版本号、日期、类型（基线发布 / 迭代 / hotfix / 配置变更）、摘要、修改人。**基线 V1.0 = 2026-08-08**。未更新版本迭代表的发布视为流程违规，违反"必须无问题上生产"的可追溯原则。
11. **生产发布四段式验证（强制）**：每次生产发布（除纯文档/纯 README 更新外）必须严格执行以下四段式流程，缺一不可：
    - **段一 预检（本地）**：跑全量回归 `pytest tests/ --ignore=tests/performance -q`（期望 1554 passed）+ `mypy platform_mcp/`（0 errors / 108 files，需安装 dev 依赖含 `types-PyYAML` 存根）+ `cd platform-mcp-frontend && npx vue-tsc -b`（exit 0）+ `npx vitest run`（174 passed）。**全绿才能进入段二**，任一红立即终止并修代码。
    - **段二 部署 + 健康检查**：上传变更 → 重启服务（**必须 `export PLATFORM_MCP_ENV=prod` 否则 web 起在 8000**）→ 验证 `curl http://127.0.0.1:8080/api/v1/health` 返回 `{"status":"UP"}` + `curl -X POST http://127.0.0.1:9000/mcp/`（无 PLATFORM_MCP_API_KEY Header 应返回 401）+ `curl -I http://127.0.0.1:8080/` 前端 200。
    - **段三 MCP 核心工具冒烟（必过项）**：依次调用下表 11 个核心工具（database 5 + server 6；V3.0 后新增的 skill 生态/双端承接 20 工具已由三角色 × 全工具单测矩阵固化，生产部署时按接入需要抽测），每个调用 request_summary 必须含唯一标记 `__MCP_VERIFY_<YYYYMMDDHHMMSS>__`（便于段四精准回滚）：
      | 工具 | 输入示例 | 期望 |
      |---|---|---|
      | `list_datasources` | `env_code=DEV` | 返回 ≥1 数据源 |
      | `list_servers` | `env_code=DEV` | 返回 ≥1 服务器 |
      | `validate_sql` | `SELECT 1 /* __MCP_VERIFY__ */` | LOW 风险 |
      | `validate_command` | `echo __MCP_VERIFY__` | LOW 风险 |
      | `execute_sql_text` | mysql-app-dev, `SELECT 1 AS __MCP_VERIFY__` | success |
      | `execute_command` | linux-app-dev, `echo __MCP_VERIFY__` | success |
      | `upload_file` | local=/tmp/_verify_src.txt → remote=/tmp/_verify_dst.txt（先创建源文件）| success（或 DEV allowed_sql_dirs 拦截）|
      | `download_file` | remote=/tmp/_verify_dst.txt → local=/tmp/_verify_dl.txt | success 或同上 |
      | `execute_sql_file` | /tmp/_verify.sql（含 SELECT 1）| success |
      | `get_execution_status` | 任意 execution_id | success 或 404 兜底 |
      | `get_server_execution_status` | 同上 | 同上 |
    - **段四 测试痕迹回滚（强制）**：冒烟产生的数据必须清理，**保持审计表纯净**：
      ```sql
      DELETE FROM pmcp_audit_log WHERE request_summary LIKE '%__MCP_VERIFY_%';
      DELETE FROM pmcp_mcp_call_log WHERE input_summary LIKE '%__MCP_VERIFY_%' OR output_summary LIKE '%__MCP_VERIFY_%';
      ```
      服务器清理：`rm -f /tmp/_verify_*`。**注**：真实业务审计行不可篡改（删除即审计欺诈）；段三冒烟标记的测试痕迹属生产数据污染，必须清理以保持审计表纯净——这一例外仅适用于 `__MCP_VERIFY__` 标记的明确测试行。

**禁止行为**：
- 禁止跳过 vue-tsc / pytest / vitest
- 禁止用 `as any` 掩盖类型错误
- 禁止生产发布后不更新 `README.md §版本迭代` 表（破坏可追溯性，违反发布纪律）
- 禁止跳过 §部署原则 #11 四段式验证（段一预检 / 段二部署健康检查 / 段三 MCP 冒烟 / 段四测试痕迹回滚）任意一段
- 禁止保留段三 MCP 冒烟产生的 audit_log / mcp_call_log 测试行（违反审计纯净原则；真实业务行严禁删除，例外仅限 `__MCP_VERIFY__` 标记行）
- 禁止保留"pre-existing issue"借口（部署期发现的所有问题必须修复或显式决策后才能上线）
- 禁止传明文敏感数据跨环境（必须 re-encrypt）
- 禁止 crypto key 跨环境复用

**遇到问题的处理流程**：
1. 优先修代码（生产代码 > 测试代码 > 文档）
2. 修复后必须回归（重跑 vue-tsc + 全量测试）
3. 文档同步更新（部署规范、CLAUDE.md、deployment-record-*.md）
4. 真正的决策点（如版本冲突需选型、依赖包不可用）才中断请用户决策

## Key Conventions

- **Git commits**: `<type>: <description in Chinese> yyyymmdd by castle`（types: feat/fix/refactor/docs/test/chore）——详见代码规范 §六
- **Unified response format**: 5 字段 `code` / `message` / `data` / `trace_id` / `timestamp`（Unix ms）——详见代码规范 §9.3
- **High-risk confirmation**: `confirm_token`（一次性服务端生成，反重放）——非布尔开关；风险 4 级 LOW/MEDIUM/HIGH/CRITICAL，HIGH+ 必须带 confirm_token（架构 §11）
- **加密密文格式**: `AES:base64(iv+ciphertext+tag)` 前缀；legacy `AES-CBC:...`；无前缀=明文透传——详见加解密方案 §4.4
- **Coverage gates**: skills.database / mcp_server / auth / common ≥90%，其他模块 ≥80%——详见测试规范 §1.2 / §7.4
- **环境配置**: `settings-{env}.yml`（dev/test/prod），crypto key 独立文件——详见部署规范 §5
- **Audit resource_type 规范化**（前端 `src/views/audit/AuditPage.vue:resourceTypeLabel` 映射，与代码 1:1）：`auth` / `sql`+`sql_exec`（同映 SQL 执行）/ `shell` / `server` / `datasource` / `user`+`role`+`permission`（同映用户管理）/ `crypto` / `config`+`system`（同映系统配置）/ `group` / `skill`（创建/更新/分享/撤回/迭代）/ `notify`（outbox 留痕）；分组调整归属 datasource/server 分组管理条目。MCP 调用走单独的 `pmcp_mcp_call_log` 表，audit_log 不存 `mcp` 类型
- **API Key 掩码统一**：前端用 `utils/format.ts:maskApiKey(prefix)` → `pmcp_a******yz`（前 7+******+后 2）。**禁止**各页面各自实现掩码函数（DRY 原则）。
- **多语言可扩展性**（V3.0 M1 起）：多语言非硬编码，新增语言（如四期日语）**仅加不改**——① 前端：新增 `src/i18n/<locale>.ts` 语言包（键位与 zh-CN 1:1，`src/__tests__/i18n/i18n.test.ts` 守卫强制）+ `src/i18n/index.ts` 的 `SUPPORTED_LOCALES` 与 `LOCALE_OPTIONS` 各加一项；② 后端：`platform_mcp/i18n/__init__.py` 的 `SUPPORTED_LOCALES` + `RESOURCES` 每键补新语言条目（`tests/unit/test_i18n.py` 1:1 强制）；③ 历史双语文档（README.md/README.en.md 等）同步检查补充新语言版本。禁止任何硬编码语言分支（`if locale == ...`）。
- **i18n 同功能同义同出处**（V3.0 起，2026-09-04）：同一功能、同一词义的文案必须使用同一个 i18n 键（单一出处，跨页面复用通常置于 `common` 段），**禁止在多个业务段重复定义同名同值键**（反例：skill/plaza 各自 `readmeAction` → 统一 `common.readmeAction`）。守卫：`src/__tests__/i18n/i18n.test.ts` 跨段同名同值检测（存量 28 键白名单见 `LEGACY_DUP_KEYS`，仅减不增，逐步收敛至 common）；后端 RESOURCES 同理单键复用。

## 远程脱敏规范（Remote Sanitization）

推送到远程仓库的所有内容 —— 代码、文档、原型、配置、`.gitignore`、提交信息、作者/提交者身份 —— 必须先行脱敏（本地工作区口径与远程公开口径分离）：

- **统一项目口径**：仓库内从头到尾只使用 `Platform-MCP` / `platform` / `PLATFORM_MCP_API_KEY` 一套命名；任何内部代号、厂商前缀、旧标识词及其大小写变体/子串不得出现，也不得出现"按分支区分口径"类表述
- **真实用户白名单**：仅允许 `castle.zhang`（及 `Castle` 别名）与通用邮箱身份；其他真实姓名一律以"内部用户"等泛称替代
- **内网拓扑脱敏**：内网 IP 统一替换为文档地址段 `192.0.2.x`；内网系统账号统一替换为 `appuser`；内部应用/服务器编码统一替换为 `APP-SAMPLE-N` / `linux-app-dev` 这类样本名
- **本地专用分支隔离**：仅存在于本地的内部分支，其分支名、内部版本号、修复记录不得出现在任何远程文件或提交信息中
- **提交/推送前检查（强制）**：每次 commit / push 前，必须对拟提交内容（全部待提交文件 + 提交描述）执行脱敏检查。**检查范围仅限拟提交远程仓库的文件内容及提交描述**；已被 `.gitignore` 排除的内容（开发计划等本地文档、documents/review/、documents/db/backup/、历史存档、`.claude/` 等）**不做脱敏检查**，保持本地工作区原始口径。
- **匹配要素登记（本地专用）**：脱敏检查匹配要素（关键词 / 域名 / 邮箱后缀 / 实际用户，**不区分大小写**）统一登记于本地 gitignored 配置 `.claude/sanitization-elements.json`，并在 Claude 项目 memory 中留副本；登记内容**严禁提交远程**，本文件（CLAUDE.md）不得列出具体要素
- **违规处理**：已推送的违规内容必须通过历史改写（`git filter-repo --replace-text/--replace-message/--mailmap` + force push）清除，不得以"已推送"为由保留；本地工作区文档不受此限（但推送前必须清洗）

## 专题指针

- **Frontend**：UI 样式与组件规范详见《UI 样式规范.md》
- **POC Commands**：详见 `poc/README.md`（`poc/` 为本地专用目录，未入库，`.gitignore` 已排除）
- **Skill System Design**：详见《技术架构说明文档》§22.3
- **MCP 接入指南 API**：详见《技术架构说明文档》§22.4
- **UI Prototype**：`documents/ui/Platform-MCP-portal.html` —— 单文件 HTML 原型，含完整导航、角色可见性（admin/developer）、数据源管理、Skill 管理、审计日志、用户管理。前端所有页面必须严格对齐此原型。

## Documentation

Architecture and design docs in Chinese are in `documents/design/`:

| Document | Content |
|---|---|
| `Python：# Platform-MCP 技术架构说明文档.md` | Full technical architecture (authoritative source)；含 §19.5 V3.0 设计 / §19.6 三期 KB / §22.3 Skill System / §22.4 MCP 接入指南 |
| `Python：# Platform-MCP 架构说明（正式版）.md` | Formal architecture for project review |
| `Python：# Platform-MCP 代码规范.md` | Coding standards（Python/SQL/Vue/TS）+ git commit 格式 + 统一响应格式 + 技术栈钉版 |
| `Python：# Platform-MCP 部署规范.md` | Production deployment（含 Infra / crypto key 管理 / SMTP 前置 §2.7） |
| `Python：# Platform-MCP 加解密方案说明.md` | AES-256-GCM encryption scheme |
| `Python：# Platform-MCP 开发计划文档（二期）.md` | 一期 5-stage + 二期开发计划（本地专用，未入库） |
| `Python：# Platform-MCP 数据库脚本规范.md` | SQL naming, Alembic migration rules |
| `Python：# Platform-MCP 测试规范文档.md` | Testing strategy and standards（含覆盖率门禁） |
| `Python：# Platform-MCP UI 样式规范.md` | UI style guide |
| `Python：# Platform-MCP 问题汇总明细.md` | 开发避坑指南：七类 60+ 条问题清单（每条现象/根因/解决/参考四段式） |
| `poc/README.md` | POC 说明（本地专用，未入库） |
| 本文件 §文档审核标准 | 文档审核规则 |

## 文档审核标准

当用户要求"文档审核"或"一致性校验"时，除原有审核维度（口径一致、规范详尽）外，必须额外遵守以下两条规则。

### 规则一：配置/交互闭环校验

每个涉及自定义配置或跨模块交互的环节，必须验证**定义端 → 传递链 → 消费端**全链路闭环。不能出现：配置文件定义了参数但代码未读取、代码设置了字段但前端未接收、API 返回了数据但类型定义不匹配等情况。

**校验清单**：

- **配置文件中的每个自定义参数** → 对应的 Settings 类是否定义 → 是否被业务代码实际读取使用
- **API 返回的每个字段** → 前端类型定义是否包含 → 前端模板是否实际使用
- **数据库表的每个字段** → ORM 模型是否映射 → API 是否返回 → 前端是否展示
- **MCP Tool 的每个参数** → Skill 代码是否接收处理 → 结果是否正确返回

**典型问题示例**：

| 问题类型 | 现象 | 闭环断点 |
|---------|------|----------|
| 配置定义未读取 | YAML 定义了 `app.feature_x` 但代码从未使用 `settings.feature_x` | 定义端 → 消费端断 |
| API 字段未使用 | 返回 `body["data"]["extra_field"]` 但前端类型定义和模板均未引用 | 传递链 → 消费端断 |
| ORM 未映射 | 表新增列但 Pydantic schema 未包含 | 数据库 → API 断 |

### 规则二：每轮审核独立开始

每次文档审核都是独立的全新开始。不得沿用历史审核的记忆、结论或"已通过"假设。所有交叉校验必须从头执行，避免惯性遗漏（因熟悉代码而跳过某些检查）。即使某项在上一轮确认通过，本轮也必须重新验证。

**执行要点**：

1. **不依赖历史报告**：不引用上一轮审核的结论，所有数字、行号、测试数必须重新实测
2. **全量校验**：不抽样，每个交叉点都要验证
3. **工具实测**：用 grep、pytest、代码读取等工具确认，不凭记忆判断

**独立审核检查表**：

- [ ] 所有版本号、行数、测试数等数字通过 grep/pytest 实测重新确认
- [ ] 所有代码引用路径通过 Read 或 Grep 验证存在
- [ ] 所有接口定义通过实际调用或文档交叉验证
- [ ] 不假设"上次已通过，这次应该没问题"

### 审核维度参考

除上述两条规则外，文档审核还应覆盖：

| 维度 | 说明 |
|------|------|
| **口径一致** | 多份文档对同一事项的描述是否一致 |
| **规范详尽** | 是否覆盖必要细节（命令、配置、边界条件） |
| **引用有效** | 所有文档间引用路径是否正确 |
| **示例准确** | 代码示例、配置示例是否可运行 |
| **版本同步** | 文档中的版本号与 pyproject.toml/package.json 是否一致 |