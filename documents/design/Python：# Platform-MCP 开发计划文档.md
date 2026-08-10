# Platform-MCP 开发计划文档

> **文档名称**：Platform-MCP 开发计划文档
> **基于文档**：《Platform-MCP 技术架构说明文档》、《Platform-MCP 架构说明（正式版）》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | V1.0 | 2026-08-08 12:00:00 | 正式发布 | 一期 + Server Skill 二期专项全量上线 | castle |
>
> **适用范围**：Platform-MCP 一期（Database Skill 落地闭环）
> **编制时间**：2026-06-03
> **开发环境**：Windows 11 + IntelliJ IDEA / VS Code

---

## 一、项目概况

### 1.1 项目定位

Platform-MCP 是内部 MCP 能力平台，一期聚焦 Database Skill，通过 MCP 标准接口承接 Claude Code 的数据库执行请求，并建设 Web 管理端。

### 1.2 一期核心交付物

| 交付物 | 说明 |
|--------|------|
| MCP Server | 双传输（stdio + streamable-http），支持 11 个 Tool（database 5 + server 6） |
| FastAPI Web | REST API 管理端，9 个核心页面（含 V1.0 新增服务器管理页） |
| Database Skill | SQL 文本执行、SQL 文件执行、风险识别、数据源列表、执行状态查询 |
| Server Skill（V1.0 二期专项） | execute_command / upload_file / download_file / list_servers / validate_command / get_server_execution_status（Linux SSH/SFTP） |
| PostgreSQL 系统库 | 用户/角色/权限/数据源/服务器/审计日志/Skill 注册（15 张系统表） |
| 部署方案 | 单机 systemd + Nginx（root 版）/ 用户态 portable（无 root，§13 部署规范） |

### 1.3 技术栈

| 层次 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | 3.11.9 |
| Web 框架 | FastAPI + Gunicorn + Uvicorn | 0.115.0 / 23.0.0 / 0.30.6 |
| 数据校验 | Pydantic + pydantic-settings | 2.8.2 / 2.5.2（mcp 1.9.4 强制）|
| ORM | SQLAlchemy 2.0 (AsyncSession) + asyncpg | 2.0.35 / 0.30.0 |
| 数据库迁移 | Alembic | 1.13.2 |
| MCP SDK | mcp (Python SDK) | 1.9.4 |
| 目标库驱动 | oracledb (thick) / aiomysql | 2.4.1 / 0.2.0 |
| 加密 | cryptography | 43.0.1 |
| 密码哈希 | passlib + bcrypt | 1.7.4 / 4.2.0（passlib 验证 $2b$ 哈希必装 bcrypt backend） |
| SSH/SFTP | asyncssh | 2.17.0（pure Python，复用 cryptography） |
| 类型检查 | mypy | 1.11.2（V1.0 引入） |
| 表单上传 | python-multipart | 0.0.9 |
| 前端运行时 | Node.js | 22.22.3 |
| 前端框架 | Vue 3 + TypeScript + Element Plus | 3.5.34 / 6.0.2 / 2.8.1 |
| 路由 + 状态 | Vue Router + Pinia | 4.4.3 / 2.2.2 |
| HTTP 客户端 | Axios | 1.7.4 |
| 构建工具 | Vite | 8.0.12 |
| 系统数据库 | PostgreSQL | 16.4 |
| 日志 | loguru | 0.7.2 |
| HTTP 客户端（后端） | httpx | 0.27.2 |
| 重试控制 | tenacity | 9.0.0 |
| 配置解析 | PyYAML | 6.0.2 |
| Web 服务器 | Nginx | 1.26.1 |

---

## 二、分期边界

| 维度 | 一期 | 二期 |
|------|------|------|
| 核心目标 | Database Skill 落地闭环 + Server Skill 二期专项 | Skill 扩展 + 能力增强 |
| Skill 数量 | 2（database + server） | 3-5（+ config / file / log） |
| 模块数量 | 8 顶级包（含 server/ + skills/common/） | 按需拆分至 10-13 |
| Web 页面 | 9 个核心页面（含服务器管理） | 补全至 10 个 |
| 风险引擎 | sqlparse + 正则 + 关键词（database + server 共用 risk_types） | 配置化规则引擎 |
| 数据库方言 | Oracle + MySQL 基础支持 | DatabaseDialect 方言抽象层 |
| Skill 注册 | 装饰器静态注册 | 动态模块加载（热插拔） |
| 连接管理 | 按需连接 | 轻量连接池 |
| 限流 | asyncio.Semaphore 基础并发控制 | 熔断器 |

---

## 三、开发阶段规划

### 阶段零：技术兼容验证

**目标**：验证核心技术栈的兼容性与可行性

**状态**：已完成

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 0.1 | Python 3.11.9 + FastAPI 空项目验证 | GLM 5.1 | 手动 | ✅ 完成 |
| 0.2 | Oracle 11g thick 模式连接验证（oracledb 2.4.1 + run_in_executor） | GLM 5.1 | 手动 | ✅ 完成（6/6 通过） |
| 0.3 | MySQL 5.6 连接验证（aiomysql） | GLM 5.1 | 手动 | ✅ 完成（14/14 通过） |
| 0.4 | SQLAlchemy AsyncSession + asyncpg + PostgreSQL 验证 | GLM 5.1 | 手动 | ✅ 完成（阶段一搭建时一并验证） |
| 0.5 | Claude Code + MCP Python SDK stdio 模式最小化 PoC | GLM 5.1 | 手动 | ✅ 完成（4/4 通过） |
| 0.6 | cryptography AES-256-GCM 加解密验证 | GLM 5.1 | 手动 | ✅ 完成（阶段一 1.3.4 一并验证） |

**验证结论**：

- Oracle 11g：oracledb thin 模式不支持 11g（最低 12.1），必须使用 thick 模式 + `run_in_executor` 异步包装
- MySQL 5.6：aiomysql 14/14 项全量通过，可直接使用
- 驱动版本与 Python 3.11.9 形成固化清单：oracledb==2.4.1, aiomysql==0.2.0, asyncpg==0.30.0

---

### 阶段一：基础框架与系统库

**目标**：搭建后端工程骨架，初始化系统库，建立基础设施

**前置条件**：阶段零 0.1（FastAPI 空项目）+ 0.4（SQLAlchemy AsyncSession）验证通过

#### 1.1 后端工程骨架

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 1.1.1 | 创建 Python 包结构（platform_mcp） | GLM 5.1 | ecc:python-patterns | ✅ 完成 |
| 1.1.2 | 配置 pyproject.toml（依赖管理、requires-python=">=3.11.9,<3.12"、pytest、black、isort） | GLM 5.1 | ecc:python-patterns | ✅ 完成 |
| 1.1.3 | 搭建 8 顶级包骨架目录（api / auth / datasource / server / mcp_server / skills / audit / common，其中 skills 含 database + server + common 三子包） | GLM 5.1 | ecc:python-patterns | ✅ 完成 |
| 1.1.4 | FastAPI main.py 入口搭建 | GLM 5.1 | ecc:fastapi-patterns | ✅ 完成 |
| 1.1.5 | MCP Server mcp_server.py 入口搭建（空壳） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 1.1.6 | 配置管理模块（pydantic-settings，支持 settings.yml + settings-dev.yml） | GLM 5.1 | ecc:python-patterns | ✅ 完成 |
| 1.1.7 | 日志配置（loguru，统一格式） | GLM 5.1 | ecc:python-patterns | ✅ 完成 |

**验收标准**：
- `python -m platform_mcp.main` 可启动 FastAPI（返回 404 即可）
- `python -m platform_mcp.mcp_server` 可启动 MCP Server（stdio 模式无报错）
- 8 个顶级包目录存在且含 `__init__.py`（api / auth / datasource / server / mcp_server / skills / audit / common，skills 含 database + server + common 三子包）

#### 1.2 系统库表结构与 ORM

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 1.2.1 | SQLAlchemy Base + BaseModel（含审计字段） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.2 | Alembic 初始化与 env.py 配置 | GLM 5.1 | ecc:database-migrations | ✅ 完成 |
| 1.2.3 | pmcp_user / pmcp_role / pmcp_user_role 表 Model | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.4 | pmcp_permission / pmcp_role_permission 表 Model（权限定义 + 角色权限关系） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.5 | pmcp_datasource 表 Model（含 encrypted_password 字段） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.6 | pmcp_datasource_permission 表 Model（数据源权限关系） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.7 | pmcp_audit_log / pmcp_mcp_call_log / pmcp_crypto_operation_log 表 Model | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.8 | pmcp_skill 表 Model（编码、名称、描述、状态、注册方式、Tool 数量） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.9 | pmcp_system_config 表 Model（系统参数配置，支持并发限流与风险规则动态调整） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |
| 1.2.10 | Alembic 初始迁移 + seed 数据（admin 用户、默认角色、默认权限） | GLM 5.1 | ecc:database-migrations | ✅ 完成 |
| 1.2.11 | 数据库连接管理（AsyncSession 工厂、get_db 依赖注入） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成 |

**验收标准**：
- `alembic upgrade head` 成功创建全部 15 张系统表（pmcp_user、pmcp_role、pmcp_user_role、pmcp_permission、pmcp_role_permission、pmcp_api_key、pmcp_datasource、pmcp_datasource_permission、pmcp_server、pmcp_server_permission、pmcp_audit_log、pmcp_mcp_call_log、pmcp_crypto_operation_log、pmcp_skill、pmcp_system_config）
- V1.0 alembic 单一发布修订 `001_initial_tables.py` 合并历史 10 个迭代最终态
- `SELECT COUNT(*) FROM pmcp_user` 返回 1（admin 用户）
- ORM 单元测试通过

#### 1.3 通用基础设施

> **前置说明**：任务 1.3.4（CryptoUtils）依赖阶段零 0.6（cryptography AES-256-GCM 加解密验证）通过。

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 1.3.1 | 统一响应模型（ResponseBase / PageResult） | GLM 5.1 | ecc:fastapi-patterns | ✅ 完成 |
| 1.3.2 | 自定义异常体系（BaseError / BusinessError / AuthError / DataSourceError / SkillError / PathSecurityError） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 1.3.3 | 全局异常处理器（FastAPI exception_handler） | GLM 5.1 | ecc:fastapi-patterns | ✅ 完成 |
| 1.3.4 | CryptoUtils 加解密工具类（AES-256-GCM 为主，CBC 兼容解密历史密文） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 1.3.5 | 配置加载与密钥初始化流程（应用启动事件） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 1.3.6 | 审计日志基础设施（AuditLogger 接口 + pmcp_audit_log 写入） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 1.3.7 | 请求级 trace_id 中间件 | GLM 5.1 | ecc:fastapi-patterns | ✅ 完成 |

**验收标准**：
- CryptoUtils 加密 → 数据库存储 → 解密还原完整通过
- 统一响应格式符合 `{"code": 0, "message": "...", "data": ..., "trace_id": "...", "timestamp": 171756...}` 规范
- 异常可正确捕获并返回标准错误响应

---

### 阶段二：MCP Core 与 Skill Registry

**目标**：搭建 MCP Server 入口，建立 Skill 注册路由机制

**前置条件**：阶段一完成 + 阶段零 0.5（MCP SDK stdio PoC）验证通过

#### 2.1 MCP Server 入口

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 2.1.1 | MCP Server 完整入口（mcp_server.py，使用 mcp SDK FastMCP） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 2.1.2 | Tool 参数解析与校验（Pydantic Model 入参） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 2.1.3 | 统一返回结构（ToolResult 格式化） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 2.1.4 | MCP 调用上下文构建（用户信息、数据源信息、环境信息） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 2.1.5 | MCP 调用日志（调用前记录 + 调用后记录 + 异常记录） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |

**验收标准**：
- Claude Code 可通过 MCP 配置启动 Platform-MCP MCP Server
- `list_tools` 返回已注册的 Tool 列表
- 调用任意 Tool 返回统一格式结果

#### 2.2 Skill Registry

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 2.2.1 | Skill Protocol 接口定义（skill_name / list_tools / validate / execute / support） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 2.2.2 | @register_skill("name") 装饰器实现 | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 2.2.3 | SkillRegistry 类（dict 映射 + 路由 + 查询接口） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 2.2.4 | 基础并发限流（asyncio.Semaphore，每数据源默认 max 5） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 2.2.5 | Skill 注册自发现（导入时自动触发装饰器注册） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |

**验收标准**：
- Skill 注册后可通过 Registry 查询
- Tool 名称按 `skill_name.tool_name` 格式路由到正确 Skill
- 并发限流在超限时返回明确的等待/拒绝信息

---

### 阶段三：Database Skill 闭环

**目标**：实现完整的数据库 SQL 执行能力

**前置条件**：阶段二完成

#### 3.1 数据源连接管理

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 3.1.1 | 数据源连接管理器（DatasourceManager） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 3.1.2 | Oracle 连接工厂（oracledb thick + run_in_executor + asynccontextmanager） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 3.1.3 | MySQL 连接工厂（aiomysql + asynccontextmanager） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 3.1.4 | 数据源密码解密流程（CryptoUtils.decrypt） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 3.1.5 | 数据源健康检查（连接测试） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |

**验收标准**：
- 可连接 Oracle 11g 并执行 `SELECT 1 FROM DUAL`
- 可连接 MySQL 5.6 并执行 `SELECT 1`
- 密码从数据库读取 → 解密 → 建立连接全流程通过

#### 3.2 SQL 执行与风险识别

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 3.2.1 | SQL 解析与风险识别引擎（RiskEngine：sqlparse + 正则 + 关键词） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 3.2.2 | 风险等级定义（LOW / MEDIUM / HIGH / CRITICAL） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 3.2.3 | execute_sql_text Tool 实现 | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 3.2.4 | execute_sql_file Tool 实现（含路径安全校验、白名单目录校验） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 3.2.5 | validate_sql Tool 实现 | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 3.2.6 | list_datasources Tool 实现 | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |
| 3.2.7 | get_execution_status Tool 实现 | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |

**验收标准**：
- `SELECT` 语句 → LOW 风险，正常执行
- `INSERT ... VALUES(...)` → MEDIUM 风险，正常执行
- `DELETE FROM t` (无 WHERE) → HIGH 风险，要求二次确认
- `DROP TABLE t` → CRITICAL 风险，强制二次确认
- SQL 文件路径穿越（`../../etc/passwd`）→ 拒绝执行
- SQL 文件在白名单目录外 → 拒绝执行

#### 3.3 高级执行控制

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 3.3.1 | 高风险二次确认机制（confirm_token 一次性令牌生成与校验，防重放） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 3.3.2 | 基础事务控制（AUTO_COMMIT / MANUAL 事务模式） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 3.3.3 | 生产库受保护标记（PROD 数据源仅 admin 可调用） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 3.3.4 | 执行结果格式化（列名 + 行数据 + 影响行数 + 执行时间） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |
| 3.3.5 | Oracle / MySQL 方言适配（DUAL、分页语法等） | GLM 5.1 | ecc:backend-patterns | ✅ 完成 |

**验收标准**：
- 高风险 SQL 无 confirm_token 时返回确认请求
- PROD 环境下 developer 角色调用被拒绝
- Oracle DUAL 查询、MySQL LIMIT 查询正确执行

---

### 阶段四：Web 管理端

**目标**：建设 9 个核心页面（1 登录页 + 8 管理页面，含 V1.0 新增服务器管理页）

**前置条件**：阶段三完成

#### 4.1 前端工程搭建

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 4.1.1 | Vue 3 + Vite + TypeScript 项目初始化（Node.js >= 22.22.3） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.1.2 | Element Plus + Pinia + Axios + Vue Router 配置 | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.1.3 | 设计令牌（CSS 变量：亮色/暗色主题） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.1.4 | 主布局组件（侧边栏 + 头部 + 内容区域） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.1.5 | 路由配置（8 页面 + 权限守卫） | GLM 5.1 | ecc:frontend-patterns | ✅ 完成 |
| 4.1.6 | Axios 封装（拦截器、统一错误处理） | GLM 5.1 | ecc:frontend-patterns | ✅ 完成 |

**验收标准**：
- `npm run dev` 启动前端开发服务器
- 亮色/暗色主题切换正常
- 侧边栏 3 分组显示（管理中心 / 系统管理 / 帮助）

#### 4.2 认证与权限

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 4.2.1 | 后端：登录接口（Session 认证与校验、passlib 密码哈希验证） | GLM 5.1 | ecc:fastapi-patterns | ✅ 完成 |
| 4.2.2 | 后端：权限中间件（角色校验 + 接口级权限） | GLM 5.1 | ecc:fastapi-patterns | ✅ 完成 |
| 4.2.3 | 前端：登录页（双栏布局，角色由用户名自动映射，无需手动选择） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.2.4 | 前端：用户 Store（登录态管理 + Session 存储） | GLM 5.1 | ecc:frontend-patterns | ✅ 完成 |
| 4.2.5 | 前端：路由守卫（未登录跳转 + 角色权限过滤菜单） | GLM 5.1 | ecc:frontend-patterns | ✅ 完成 |

**验收标准**：
- admin 登录后可见全部 7 个管理页面
- developer 登录后不可见密码加密页、用户管理页（可见 5 个管理页面）
- Session 过期后自动跳转登录页

#### 4.3 管理页面

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 4.3.1 | Skill 管理页（列表、启停开关、审核状态徽章、新增入口） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.3.2 | 数据源管理页（CRUD、连接测试按钮、环境标识徽章） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.3.3 | 密码加密页（明文输入 → 密文输出、一键复制） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.3.4 | 审计日志页（时间/操作类型/用户筛选、日志详情弹窗） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.3.5 | 用户管理页（用户列表、角色分配 admin/developer） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.3.6 | 个人设置页（头像下拉菜单进入、显示名称/邮箱/修改密码） | GLM 5.1 | ui-ux-pro-max | ✅ 完成 |
| 4.3.7 | MCP 接入指南页（Claude Code 配置步骤、JSON 配置示例、FAQ） | GLM 5.1 | ecc:frontend-patterns | ✅ 完成 |

**验收标准**：
- Skill 管理页：admin 可启停 + 审核，developer 仅可新增（待审核状态）
- 数据源管理页：admin 可编辑，developer 仅查看 + 测试连接
- 审计日志页：admin 可看全部记录，developer 仅看自己的
- 密码加密页：仅 admin 可见

#### 4.4 后端 API

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 4.4.1 | 用户管理 API（CRUD、角色分配） | GLM 5.1 | ecc:api-design | ✅ 完成 |
| 4.4.2 | 数据源管理 API（CRUD、连接测试、密码加密） | GLM 5.1 | ecc:api-design | ✅ 完成 |
| 4.4.3 | Skill 管理 API（列表、启停、审核） | GLM 5.1 | ecc:api-design | ✅ 完成 |
| 4.4.4 | 审计日志 API（分页查询、条件筛选、详情查看） | GLM 5.1 | ecc:api-design | ✅ 完成 |
| 4.4.5 | 密码加密 API（明文加密、密文格式输出） | GLM 5.1 | ecc:api-design | ✅ 完成 |
| 4.4.6 | 个人设置 API（查看/修改个人信息、修改密码） | GLM 5.1 | ecc:api-design | ✅ 完成 |
| 4.4.7 | MCP 接入指南 API（获取配置示例、已注册 Tool 列表） | GLM 5.1 | ecc:mcp-server-patterns | ✅ 完成 |

> **二期延后说明**：架构文档 §15.1 中的"系统配置接口"（动态调整限流参数与风险规则）和"Skill 源码上传解析"（架构 §7.2.4 三种注册方式之一）延至二期实现。一期 Skill 注册仅支持页面表单提交和装饰器静态注册。**细粒度数据源权限控制**（`pmcp_datasource_permission` 表，用户/角色级别访问控制）延至二期实现，Web 端和 MCP 端一并实现。一期仅支持粗粒度角色控制（admin/developer）+ MCP operator_role 环境限制。

**验收标准**：
- 所有 API 返回统一响应格式
- 权限校验拦截非授权访问
- 审计日志记录所有写操作

---

### 阶段五：测试与上线

**目标**：全量测试验证，部署上线

**前置条件**：阶段四完成

#### 5.1 后端测试

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 5.1.1 | RiskEngine 单元测试（LOW/MEDIUM/HIGH/CRITICAL 四级） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.1.2 | SQLExecutor 单元测试（Mock 连接） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.1.3 | CryptoUtils 单元测试（加密/解密/兼容明文） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.1.4 | DatasourceManager 单元测试（连接工厂、健康检查） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.1.5 | Skill Registry 单元测试（注册、路由、查询） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.1.6 | API 集成测试（登录、数据源 CRUD、审计日志查询） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.1.7 | MCP Tool 端到端测试 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |

**验收标准**：
- skills.database 模块覆盖率 >= 90%
- mcp_server 模块覆盖率 >= 90%
- auth 模块覆盖率 >= 90%
- common 模块覆盖率 >= 90%
- 其他模块覆盖率 >= 80%

#### 5.2 安全测试

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 5.2.1 | SQL 注入防护验证 | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 5.2.2 | 路径穿越防护验证 | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 5.2.3 | 权限校验测试（admin / developer 双角色） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 5.2.4 | 数据源密码加密验证（密文入库、明文不在日志中出现） | GLM 5.1 | ecc:security-review | ✅ 完成 |
| 5.2.5 | PROD 数据源权限隔离验证 | GLM 5.1 | ecc:security-review | ✅ 完成 |

**验收标准**：
- SQL 注入攻击全部被拦截
- 路径穿越攻击全部被拦截
- developer 无法访问 admin 专属功能和 PROD 数据源

#### 5.3 兼容性测试

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 5.3.1 | Oracle 11g 全量 Tool 调用测试 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.3.2 | MySQL 5.6 全量 Tool 调用测试 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.3.3 | PostgreSQL 系统库稳定性测试 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.3.4 | 目标库连接失败不影响系统库验证 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |

**验收标准**：
- Oracle 11g：database skill 5 个 Tool 全部通过
- MySQL 5.6：database skill 5 个 Tool 全部通过
- Linux SSH：server skill 6 个 Tool 全部通过（V1.0 新增）
- 目标库异常时 Web 管理端正常响应

#### 5.4 性能测试

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 5.4.1 | 登录接口并发测试（50 并发，30s） | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.4.2 | 数据源列表查询并发测试（20 并发，含分页） | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.4.3 | SQL 执行并发测试（10 并发，含风险确认） | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.4.4 | 审计日志查询并发测试（20 并发，时间范围筛选） | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |

**验收标准**：
- API 响应时间 P95 < 500ms（非 SQL 执行接口）
- SQL 执行响应时间 P95 < 3s（含目标库查询）
- MCP Tool 调用 P95 < 2s（含风险识别）
- 错误率 < 0.1%（正常负载）

#### 5.5 前端测试

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 5.5.1 | 核心组件单元测试（Vitest） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.5.2 | Pinia Store 测试（用户、数据源、权限） | GLM 5.1 | superpowers:test-driven-development | ✅ 完成 |
| 5.5.3 | 暗色主题全页面渲染验证 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |
| 5.5.4 | 双角色菜单显隐测试 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成 |

**验收标准**：
- 核心 Store 与工具函数覆盖率 >= 80%
- 暗色主题下所有页面正常显示

#### 5.6 部署与上线

| # | 任务 | AI 模型建议 | 推荐工具/Skill | 状态 |
|---|------|------------|---------------|------|
| 5.6.1 | 前端构建产物打包（`npm run build`） | GLM 5.1 | ecc:deployment-patterns | ✅ 完成（生产 192.168.1.100 已部署） |
| 5.6.2 | 后端部署脚本编写（systemd service 文件 + 用户态启停脚本） | GLM 5.1 | ecc:deployment-patterns | ✅ 完成（start_all.sh / stop_all.sh，详见部署规范 §13.7） |
| 5.6.3 | Nginx 反向代理配置 | GLM 5.1 | ecc:deployment-patterns | ✅ 完成（用户态版改用 FastAPI StaticFiles mount 单端口 8080，详见部署规范 §13.8） |
| 5.6.4 | PostgreSQL 配置调优（生产级） | GLM 5.1 | ecc:postgres-patterns | ✅ 完成（portable PG 16 + postgresql.conf + pg_hba.conf） |
| 5.6.5 | Secret 文件生成与权限设置 | GLM 5.1 | ecc:security-review | ✅ 完成（crypto-secret.key 32 raw bytes / 0600，跨环境隔离） |
| 5.6.6 | Oracle Instant Client 安装配置 | GLM 5.1 | ecc:deployment-patterns | ✅ 完成（instantclient 11.2 zip 解压，LD_LIBRARY_PATH 注入） |
| 5.6.7 | 服务启动与健康检查验证 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成（crontab @reboot + curl /api/v1/health + MCP 401 验证） |
| 5.6.8 | Claude Code 接入 MCP Server 验证 | GLM 5.1 | superpowers:verification-before-completion | ✅ 完成（23/23 用例全过，详见 `documents/aduit/20260808_mcp_verify_report_2.md`） |

**验收标准**：
- `GET /api/v1/health` 返回 `{"status": "UP"}`
- Claude Code 可通过 MCP 调用全部 11 个 Tool（database 5 + server 6）
- 日志输出正常，无 ERROR 级别异常

---

## 四、一期验收标准

### 4.1 功能验收

| # | 验收项 | 验收方式 |
|---|--------|---------|
| F1 | Claude Code 可通过 MCP 调用 Database Skill | 实际调用 execute_sql_text |
| F2 | 可执行 SQL 文本和受控范围内的本地 `.sql` 文件 | 实际调用 execute_sql_file |
| F3 | 可查询可用数据源 | 调用 list_datasources |
| F4 | 可查看审计日志 | Web 管理端查询 |
| F5 | 可配置数据源及密文密码 | Web 数据源管理页 CRUD |
| F6 | 可按用户/角色/数据源/环境控制访问 | 双角色权限测试 |
| F7 | 高风险操作触发二次确认 | 执行 DROP / DELETE 无 WHERE |
| F8 | 9 个核心页面功能正常（含服务器管理页） | 逐页验证 |

### 4.2 兼容性验收

| # | 验收项 | 验收方式 |
|---|--------|---------|
| C1 | Oracle 11g 基础连接和 SQL 执行通过 | database skill 5 Tool 全量调用 |
| C2 | MySQL 5.6 基础连接和 SQL 执行通过 | database skill 5 Tool 全量调用 |
| C3 | PostgreSQL 系统库访问稳定 | 压测 100 次查询 |
| C4 | 目标数据库连接失败不影响系统库和管理端 | 模拟目标库不可用 |
| C5 | 驱动版本与 Python 版本形成最终固化清单 | 版本锁定确认 |

### 4.3 安全与审计验收

| # | 验收项 | 验收方式 |
|---|--------|---------|
| S1 | 目标数据库密码不明文入库 | 数据库直接查询验证 |
| S2 | Secret 文件不写入代码 | `.gitignore` 检查 |
| S3 | 解密操作受权限控制 | developer 角色访问测试 |
| S4 | SQL 执行全链路可追踪 | 审计日志完整性检查 |
| S5 | SQL 注入攻击被拦截 | 注入测试 |
| S6 | 路径穿越攻击被拦截 | 路径穿越测试 |

### 4.4 性能基线

| 指标 | 目标值 |
|------|--------|
| API 响应时间 P95 | < 500ms（非 SQL 执行接口） |
| SQL 执行响应时间 P95 | < 3s（含目标库查询） |
| MCP Tool 调用 P95 | < 2s（含风险识别） |
| 错误率 | < 0.1%（正常负载） |

### 二期推迟功能说明

以下功能在原型中有设计，但经确认推迟到第二期实现：

1. **Skill 源码上传**（三种注册方式之一）：原型有拖拽上传 Tab，推迟原因：需完善解析引擎
2. **用户数据源权限分配**（`pmcp_datasource_permission` 表）：原型有环境复选框+数据源复选框，推迟原因：一期简化为角色级控制
3. **系统配置管理 API**（`pmcp_system_config` 表）：已有 ORM 模型，推迟原因：一期使用 YAML 配置
4. **细粒度权限控制**（`pmcp_permission` + `pmcp_role_permission` 表）：已有 ORM 模型和 DDL，一期简化为 admin/developer 双角色硬编码

---

## 五、质量门禁

| 检查项 | 标准 | 阻断级别 |
|--------|------|---------|
| 全部测试通过 | 0 Failure, 0 Error | 阻断 |
| skills.database 覆盖率 | >= 90% | 阻断 |
| mcp_server 覆盖率 | >= 90% | 阻断 |
| auth 覆盖率 | >= 90% | 阻断 |
| common 覆盖率 | >= 90% | 阻断 |
| 其他后端模块覆盖率 | >= 80% | 警告 |
| 前端 Store/工具函数覆盖率 | >= 80% | 警告 |
| 安全测试全通过 | SQL 注入 + 路径穿越 + 权限隔离 | 阻断 |
| 代码规范检查 | black + isort + mypy 通过 | 阻断 |

---

## 六、风险管理

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Oracle 11g 驱动兼容性 | 阶段三阻塞 | 阶段零已验证 thick 模式 6/6 通过 |
| MCP SDK 版本更新导致接口变化 | 阶段二阻塞 | 锁定 mcp==1.9.4，关注 changelog |
| 目标数据库网络不稳定 | 阶段三执行失败 | 连接超时 + 重试机制（tenacity） |
| 生产环境 Oracle Instant Client 缺失 | 部署失败 | 部署前检查清单包含 Oracle Client 安装验证 |
| SQL 解析库（sqlparse）对复杂 SQL 识别不准 | 风险等级误判 | 配合正则 + 关键词兜底，CRITICAL 级宁可多拦截 |

---

## 七、相关规范文档索引

| 文档 | 与开发计划的关系 |
|------|----------------|
| 《Platform-MCP 代码规范》 | 代码编写标准，贯穿全部阶段 |
| 《Platform-MCP 数据库脚本规范》 | 系统库建表、Alembic 迁移标准 |
| 《Platform-MCP 加解密方案说明》 | CryptoUtils 实现、密钥管理、部署集成 |
| 《Platform-MCP 测试规范文档》 | 测试策略、覆盖率要求、质量门禁标准 |
| 《Platform-MCP 部署规范》 | 生产环境部署步骤、目录结构、systemd 配置 |
| 《Platform-MCP UI 样式规范》 | 前端页面设计令牌、组件规范、布局标准 |
| 《Platform-MCP 技术架构说明文档》 | 技术选型、模块划分、接口设计的权威来源 |
| 《Platform-MCP 架构说明（正式版）》 | 项目评审、立项汇报的正式版架构说明 |
