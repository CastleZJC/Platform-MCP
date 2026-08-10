# Platform-MCP 技术架构说明文档

- **适用对象**：架构师、后端开发、前端开发、运维工程师、测试工程师
- **文档用途**：用于项目启动阶段的 IT 内部宣讲、技术评审、系统设计与实施基线对齐

---

## 版本更新日志

| 版本 | 日期 | 修订性质 | 修订摘要 | 修改人 |
|---|---|---|---|---|
| V1.0 | 2026-08-08 | 正式发布 | 一期 + Server Skill 二期专项全量上线 | castle |

---

# 1. 文档概述

## 1.1 编写背景

Platform-MCP 项目面向内部场景建设统一的 MCP 能力平台。项目首期聚焦数据库 Skill，通过标准 MCP 接口承接 Claude Code 等调用方的数据库执行请求，同时建设配套的管理界面、权限控制、状态查看和审计能力。

本文档在前期架构设计与多轮技术评审基础上，整合形成项目启动阶段的统一技术基线。

## 1.2 文档目标

- 统一整体技术方向与选型
- 统一后端、前端、数据库和部署实施基线
- 统一 MCP 扩展方式与 Skill 接口规范
- 统一模块职责与边界
- 统一接口、日志、权限、审计、安全和兼容性原则
- 明确迭代分期边界与验收标准

## 1.3 适用范围

| 角色 | 用途 |
|---|---|
| 架构师 | 架构评审与演进设计 |
| 后端开发 | 服务实现与模块边界约束 |
| 前端开发 | 页面范围与接口对接 |
| 运维工程师 | 部署、配置、监控与运行维护 |
| 测试工程师 | 测试范围界定与用例设计 |

---

# 2. 系统建设目标与原则

## 2.1 总体目标

建设一套内部统一的 MCP 服务平台：

- 提供 Claude Code 可调用的 MCP 服务入口
- 首期支持数据库 Skill，执行本地 `.sql` 文件和 SQL 文本
- 提供统一权限管理、数据源管理和审计能力
- 支持 Oracle 11g、MySQL 5.6 等存量数据库接入
- 提供密码加解密管理界面和 MCP 调用状态查看页面
- 保留后续扩展其他 Skill 的能力

## 2.2 核心建设原则

| 原则 | 说明 |
|---|---|
| 稳定优先 | 选择成熟、长期维护稳定的技术组件 |
| 兼容优先 | 兼容存量数据库（Oracle 11g、MySQL 5.6）、老驱动和传统部署方式 |
| 简单优先 | 不引入 Docker、K8s、微服务等当前阶段不必要的复杂度 |
| 扩展优先 | MCP 层按 Skill 插件式能力扩展设计，首期即固化接口规范 |
| 审计优先 | 所有关键调用、配置变更、安全操作全链路可追溯，审计从首阶段贯穿建设 |

---

# 3. 系统定位与边界

## 3.1 系统定位

- MCP 统一能力服务平台
- 首期聚焦数据库 Skill 的执行服务
- 带 Web 管理台的内部管理平台
- 可扩展其他 Skill 的技术底座

**与传统 SQL 平台的区别：** 本系统核心执行入口为 MCP（通过 Claude Code 调用），Web 端主要承担管理、审计和运维支撑职责，不作为主要 SQL 编写执行入口。

## 3.2 非目标说明

以下内容不纳入建设范围：

- Web 在线 SQL 富编辑器
- 工作流审批引擎
- 微服务拆分
- Docker/K8s 云原生部署
- 多机房高可用架构
- 大规模分布式任务调度平台

---

# 4. 总体架构设计

## 4.1 架构结论

系统采用以下架构形态：

- **Python 单体模块化架构**
- **双入口设计：FastAPI Web 管理端 + MCP Server（stdio 模式）**
- **共享业务逻辑层 + PostgreSQL 系统库**
- **Python 数据库驱动连接目标数据库（Oracle thick 模式通过 run_in_executor 异步包装）**
- **虚拟环境部署 + systemd + Nginx**

## 4.2 双入口架构设计

系统存在两个独立运行的入口进程，共享同一套业务逻辑：

### 4.2.1 FastAPI Web 入口（main.py）

- 承载 Web 管理 REST API
- 由 systemd 托管，通过 Gunicorn + Uvicorn Worker 运行
- 负责：登录认证、数据源管理、密码加解密、审计查询、用户管理

### 4.2.2 MCP Server 入口（mcp_server.py）

- 使用官方 `mcp` Python SDK，支持双传输模式：
  - **stdio 模式**（dev 默认）：由 Claude Code 作为子进程启动和管理
  - **streamable-http 模式**（prod 推荐）：作为独立 systemd 进程运行，通过 HTTP/SSE 远程调用
- 模式由 `settings.yml` 的 `mcp.transport` 字段控制
- 负责：MCP Tool 接入、Skill 路由、Tool 执行

### 4.2.3 共享业务逻辑层（core/）

两个入口共享以下模块：

- Skill 注册与路由
- SQL 执行器
- 风险识别引擎
- 数据源管理
- 密码加解密
- 审计日志
- 通用工具

## 4.3 逻辑架构分层

### 4.3.1 调用侧

- Claude Code（通过 MCP 协议调用）
- Web 管理用户（通过浏览器访问）
- 运维管理员

### 4.3.2 接入层

- MCP Tool 接口（stdio 模式）
- Web REST API（HTTP/HTTPS）

### 4.3.3 业务服务层

- 权限认证
- MCP 请求分发与 Skill 路由
- 数据源管理
- 密码加解密
- SQL 执行与风险识别
- 审计日志与状态监控

### 4.3.4 数据层

- PostgreSQL 系统库（系统管理数据）
- Oracle 11g / MySQL 5.6（业务执行目标库）

## 4.4 核心使用场景

### 场景 A：Claude Code 接入执行 SQL 脚本

Claude Code 通过添加 MCP Server 配置接入本系统。用户在 Claude Code 中持有本地 SQL 脚本，通过提示"执行数据库是测试环境"，系统自动匹配对应环境的数据源，读取 SQL 文件内容，执行 SQL 并审计过程及结果。

**调用链：**
1. Claude Code 调用 MCP Tool（execute_sql_file），传入文件路径、目标环境等参数
2. MCP Server 接收请求，路由至 Database Skill
3. 读取本地 `.sql` 文件内容，校验文件路径安全性
4. 执行 SQL 风险识别
5. 根据数据源配置建立数据库连接
6. 执行 SQL，返回执行结果
7. 写入 MCP 调用日志和审计日志

### 场景 B：高风险操作二次确认

当 SQL 执行触发高风险标识（DELETE 无 WHERE、DROP、TRUNCATE、存储过程调用等），系统返回风险提示，要求用户二次确认后方可继续执行。

**调用链：**
1. 用户发起 SQL 执行请求
2. 风险引擎识别为高风险操作（如 DELETE 无 WHERE、DROP、TRUNCATE、存储过程调用）
3. 系统返回风险等级、风险原因，等待用户确认
4. 用户确认后继续执行，或用户取消放弃执行
5. 确认/取消操作均写入审计日志

### 场景 C：管理员配置数据源密码

**调用链：**
1. 管理员进入 Web 密码加解密页
2. 输入明文密码
3. 后端执行 AES-256 加密
4. 返回密文
5. 保存到数据源配置
6. 写入加密操作审计日志

---

# 5. 技术选型基线

## 5.1 选型原则

- 选择当前仍活跃维护、社区稳定、长期可用的版本
- 在兼容 Oracle 11g、MySQL 5.6 的前提下，优先选择成熟稳定版本
- 避免使用过于激进的新特性
- 明确锁定主版本与推荐小版本，统一开发和部署环境

## 5.2 后端技术栈

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.11.9 | 正式基础运行版本，全环境统一锁定 |
| FastAPI | 0.115.0 | Web API 与管理接口框架 |
| Uvicorn | 0.30.6 | ASGI Server |
| Gunicorn | 23.0.0 | 生产环境进程管理，结合 Uvicorn Worker 使用 |
| Pydantic | 2.8.2 | 数据校验与配置建模 |
| pydantic-settings | 2.5.2 | 配置管理（mcp 1.9.4 强制依赖，2.4.0 pip 装不上）|
| SQLAlchemy | 2.0.35 | PostgreSQL 系统库 ORM（AsyncSession） |
| Alembic | 1.13.2 | 数据库版本迁移工具 |
| asyncpg | 0.30.0 | PostgreSQL 异步驱动，用于 SQLAlchemy AsyncSession |
| psycopg2-binary | 2.9.9 | PostgreSQL 同步驱动（scripts/ 同步脚本用，与 asyncpg 互补） |
| sqlparse | 0.5.0 | SQL 语句解析（execute_sql_file 多语句分句处理） |
| oracledb | 2.4.1 | Oracle 驱动（thick 模式 + run_in_executor），需安装 Oracle Instant Client 64-bit |
| aiomysql | 0.2.0 | MySQL 异步驱动，适用于 MySQL 5.6 |
| cryptography | 43.0.1 | AES-256 加解密实现 |
| passlib | 1.7.4 | 用户密码摘要处理 |
| loguru | 0.7.2 | 日志增强 |
| httpx | 0.27.2 | HTTP 客户端 |
| tenacity | 9.0.0 | 重试控制 |
| PyYAML | 6.0.2 | YAML 配置处理 |
| python-multipart | 0.0.9 | 表单与上传支持 |
| uv | 0.4.13 | Python 依赖与虚拟环境管理工具，可选 |
| pip | 24.2 | 标准包管理工具 |
| mcp | 1.9.4 | MCP Python SDK，用于构建 MCP Server |

## 5.3 前端技术栈

| 组件 | 版本 | 说明 |
|---|---|---|
| Node.js | 22.22.3 | 前端构建运行环境 |
| npm | 10.7.0 | 包管理工具 |
| Vue | 3.5.34 | 稳定主流版本 |
| Vite | 8.0.12 | 构建工具 |
| TypeScript | 6.0.2 | 类型约束 |
| Vue Router | 4.4.3 | 路由管理 |
| Pinia | 2.2.2 | 状态管理 |
| Element Plus | 2.8.1 | UI 组件库 |
| Axios | 1.7.4 | HTTP 请求 |
| ECharts | 5.5.1 | 状态监控图表，可选 |
| ESLint | 9.9.1 | 代码规范 |
| Prettier | 3.3.3 | 代码格式化 |

### 5.5.1 前端测试工具

| 组件 | 版本 | 说明 |
|---|---|---|
| Vitest | 3.x | 前端单元/组件测试引擎 |
| @vue/test-utils | 2.x | Vue 组件挂载与交互测试 |
| happy-dom | 17.x | 轻量 DOM 环境 |

## 5.4 数据库与中间件

| 组件 | 版本 | 说明 |
|---|---|---|
| PostgreSQL | 16.4 | 系统库，稳定且适合管理类数据 |
| Nginx | 1.26.1 | 静态资源托管与反向代理 |
| systemd | OS 自带 | 服务托管 |
| Linux OS | Rocky Linux 9.4 / RHEL 9.x / CentOS Stream 9 | 推荐服务器环境 |

## 5.5 测试与质量工具

| 组件 | 版本 | 说明 |
|---|---|---|
| pytest | 8.3.2 | Python 单元与集成测试主框架 |
| pytest-asyncio | 0.23.8 | 异步测试支持 |
| pytest-cov | 5.0.0 | 覆盖率统计 |
| httpx | 0.27.2 | API 测试客户端 |
| Faker | 28.4.1 | 测试数据构造 |
| Postman | 11.x | 接口测试 |
| Apache JMeter | 5.6.3 | 压测工具 |
| SonarQube | 10.6 | 代码质量检查，可选 |
| Ruff | 0.6.3 | Python 代码规范与静态检查 |
| mypy | — | Python 静态类型检查 |
| Black | 24.8.0 | 代码格式化 |
| isort | 5.13.2 | import 排序 |

## 5.6 统一异步策略

FastAPI 为异步框架，数据库驱动必须统一为异步方案以避免事件循环阻塞：

| 数据库 | 驱动 | 用途 |
|---|---|---|
| PostgreSQL 16.4（系统库） | asyncpg + SQLAlchemy AsyncSession | 系统管理数据访问 |
| Oracle 11g（目标库） | oracledb thick 模式 + run_in_executor | SQL 执行（thick 模式仅提供同步 API，通过 asyncio.run_in_executor 包装为异步调用） |
| MySQL 5.6（目标库） | aiomysql | SQL 执行 |

**禁止事项：** 一期不混用同步驱动与 FastAPI async 端点（Oracle thick 模式为例外，通过 run_in_executor 包装后事件循环保持非阻塞）。

---

# 6. 版本兼容性与前置验证

## 6.1 Python 版本策略

项目统一基线为 **Python 3.11.9**：

- 开发、测试、生产全环境统一使用 Python 3.11.9
- 不允许开发环境与生产环境混用 3.10 / 3.12
- `pyproject.toml` 声明 `requires-python = ">=3.11.9,<3.12"`
- CI/CD、虚拟环境、运维脚本全部以 3.11.9 为标准

## 6.2 Oracle 11g 驱动兼容性

### POC 验证结论（2026-06-03 完成）

`oracledb 2.4.1` thin 模式官方支持矩阵起始版本为 Oracle 12.1，**POC 确认 thin 模式无法连接 Oracle 11g**（DPY-3010 错误）。已切换至 thick 模式方案。

**驱动策略：oracledb thick 模式 + `asyncio.run_in_executor`**

- thick 模式通过 `oracledb.init_oracle_client(lib_dir=...)` 初始化，需安装 Oracle Instant Client（64-bit）
- thick 模式仅提供同步 API，通过 `asyncio.run_in_executor` 包装为异步调用
- 并发查询验证通过：事件循环保持非阻塞
- 部署要求：服务器需预装 Oracle Instant Client 64-bit

**已验证项（thick 模式，全部通过）：**

| 验证项 | 验证内容 | 结果 |
|---|---|---|
| 连接建立 | Basic/TNS 连接方式 | PASS |
| 字符集 | NVARCHAR2/NCLOB 中英文混合读写 | PASS |
| 日期类型 | DATE / TIMESTAMP / TIMESTAMP WITH TIME ZONE | PASS |
| 存储过程 | IN/OUT/INOUT 参数、REF CURSOR | PASS |
| CLOB/BLOB | 10k+ 大字段读写 | PASS |
| 事务控制 | autocommit=false + commit/rollback | PASS |

## 6.3 MySQL 5.6 驱动兼容性

### POC 验证结论（2026-06-03 完成）

`aiomysql 0.2.0` 作为 MySQL 5.6 异步驱动，**14/14 子项全部通过**。

**驱动决策：使用 aiomysql 直接异步调用**

- 驱动对比：aiomysql 原生异步性能最优（~43.2ms/query 并发），PyMySQL + executor 约慢 8 倍，asyncmy 为兼容备选
- 确定使用 aiomysql，不引入 PyMySQL 或 asyncmy

**已验证项（全部通过）：**

| 验证项 | 结果 | 说明 |
|---|---|---|
| 连接 + 连接池 | PASS | aiomysql.create_pool 正常 |
| 字符集（utf8mb4） | PASS | 中文 + emoji 读写正确 |
| 日期类型 | PASS | DATE / DATETIME / TIMESTAMP |
| 存储过程（IN/OUT） | PASS | callproc + SELECT @ 变量 |
| 多语句执行（nextset） | PASS | nextset() 结果集切换正常 |
| 事务控制 | PASS | commit/rollback/autocommit 均正确 |
| 认证协议 | PASS | mysql_native_password 兼容 |

## 6.4 MCP Python SDK 兼容性

- 锁定 `mcp` SDK 版本，业务逻辑与协议层解耦
- 评估 SDK 版本升级时做兼容性回归

## 6.5 SQLAlchemy 2.0 说明

SQLAlchemy 2.0 相较 1.x 存在 API 变更：

- 查询方式：`select()` 替代 `session.query()`
- 异步会话：必须使用 `AsyncSession`
- 团队需统一 2.0 范式，不混用 1.x 写法

## 6.6 Pydantic v2 说明

Pydantic v2 相较 v1 存在 API 变更：

- 字段验证：`@field_validator` 替代 `@validator`
- 模型导出：`model_dump()` 替代 `dict()`
- 配置：`model_config = ConfigDict(...)` 替代 `class Config`

## 6.7 启动前验证清单

项目启动前必须完成以下验证：

| 编号 | 验证项 | 优先级 | 结果 |
|---|---|---|---|
| V1 | Python 3.11.9 + FastAPI 空项目运行 | P0 | -- |
| V2 | Claude Code + MCP Python SDK stdio 模式最小化 PoC | P0 | -- |
| V3 | oracledb thin 模式 + Oracle 11g 连接验证 | P0 | FAIL（DPY-3010，已切换 thick 模式） |
| V4 | oracledb thick 模式 + Oracle 11g 存储过程验证 | P0 | PASS（thick 模式 6/6 项通过） |
| V5 | aiomysql + MySQL 5.6 连接验证 | P0 | PASS |
| V6 | aiomysql + MySQL 5.6 多语句执行验证 | P0 | PASS |
| V7 | SQLAlchemy AsyncSession + asyncpg + PostgreSQL 16.4 验证 | P0 | -- |
| V8 | cryptography AES-256-GCM 加解密验证 | P1 | -- |

---

# 7. 模块化架构设计

## 7.1 一期模块清单

V1.0（含 Server Skill 二期专项）共 8 个顶级包：

| 模块 | 包含能力 | 说明 |
|---|---|---|
| `platform_mcp.api` | FastAPI Web 接口 | 前端对接接口与页面数据聚合输出（10 个 .py 扁平布局） |
| `platform_mcp.auth` | 认证鉴权 | 登录认证、用户/角色/权限管理、API Key 双存储 |
| `platform_mcp.datasource` | 数据源管理 + 密码加解密 | 数据源配置、环境管理、密码加密解密 |
| `platform_mcp.server` | 服务器管理（Linux SSH/SFTP 目标） | 服务器配置、SSH 凭证加密、 mirrors datasource/ 结构 |
| `platform_mcp.mcp_server` | MCP 接入 + Skill 接口 + 注册路由 + Skill 管理 | MCP 协议接入（双传输 stdio + streamable-http）、Skill 统一接口定义、Skill 注册与路由分发、Skill 管理与生命周期 |
| `platform_mcp.skills.database` | 数据库 Skill + SQL 执行器 + 风险引擎 | 数据库 Skill 业务逻辑、SQL 执行、风险识别（5 tools） |
| `platform_mcp.skills.server` | 服务器 Skill + SSH/SFTP 执行器 + Shell 风控 | 服务器 Skill 业务逻辑、SSH/SFTP 执行、Shell 4 级风控（6 tools） |
| `platform_mcp.skills.common` | Skill 共用层 | RiskLevel/RiskResult + 环境权限校验（database + server 共用） |
| `platform_mcp.audit` | 审计 + 状态监控 | 审计日志记录、MCP 调用状态统计、服务运行状态输出 |
| `platform_mcp.common` | 通用工具 | 通用异常、响应模型、枚举、工具类、常量 |

> **计数口径**：顶级 Python 包 8 个（`platform_mcp/{api, auth, datasource, server, mcp_server, skills, audit, common}`，其中 `skills/` 含 3 子包）；API 路由模块 10 个（`api/*.py`）；MCP 工具 11 个（database 5 + server 6）。

## 7.2 模块职责详述

### 7.2.1 platform_mcp.api

- 提供 Web 管理 REST API
- 前端页面数据聚合输出
- 对接 auth、datasource、audit 等模块

### 7.2.2 platform_mcp.auth

- 用户名密码登录认证
- 用户、角色、权限管理
- 资源访问鉴权
- Session 管理

### 7.2.3 platform_mcp.datasource

- 数据源信息管理（增删改查、启停）
- 环境管理（DEV/TEST/PROD）
- 连接参数管理
- 数据源权限控制
- 密码加密与解密
- 密钥读取与密码操作审计

### 7.2.4 platform_mcp.mcp_server

- MCP 协议接入与 Tool 参数解析
- Skill 统一接口标准定义
- Skill 注册、发现与路由分发
- 调用链路上下文封装
- 统一响应结构
- MCP 调用并发限流
- Skill 管理与生命周期（查看、启停、审核） — developer 提交 Skill 进入"待审核"状态，admin 审核通过后启用或驳回
- Skill 注册方式支持：
  - 页面新增：通过 Web 管理端表单提交 Skill 信息
  - 源码上传解析：上传 .py / .jar 源码文件，系统自动解析 Skill 信息（编码、名称、Tool 列表），管理员确认后完成注册
  - 装饰器注册：通过 `@register_skill` 装饰器在代码中静态注册

### 7.2.5 platform_mcp.skills.database

- 数据库 Skill 业务逻辑
- Tool 能力落地（execute_sql_file、execute_sql_text、validate_sql、list_datasources、get_execution_status）
- SQL 执行（多语句分段、查询结果映射、存储过程调用）
- SQL 风险识别（语句类型、高危标记、解析失败记录）

### 7.2.6 platform_mcp.audit

- 审计日志记录（登录登出、SQL 执行、数据源管理、用户管理、密码加密、Skill 管理）
- MCP 调用状态统计
- 服务运行状态输出
- 概览统计数据输出

### 7.2.7 platform_mcp.common

- 通用异常与错误码
- 统一响应模型
- 公共枚举
- 工具类与常量

## 7.3 Skill 注册方式

一期采用基于 `typing.Protocol` 的 Skill 接口定义和装饰器注册模式：

- Skill 接口通过 `Protocol` 类定义，明确 `skill_name`、`list_tools`、`validate`、`execute`、`support` 五个方法签名
- 具体 Skill 实现通过 `@register_skill("database")` 装饰器完成注册
- Skill Registry 维护 `dict[str, Skill]` 映射表，根据 Tool 名称前缀路由到对应 Skill

## 7.4 二期模块拆分预案

当第二个 Skill 落地时，按需从现有模块提取：

| 拆分项 | 来源 | 触发条件 |
|---|---|---|
| skill_api | mcp_server | 第二个 Skill 落地时提取 Skill 统一接口为独立模块 |
| skill_registry | mcp_server | Skill 注册路由逻辑复杂度增加时独立 |
| sql_executor | skills.database | 引入 DatabaseDialect 方言抽象层时独立 |
| risk_engine | skills.database | 风险规则可配置化改造时独立 |
| monitor | audit | 监控指标与审计日志职责分化时独立 |
| crypto | datasource | 加解密逻辑复杂度增加时独立 |

---

# 8. MCP 能力架构

## 8.1 设计原则

MCP 层按"统一入口 + Skill 扩展"设计：

- MCP Server 负责协议接入
- Skill 负责能力实现
- Registry 负责路由分发
- Audit 负责全链路记录

**关键约束：** Database Skill 相关逻辑不得侵入 mcp_server。mcp_server 只处理协议接入、参数标准化、上下文封装和响应封装。

## 8.2 一期 Skill 规划

一期仅建设 `database` Skill。一期 Web 管理端新增 Skill 管理页，支持查看已注册 Skill 列表、使用方式、Skill 启停与审核操作。Skill 注册方式详见 §7.2.4。developer 提交的 Skill 状态为"待审核"，需 admin 审核通过后方可启用。

二期预留：`file`、`log`、`config`、`deploy`。

> 一期后增补（2026-08-07）：新增 `server` Skill（Linux SSH/SFTP，6 tools：execute_command / upload_file / download_file / list_servers / validate_command / get_server_execution_status）。镜像 database skill 结构，新增 `platform_mcp/server/` 包 + `platform_mcp/skills/server/` 包 + `platform_mcp/skills/common/`（共用 risk_types + permission）。Shell 风控 4 级（CRITICAL: rm -rf / mkfs dd fork bomb shutdown... / HIGH: sudo systemctl stop... / MEDIUM: curl nohup... / LOW: ls cat grep...），PROD 自动升 CRITICAL。upload/download 写入系统目录（/etc /boot /usr 等）强制 CRITICAL 走 confirm_token，>400MB 文件判 HIGH。新增依赖 `asyncssh==2.17.0`。审计 resource_type='shell'（execute/upload/download）+ 'server'（list_servers / get_status）；MCP 调用日志 input_summary 含 `skill=server | tool=... cmd=...` 命令摘要。

### 8.2.1 二期功能规划清单（开发计划 §5 明确推迟，文档与代码已对齐）

| # | 功能 | 当前实现状态 |
|---|---|---|
| 1 | Skill 表单/源码上传 | `api/skills.py:create_skill` 返回 501；前端 `SkillPage.vue:94` 置灰按钮 title="二期功能" |
| 2 | 数据源权限分配（用户↔环境↔数据源三维） | 表 `pmcp_datasource_permission` 已建 + ORM 已定义（`datasource/models.py:32`），业务逻辑/API 二期补 |
| 3 | 系统配置管理 API（CRUD `pmcp_system_config`） | 表已建 + ORM 已定义（`common/models.py:9`），REST API 二期补（一期用 YAML 配置） |

## 8.3 一期 Tool 规划

Database Skill 提供：

| Tool | 说明 |
|---|---|
| `execute_sql_file` | 接收文件路径，读取本地 SQL 文件并执行 |
| `execute_sql_text` | 接收 SQL 文本直接执行 |
| `validate_sql` | 校验 SQL 语法并返回风险等级 |
| `list_datasources` | 列出可访问的数据源 |
| `get_execution_status` | 查询异步执行任务的状态 |

### 8.3.1 Server Skill 二期专项（2026-08-07 落地）

一期后增补的 Server Skill 通过 `asyncssh==2.17.0`（pure Python，复用 cryptography）实现 Linux SSH/SFTP 远程操作，与 Database Skill 共用 `platform_mcp/skills/common/`（`risk_types.py` + `permission.py`）。

| Tool | 风控 | 说明 |
|---|---|---|
| `execute_command` | LOW~HIGH | 远程 Shell 执行（多语句 / sudo / 未识别命令触发 HIGH，需 confirm_token） |
| `upload_file` | LOW~CRITICAL | SFTP 上传（生产 allowed_sql_dirs 为空时全部拦截） |
| `download_file` | LOW~CRITICAL | SFTP 下载（敏感路径 `/etc/*`、`/boot/*` 自动升 CRITICAL） |
| `list_servers` | — | 列出可访问的 SSH 服务器 |
| `validate_command` | — | 校验命令风险等级（不发送远端，CRITICAL 也可暴露） |
| `get_server_execution_status` | — | 查询异步执行任务状态（30 分钟 TTL） |

**4 级风控**：
- LOW：ls / cat / grep 等只读命令 → 直接放行
- MEDIUM：rm + /tmp 前缀等 → 放行 + 审计
- HIGH：多语句、未识别、psql 直连等 → 返回 confirm_token，二次确认后通过（token 一次性，反重放）
- CRITICAL：rm -rf /、mkfs、dd、fork bomb、shutdown 等 → 仅 validate 端点暴露，execute 端点不接受

**PROD 自动升 CRITICAL**：env_code='PROD' 的所有 server skill execute 调用强制升 CRITICAL，developer 角色无权访问，admin 角色亦需走 confirm_token 二次确认。

## 8.4 Skill 统一接口

每个 Skill 实现需统一具备以下方法：

| 方法 | 说明 |
|---|---|
| `skill_name()` | 返回 Skill 名称 |
| `list_tools()` | 返回该 Skill 提供的 Tool 列表及元数据 |
| `validate()` | 校验 Tool 输入参数 |
| `execute()` | 执行 Tool 逻辑 |
| `support()` | 判断是否支持指定 Tool |

二期扩展时预留生命周期方法：`initialize()`、`shutdown()`。

## 8.5 Tool 元数据结构

每个 Tool 应声明完整元数据：

| 字段 | 说明 |
|---|---|
| tool_name | Tool 唯一标识 |
| display_name | 显示名称 |
| description | 功能描述 |
| input_schema | 输入参数 JSON Schema |
| output_schema | 输出结构 JSON Schema |
| required_permissions | 所需权限列表 |
| supported_envs | 支持的环境列表 |
| risk_level | 默认风险等级 |
| timeout_seconds | 超时上限 |
| audit_required | 是否审计 |

## 8.6 统一上下文信息

MCP 调用上下文统一封装：

| 字段 | 说明 |
|---|---|
| trace_id | 全链路追踪标识 |
| request_id | 请求唯一标识 |
| operator | 操作人 |
| skill_name | Skill 名称 |
| tool_name | Tool 名称 |
| target_datasource | 目标数据源编码（可选） |
| target_env | 目标环境标识（可选） |
| request_time | 请求时间 |
| risk_level | 风险等级 |
| execution_status | 执行状态 |

**设计原则：** 审计主表保留通用字段，数据库专有字段（datasource_code、env_code）作为可选扩展字段，确保上下文结构面向所有 Skill 通用。

## 8.7 MCP 认证策略

一期通过 **API Key 机制** 实现 MCP 层用户级认证：

- admin 在 Web 管理端创建用户时，系统自动生成 API Key（格式：`pmcp_` + 43 字符随机串）
- 用户将 Key 写入 Claude Code 配置（`~/.claude.json`），stdio 模式通过 `env.PLATFORM_MCP_API_KEY` 传递，streamable-http 模式通过 HTTP Header `PLATFORM_MCP_API_KEY` 传递
- MCP Server 校验 Key 后确定调用者身份（user_id / username / role_code），后续 tool 执行按角色判定权限（如 PROD 环境仅 admin 角色可访问）
- Key 的 SHA-256 哈希存储于 `pmcp_api_key` 表，支持撤销/重置操作
- Web 管理端个人设置页可查看、复制、重置自己的 API Key

两种模式的 Key 传递方式：

| 模式 | Key 传递方式 |
|------|-------------|
| stdio | 环境变量 `PLATFORM_MCP_API_KEY`，进程启动时校验一次 |
| streamable-http | HTTP Header `PLATFORM_MCP_API_KEY`，每次请求校验 |

---

# 9. 数据源与目标数据库设计

## 9.1 系统库与目标库分离原则

- PostgreSQL 用于系统管理数据
- Oracle/MySQL 用于业务执行目标库
- 系统库访问与目标库访问逻辑严格分离
- 系统库使用 SQLAlchemy AsyncSession（asyncpg 驱动）
- 目标库采用按需异步连接，不长期持有连接池

## 9.2 数据源配置内容

每个数据源包括：

| 配置项 | 说明 |
|---|---|
| 数据源编码 | 唯一标识 |
| 数据源名称 | 显示名称 |
| 数据库类型 | Oracle / MySQL |
| 主机地址 | IP 或域名 |
| 端口 | 数据库端口 |
| 实例名/服务名 | 数据库实例或 Oracle Service Name |
| 用户名 | 连接用户 |
| 密文密码 | AES-256 加密存储 |
| 环境标识 | DEV / TEST / PROD |
| 是否启用 | 启停状态 |
| 驱动类型 | 连接驱动标识 |
| 连接串 | 完整连接 URL |
| 备注信息 | 补充说明 |

### 数据源环境权限约束

PROD 环境数据源仅 admin 角色可调用。developer 角色通过 MCP 调用 PROD 数据源时，系统返回"权限不足"错误。此为数据源级别限制，非 Skill 级别。

## 9.3 目标库连接策略

- 每次执行通过 `contextlib.asynccontextmanager` 创建连接 → 执行 → 关闭
- 连接超时默认 30 秒，执行超时默认 300 秒
- 按数据源维护 `asyncio.Semaphore` 控制最大并发连接数（默认 5）
- 不为所有目标数据库长期持有连接池，降低老旧数据库连接稳定性风险

## 9.4 一期支持矩阵

| 能力 | Oracle 11g | MySQL 5.6 |
|---|---|---|
| SELECT 查询 | 支持（已验证） | 支持（已验证） |
| INSERT / UPDATE / DELETE | 支持（已验证） | 支持（已验证） |
| 多语句执行 | 需验证（一期 sqlparse 拆分处理） | 支持（已验证，nextset） |
| 存储过程调用 | 支持（已验证，IN/OUT/INOUT + REF CURSOR） | 支持（已验证，IN/OUT） |
| 事务控制 | 支持（已验证） | 支持（已验证） |
| CLOB/BLOB 大字段 | 支持（已验证，10k+） | 支持（已验证，10k+） |
| 字符集 | 支持（已验证，NVARCHAR2/NCLOB 中英文混合） | 支持（已验证，utf8mb4 中文+emoji） |

---

# 10. SQL 执行设计

## 10.1 执行方式

| 方式 | 说明 |
|---|---|
| SQL 文件执行 | 接收文件路径，读取本地 `.sql` 文件执行 |
| SQL 文本执行 | 接收 SQL 文本直接执行 |

## 10.2 文件执行流程

1. 接收文件路径参数
2. **路径安全校验**（白名单目录、禁止路径穿越、禁止符号链接跟随、限制扩展名为 `.sql`、限制文件大小）
3. 读取文件内容
4. 编码校验
5. 语句拆分
6. 风险识别
7. 建立数据库连接
8. 逐语句执行
9. 汇总结果返回

## 10.3 路径安全约束

SQL 文件执行必须满足以下安全条件：

- 配置允许读取的根目录白名单（如 `/opt/Platform-MCP/sql-scripts/`）
- 使用 `Path.resolve()` 解析绝对路径，校验是否在白名单目录内
- 禁止符号链接跟随
- 仅允许 `.sql` 扩展名
- 限制单文件大小（建议 10MB），防止内存溢出

## 10.4 多语句处理

一期采用简单稳定策略：

- 基于 `sqlparse` 按分号拆分，处理注释和字符串常量中的分号
- Oracle PL/SQL 块建议单语句执行或采用明确分隔符规范
- 一期不承诺完全通用 SQL 脚本解析能力
- 解析失败的 SQL 统一标记为 HIGH 风险

## 10.5 异步执行与超时控制

- SQL 执行设置超时上限（默认 300 秒），超时自动终止
- `execute_sql_file/text` 支持异步执行模式，立即返回 `execution_id`
- 结果通过 `get_execution_status` 获取
- 状态值：PENDING / RUNNING / SUCCESS / FAILED / TIMEOUT

## 10.6 并发限流

- 全局 `asyncio.Semaphore` 控制最大并发执行数
- 按数据源维护独立 Semaphore 控制单数据源并发上限
- 限流参数存储在 `pmcp_system_config` 表，支持动态调整

## 10.7 返回结果结构

| 字段 | 说明 |
|---|---|
| success | 是否成功 |
| affectedRows | 影响行数 |
| resultSummary | 结果集摘要 |
| errorMessage | 错误信息 |
| durationMs | 执行耗时 |
| riskLevel | 风险等级 |
| auditId | 审计编号 |

---

# 11. 风险识别设计

## 11.1 识别目标

对 SQL 在执行前做基础风险识别，降低误操作风险。

## 11.2 一期识别范围

一期采用 `sqlparse` + 正则 + 关键词匹配，不引入 SQL AST 解析器：

| 识别项 | 说明 |
|---|---|
| 语句类型识别 | DDL / DML / DCL 分类 |
| DDL 检测 | CREATE、ALTER、DROP 等 |
| 高危操作标记 | DROP、TRUNCATE |
| 全表操作检测 | DELETE / UPDATE 无 WHERE |
| 存储过程调用检测 | CALL / EXEC 语句标记为 HIGH |
| 解析失败记录 | 标记为 HIGH 风险 |

## 11.3 风险等级与处理策略

| 等级 | 说明 | 处理策略 |
|---|---|---|
| LOW | SELECT 查询等低风险操作 | 正常执行 |
| MEDIUM | INSERT、带 WHERE 的 DML | 正常执行 |
| HIGH | 无 WHERE 的 UPDATE/DELETE、存储过程调用、解析失败 | 提示用户二次确认 |
| CRITICAL | DROP、TRUNCATE、生产库 DDL | 强制二次确认 |

## 11.4 局限性声明

风险识别为辅助参考，不保证 100% 准确。一期不覆盖以下场景：

- PL/SQL 块内部语义分析
- 嵌套子查询风险评估
- 存储过程内部操作识别

## 11.5 生产库保护

- 生产库（env_code=PROD）数据源默认标记为"受保护"
- 受保护数据源的 DDL 和 DELETE WITHOUT WHERE 操作强制标记为 CRITICAL
- 风险规则可通过 `pmcp_system_config` 表配置开关，无需改代码

## 11.6 高风险操作二次确认

HIGH/CRITICAL 级别操作处理流程：

1. 风险引擎识别为 HIGH/CRITICAL 操作
2. 返回风险等级、风险原因，以及一次性 `confirm_token`（服务端生成，绑定风险上下文，防重放）
3. 用户确认后回传 `confirm_token`，服务端校验通过后继续执行
4. 用户未确认（不传 token）则拒绝执行
5. 确认与拒绝操作均写入审计日志

---

# 12. 安全设计

## 12.1 认证方案

Web 管理端采用 Session 方案：

- 用户名密码登录
- Session 存储于 PostgreSQL，避免进程重启导致会话失效
- Session 超时策略建议不超过 30 分钟
- 登录页采用双栏布局：左侧为企业项目视觉区（项目名称、功能亮点），右侧为登录表单，底部版权说明。角色由用户名自动映射（admin/developer 双角色绑定用户账号），无需用户手动选择

选择 Session 而非 JWT 的原因：内部系统简单稳定，后台管理场景更易控制，更适合权限收敛和会话失效管理。

MCP 层认证策略参见 8.7 节。

## 12.2 权限模型

权限控制维度：

| 维度 | 说明 |
|---|---|
| 用户 | 系统用户 |
| 角色 | 用户分组 |
| Skill | 能力模块 |
| Tool | 具体操作 |
| 环境 | DEV / TEST / PROD |
| 数据源 | 具体数据库实例 |
| 页面功能点 | 菜单或按钮级控制 |

**一期重点控制：** Tool + 环境 + 数据源维度。页面功能点权限先做到菜单级基础控制。个人设置页（显示名称、邮件地址、修改密码）仅当前登录用户可修改自己的信息。

### 一期角色定义（双角色模型）

一期简化为两个预置角色：

| 角色 | 标识 | 说明 |
|---|---|---|
| 系统管理员 | admin | 全页面、全操作权限 |
| 开发人员 | developer | 受限权限，详见下表 |

#### developer 角色权限范围

| 功能域 | developer 权限 |
|---|---|
| Skill 管理 | 可新增 Skill（状态为"待审核"），不可禁用/审核 Skill；仅可见自己上传的 Skill |
| 数据源管理 | 仅查看 + 测试连接，不可新增/修改/禁用数据源 |
| 审计日志 | 仅可查看自己的操作记录 |
| 密码加密页 | 页面不可见 |
| 用户管理页 | 页面不可见 |
| MCP 接入指南 | 可见 |

#### Skill 审核流程

1. developer 通过 Web 管理端提交 Skill → 状态为"待审核"
2. admin 审核后可"启用"（批准）或"驳回"
3. 仅 admin 可执行 Skill 的禁用与审核操作

## 12.3 密码加解密方案

- 算法：AES-256
- 模式：GCM 优先，CBC 作为兼容备选
- IV / nonce：随机生成
- 输出：Base64 编码

**密钥管理：**

- 存储于独立 secret 文件（`crypto-secret.key`）
- 严禁入库明文保存
- 严禁写死在代码中
- secret 文件权限收敛至仅应用运行用户可读

## 12.4 密码解密控制

- 解密操作默认受控，仅授权用户可执行
- 解密结果仅用于连接测试，不在页面展示完整明文密码
- 每次解密操作写入审计日志
- 审计日志中严禁记录明文密码

## 12.5 审计要求

以下操作必须审计，**审计写入能力从第一阶段开始建设**：

- 登录登出
- MCP Tool 调用
- SQL 执行
- 数据源新增修改删除
- 权限变更
- 密码加密
- 密码解密
- 系统参数修改

**分期覆盖策略：**
- Sprint 1：登录登出、数据源变更、加密操作审计
- Sprint 2：MCP 调用、SQL 执行、风险记录审计

---

# 13. Web 前端设计基线

## 13.1 页面范围与优先级

### V1.0 必须交付（9 个核心页面，含服务器管理）

| 页面 | 优先级 | 理由 |
|---|---|---|
| 登录页 | P0 | 无认证则无法使用 |
| Skill 管理页 | P0 | Skill 注册信息查看、使用方式说明、启停管理、审核操作 |
| 数据源管理页 | P0 | MCP 调用的前置依赖 |
| 密码加密页 | P0 | 数据源配置的配套能力 |
| 审计日志页 | P0 | 合规要求 |
| 用户管理页 | P1 | 基本账号管理 |
| 个人设置页 | P1 | 用户自定义显示名称、邮件地址、修改密码 |
| MCP 接入指南页 | P1 | Claude Code 配置步骤、JSON 配置示例（stdio 模式）、已注册 Skill/Tool 列表、环境要求、FAQ；所有用户可见 |

### 侧边栏分组

侧边栏按以下三个分组组织，根据登录角色动态显隐：

| 分组 | 包含页面 | 可见角色 |
|---|---|---|
| 管理中心 | Skill 管理、数据源管理、审计日志 | admin + developer |
| 系统管理 | 密码加密、用户管理 | 仅 admin |
| 帮助 | MCP 接入指南 | admin + developer |

### 一期延后至二期（4 个页面）

| 页面 | 延后理由 |
|---|---|
| 系统概览页 | 一期数据量少，概览价值有限 |
| 角色权限管理页 | 简化为一期仅支持预置角色 |
| MCP 调用状态页 | 审计日志页可暂时替代 |
| 系统配置页 | 初期配置项少，可通过配置文件管理 |

## 13.2 前端职责边界

**前端负责：** 页面交互、表单校验、数据展示、调用后端接口

**前端不负责：** SQL 真正执行、数据库密码真实加解密、风险识别逻辑、权限判定最终决策

## 13.3 前端版本锁定

一期在 `package.json` 中使用精确版本号（不用 `^`），锁定当前版本组合，避免开发期间版本漂移。一期完成后统一评估是否升级。

## 13.4 前端工程规范

- ESLint + Prettier 统一代码风格
- TypeScript strict 模式
- API 层统一 Axios 封装，统一错误处理

---

# 14. 系统库设计基线

## 14.1 核心表清单

- `pmcp_user` — 用户信息
- `pmcp_role` — 角色信息
- `pmcp_user_role` — 用户角色关系
- `pmcp_permission` — 权限定义
- `pmcp_role_permission` — 角色权限关系
- `pmcp_api_key` — API Key 双存储（key_hash SHA-256 校验 + key_encrypted AES-GCM admin reveal）
- `pmcp_datasource` — 数据源配置
- `pmcp_datasource_permission` — 数据源权限关系（表已建，业务逻辑二期实现）
- `pmcp_server` — 服务器配置（Linux SSH/SFTP 目标，含 encrypted_password + encrypted_ssh_key + allowed_paths）
- `pmcp_server_permission` — 服务器权限关系（表已建，业务逻辑二期实现）
- `pmcp_audit_log` — 审计日志
- `pmcp_mcp_call_log` — MCP 调用日志
- `pmcp_crypto_operation_log` — 加解密操作日志
- `pmcp_system_config` — 系统参数配置（表已建，CRUD API 二期实现）
- `pmcp_skill` — Skill 注册信息（编码、名称、描述、状态、注册方式、Tool 数量）

共 **15 张系统表**（grep `__tablename__` 实测，含 V1.0 新增 `pmcp_server` + `pmcp_server_permission`）。其中 `pmcp_datasource_permission`、`pmcp_server_permission`、`pmcp_system_config` 为已建未用资产（ORM 已定义，业务逻辑/API 留待二期实现）。V1.0 alembic 单一发布修订：`alembic/versions/001_initial_tables.py`（合并历史 10 个迭代 ba0102b846dd → ch0101a947f6 的最终态）。

## 14.2 审计日志表核心字段

| 字段 | 说明 |
|---|---|
| id | 主键 |
| trace_id | 全链路追踪标识 |
| request_id | 请求唯一标识 |
| operator | 操作人 |
| skill_name | Skill 名称 |
| tool_name | Tool 名称 |
| resource_type | 资源类型 |
| resource_id | 资源标识 |
| env_code | 环境标识（可选） |
| request_summary | 请求摘要 |
| result_status | 结果状态 |
| risk_level | 风险等级 |
| error_code | 错误码 |
| error_message | 错误信息 |
| duration_ms | 耗时毫秒 |
| extra_data | 扩展数据（JSONB，预留给二期 Skill 扩展） |
| inserted_at | 创建时间 |
| updated_at | 更新时间 |
| inserted_by / updated_by | 审计字段 |

**设计原则：** datasource_code 和 env_code 作为可选字段，确保审计结构面向所有 Skill 通用。extra_data 使用 JSONB 类型存储，为二期新增 Skill 预留扩展空间。**V1.0 已删除** 历史 `start_time` / `end_time` 僵尸列（迁移 `cg0101a947f5_drop_audit_dead_columns.py`，已合并入 `001_initial_tables.py`），用 `duration_ms` 单字段表达耗时。

## 14.3 日志表增长策略

`pmcp_audit_log` 和 `pmcp_mcp_call_log` 数据量增长后，采用 PostgreSQL 原生按时间分区表。保留周期与归档策略与运维团队协商确定。

---

# 15. 接口设计基线

## 15.1 Web 管理接口

- 登录接口
- 用户管理接口
- 角色管理接口
- 数据源管理接口
- 密码加解密接口
- 审计日志查询接口
- MCP 状态查询接口
- 系统配置接口

## 15.2 MCP Tool 接口

> **完整 11 工具清单**：database skill 5 tools 见下表；server skill 6 tools（execute_command / upload_file / download_file / list_servers / validate_command / get_server_execution_status）详见 §8.3.1。

| Tool | 输入参数 | 输出 |
|---|---|---|
| execute_sql_file | file_path, datasource_code, env_code, confirm_token(可选) | 执行结果结构 |
| execute_sql_text | sql_text, datasource_code, env_code, confirm_token(可选) | 执行结果结构 |
| validate_sql | sql_text, datasource_code | 风险等级与风险原因 |
| list_datasources | env_code(可选) | 数据源列表 |
| get_execution_status | execution_id | 状态与结果 |

## 15.3 统一响应格式

| 字段 | 类型 | 说明 |
|---|---|---|
| code | int | 状态码 |
| message | string | 状态描述 |
| data | object | 业务数据 |
| trace_id | string | 追踪标识 |
| timestamp | long | 时间戳 |

## 15.4 错误码规范

| 分类 | 错误码范围 | 说明 |
|---|---|---|
| MCP 错误 | 10001-10999 | 协议错误、Tool 未找到、参数校验失败 |
| 认证错误 | 11001-11999 | 权限拒绝、会话过期 |
| 数据源错误 | 12001-12999 | 连接失败、超时、驱动异常 |
| SQL 执行错误 | 13001-13999 | 语法错误、执行失败、超时 |
| 风险拦截错误 | 14001-14999 | 高风险被拦截、需要二次确认 |
| 系统错误 | 15001-15999 | 内部错误、配置缺失 |
| 安全错误 | 16001-16999 | 路径穿越、权限边界等安全拦截 |

---

# 16. 日志与监控设计

## 16.1 应用日志分类

| 类型 | 说明 |
|---|---|
| 应用运行日志 | 服务启动、停止、异常 |
| 安全日志 | 认证失败、权限拒绝 |
| 审计日志 | 关键操作审计记录（入库），审计范围详见 §12.5 |
| SQL 执行日志 | SQL 语句与执行结果 |
| MCP 调用日志 | MCP 请求与响应 |
| 错误日志 | 异常堆栈 |

## 16.2 日志输出

- 开发环境：控制台输出
- 测试/生产环境：文件输出，按天滚动
- 保留周期按运维规范设置
- 推荐 JSON 结构化输出，便于检索与审计
- 使用 loguru 作为主日志库

## 16.3 一期监控

采用轻量监控：

- 应用存活检查
- Python 进程监控
- 内存使用监控
- CPU 使用监控
- 错误率监控
- MCP 调用量统计
- 执行耗时统计

---

# 17. 部署与运维基线

## 17.1 部署形态

传统部署，不采用 Docker：

- Python 虚拟环境部署
- Gunicorn + Uvicorn Worker 运行 FastAPI Web 端
- MCP Server 由 Claude Code 以子进程方式启动（stdio 模式）
- 前端静态资源部署
- PostgreSQL 独立部署
- Nginx 反向代理
- systemd 托管 Web 进程

## 17.2 双进程部署说明

| 进程 | 启动方式 | 运行内容 |
|---|---|---|
| Web 进程 | systemd 托管（Platform-MCP.service） | Gunicorn + Uvicorn Worker 运行 FastAPI |
| MCP Server 进程 | dev: Claude Code 子进程（stdio）<br>prod: systemd 托管（Platform-MCP-mcp.service，streamable-http） | MCP Python SDK，模式由 settings 决定 |

两个进程共享 `/opt/Platform-MCP/app/` 下的业务逻辑代码和 `/opt/Platform-MCP/config/` 下的配置文件。

## 17.3 目录结构

```
/opt/Platform-MCP/
├── app/           # Python 应用代码
├── venv/          # 虚拟环境
├── config/        # 配置文件
├── secret/        # 密钥文件
├── logs/          # 日志文件
├── scripts/       # 运维脚本
└── sql-scripts/   # SQL 脚本文件（白名单目录）
```

## 17.4 配置文件分离

| 文件 | 说明 |
|---|---|
| `settings.yml` | 主配置 |
| `settings-dev.yml` | 开发环境配置 |
| `settings-test.yml` | 测试环境配置 |
| `settings-prod.yml` | 生产环境配置 |
| `pyproject.toml` | 项目元数据与依赖声明 |
| `crypto-secret.key` | 加密密钥 |

## 17.5 systemd 服务

服务名：`Platform-MCP.service`

启动命令：

```
gunicorn platform_mcp.main:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8080
```

## 17.6 Nginx 职责

- 托管前端静态资源
- 反向代理后端接口
- 路由转发
- 访问日志记录

## 17.7 运维注意事项

- Python 版本全环境统一为 3.11.9
- 虚拟环境隔离，不使用系统 Python
- secret 文件权限收敛（仅应用运行用户可读）
- 日志按目录输出，配置按天滚动
- 内网环境需准备离线安装方案（wheelhouse）

---

# 18. 测试基线

## 18.1 测试范围

- Web 页面功能
- 后端接口
- MCP Tool 调用
- 数据源管理
- 密码加解密
- 审计日志
- Oracle/MySQL 兼容验证

## 18.2 测试分类

| 类型 | 说明 |
|---|---|
| 单元测试 | 各模块核心逻辑 |
| 集成测试 | 模块间协作 |
| 接口测试 | REST API 与 MCP Tool |
| 兼容性测试 | Oracle 11g / MySQL 5.6 驱动与执行 |
| 安全测试 | 权限隔离、路径穿越、密码保护 |
| 压力测试 | 并发 MCP 调用、SQL 执行性能 |

## 18.3 重点测试项

- Oracle 11g 连接与执行
- MySQL 5.6 连接与执行
- SQL 文件执行正确性
- 多语句处理正确性
- 风险识别准确性
- 密码解密权限控制
- MCP 调用日志完整性
- 权限隔离有效性
- SQL 文件路径穿越防护

---

# 19. 迭代分期规划

## 19.1 分期边界

| 维度 | 一期 | 二期 |
|---|---|---|
| 核心目标 | Database Skill 落地闭环 | Skill 扩展 + 能力增强 |
| Skill 数量 | 1（database） | 3-5（+ config / file / log） |
| 模块数量 | 7 | 按需拆分至 10-13 |
| Web 页面 | 9 个核心页面（含 Skill 管理、服务器管理、个人设置、MCP 接入指南） | 补全至 10 个 |
| 风险引擎 | sqlparse + 正则 + 关键词 | 配置化规则引擎 |
| 数据库方言 | Oracle + MySQL 基础支持 | DatabaseDialect 方言抽象层 |
| Skill 注册 | 装饰器静态注册 | 动态模块加载（热插拔） |
| 连接管理 | 按需连接 | 轻量连接池 |
| 限流 | asyncio.Semaphore 基础并发控制 | 熔断器 |

## 19.2 一期实施阶段

### 阶段零：技术兼容验证

- Python 3.11.9 + FastAPI 空项目验证
- oracledb 2.4.1 thick 模式 + run_in_executor + Oracle 11g 连接与执行验证（已完成，6/6 通过）
- aiomysql + MySQL 5.6 连接与执行验证（已完成，14/14 通过）
- SQLAlchemy AsyncSession + asyncpg + PostgreSQL 验证
- Claude Code + MCP Python SDK stdio 模式最小化 PoC

### 阶段一：基础框架与系统库

- 后端工程骨架（8 顶级包结构）
- 系统库表结构初始化（Alembic）
- 用户、角色、权限基础模型
- 数据源配置模型
- **审计日志基础设施**（AuditLogger 接口 + pmcp_audit_log 写入能力）
- 通用响应、异常、trace_id 机制
- 配置管理（pydantic-settings）

### 阶段二：MCP Core 与 Skill Registry

- MCP Server 入口搭建（mcp_server.py）
- Tool 参数解析
- Skill 接口定义与固化（Protocol）
- Skill 注册与路由（装饰器 + dict 映射）
- MCP 调用日志
- 统一返回结构
- 基础并发限流

### 阶段三：Database Skill 闭环

- list_datasources
- execute_sql_text
- execute_sql_file（含路径安全校验）
- validate_sql（sqlparse + 正则风险识别）
- 高风险操作二次确认机制
- 基础事务控制
- Oracle / MySQL 基础执行支持
- 生产库受保护标记

### 阶段四：Web 管理端

- 登录页（双栏布局：左侧项目视觉区 + 右侧登录表单，角色由用户名自动映射）
- Skill 管理页（Skill 列表、使用方式、启停操作、审核操作、新增入口）
- 数据源管理页
- 密码加密页
- 审计日志页
- 用户管理页
- 个人设置页（显示名称、邮件地址、修改密码，通过头像下拉菜单进入）
- MCP 接入指南页（Claude Code 配置步骤、JSON 配置示例、已注册 Skill/Tool 列表、环境要求、FAQ）

### 阶段五：测试与上线

- Oracle 11g 兼容测试
- MySQL 5.6 兼容测试
- 权限隔离测试
- 审计完整性测试
- SQL 文件执行边界测试
- 部署启停与日志检查

## 19.3 一期验收标准

### 功能验收

- Claude Code 可通过 MCP 调用 Database Skill
- 可执行 SQL 文本和受控范围内的本地 `.sql` 文件
- 可查询可用数据源
- 可查看审计日志
- 可配置数据源及密文密码
- 可按用户/角色/数据源/环境控制访问
- 高风险操作（DELETE 无 WHERE、DROP、TRUNCATE、生产库 DDL、存储过程调用等）触发二次确认

### 兼容性验收

- Oracle 11g 基础连接和 SQL 执行通过
- MySQL 5.6 基础连接和 SQL 执行通过
- PostgreSQL 系统库访问稳定
- 目标数据库连接失败时不影响系统库和管理端
- 驱动版本与 Python 版本形成最终固化清单

### 安全与审计验收

- 目标数据库密码不明文入库
- secret 文件不写入代码
- 解密操作受权限控制
- SQL 执行全链路可追踪
- MCP 调用、配置变更、权限变更均有审计记录

### 运维验收

- 支持 systemd 启停
- 支持 Nginx 反向代理
- 日志按目录输出
- 配置文件与 secret 文件分离
- 服务异常可通过日志定位

## 19.4 二期规划方向

### Skill 扩展

按优先级逐步扩展：`config`（低风险，验证框架扩展性）→ `file` → `log` → `deploy`（高风险，独立安全评审）→ `shell`（高风险，独立安全评审）

### 架构增强

| 增强项 | 说明 |
|---|---|
| DatabaseDialect 方言抽象 | 每个目标数据库一个 Dialect 实现，新增数据库支持只需实现新 Dialect |
| Skill 热插拔机制 | Skill 作为独立 Python 模块放入指定目录后自动注册，支持动态加载与卸载 |
| Capability 抽象层 | 执行器、风险识别、审计等公共服务可跨 Skill 复用 |
| 分层上下文 | 基础上下文（所有 Skill 共享）+ Skill 专用上下文（扩展字段） |
| 配置化规则引擎 | 风险规则按数据库类型配置，新增规则不改代码 |
| 轻量连接池 | 高频调用数据源启用独立连接池实例 |
| 熔断器 | 按数据源的熔断机制，连续失败自动熔断 |
| 流式响应 | MCP SSE 流式返回执行进度 |
| 多环境隔离增强 | 操作审批流、IP 白名单校验、操作窗口控制 |

### Web 页面补全

补全系统概览页、角色权限管理页、MCP 调用状态页、系统配置页。

### 数据库能力增强

- Oracle 存储过程高级支持（OUT 参数、REF CURSOR 已在一期 POC 验证通过，二期进一步封装与优化）
- MySQL 多语句执行增强（nextset 已在一期 POC 验证通过，二期优化多结果集映射）
- SQL 执行计划辅助查看
- 高危 SQL 二次确认或审批机制

---

# 20. 开源协议与合规说明

## 20.1 后端依赖协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| Python | 3.11.9 | PSF License | 可商业使用 |
| FastAPI | 0.115.0 | MIT License | 无传染性 |
| Uvicorn | 0.30.6 | BSD 3-Clause License | 无传染性 |
| Gunicorn | 23.0.0 | MIT License | 无传染性 |
| Pydantic | 2.8.2 | MIT License | 无传染性 |
| pydantic-settings | 2.4.0 | MIT License | 无传染性 |
| SQLAlchemy | 2.0.35 | MIT License | 无传染性 |
| Alembic | 1.13.2 | MIT License | 无传染性 |
| asyncpg | 0.30.0 | Apache License 2.0 | 无传染性 |
| oracledb | 2.4.1 | Apache License 2.0 / Oracle Free Use Terms and Conditions | 需确认 Oracle 驱动使用条款 |
| aiomysql | 0.2.0 | MIT License | 无传染性 |
| cryptography | 43.0.1 | Apache License 2.0 | 无传染性 |
| passlib | 1.7.4 | BSD License | 无传染性 |
| loguru | 0.7.2 | MIT License | 无传染性 |
| httpx | 0.27.2 | BSD License | 无传染性 |
| tenacity | 9.0.0 | Apache License 2.0 | 无传染性 |
| PyYAML | 6.0.2 | MIT License | 无传染性 |
| python-multipart | 0.0.9 | MIT License | 无传染性 |
| mcp | 1.9.4 | MIT License | 无传染性 |
| uv | 0.4.13 | MIT License / Apache License 2.0 | 无传染性 |
| pip | 24.2 | MIT License | 无传染性 |

## 20.2 前端依赖协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| Vue | 3.5.34 | MIT License | 无传染性 |
| Vite | 8.0.12 | MIT License | 无传染性 |
| TypeScript | 6.0.2 | Apache License 2.0 | 无传染性 |
| Vue Router | 4.4.3 | MIT License | 无传染性 |
| Pinia | 2.2.2 | MIT License | 无传染性 |
| Element Plus | 2.8.1 | MIT License | 无传染性 |
| Axios | 1.7.4 | MIT License | 无传染性 |
| ECharts | 5.5.1 | Apache License 2.0 | 无传染性 |
| ESLint | 9.9.1 | MIT License | 无传染性 |
| Prettier | 3.3.3 | MIT License | 无传染性 |

## 20.3 数据库与中间件协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| PostgreSQL | 16.4 | PostgreSQL License | 类 BSD 协议，无传染性 |
| Nginx | 1.26.1 | BSD 2-Clause License | 无传染性 |

## 20.4 测试工具协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| pytest | 8.3.2 | MIT License | 无传染性 |
| pytest-asyncio | 0.23.8 | Apache License 2.0 | 无传染性 |
| pytest-cov | 5.0.0 | MIT License | 无传染性 |
| Faker | 28.4.1 | MIT License | 无传染性 |
| Apache JMeter | 5.6.3 | Apache License 2.0 | 无传染性 |

## 20.5 运行环境协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| Node.js | 22.22.3 | MIT License (OpenJS Foundation) | 无传染性 |
| npm | 10.7.0 | Artistic License 2.0 | 可商业使用 |

## 20.6 重点合规关注

| 风险项 | 说明 | 建议 |
|---|---|---|
| oracledb 2.4.1 | Oracle Free Use Terms and Conditions 或 Apache License 2.0 | 已确认需使用 thick 模式，需引入 Oracle Instant Client。确认 Oracle Instant Client 许可证允许内部使用场景 |
| aiomysql | MIT License | 内部使用无合规风险 |

---

# 21. 非功能性要求

| 维度 | 要求 |
|---|---|
| 可用性 | 服务支持稳定持续运行，异常请求不影响整体服务可用性 |
| 可维护性 | 模块职责清晰，日志可定位，配置可管理，错误信息可追踪 |
| 安全性 | 密码密文存储，解密操作受控，权限最小化，全链路审计 |
| 可扩展性 | MCP 统一入口不绑定单一数据库能力，Skill 可逐步扩展，接口和日志结构可复用 |

---

# 22. 配置系统与共享基础设施（Configuration System & Shared Infrastructure）

## 22.1 配置系统设计

`config.py` 使用 `pydantic-settings` 加载 YAML 配置。关键机制：YAML `app:` 嵌套在 `config.py` 第 99-100 行被扁平化到顶层（`raw.update(raw.pop("app"))`），因此使用 `settings.name` 而非 `settings.app.name`。

### MCP 相关配置（`config.py` McpSettings 类，L73-79）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `operator_role` | `"admin"` | stdio 模式下 API Key 未设置时的回退身份 |
| `transport` | `"stdio"` | MCP 传输模式：`stdio` 或 `streamable-http` |
| `http_host` | `"127.0.0.1"` | HTTP 模式绑定地址 |
| `http_port` | `9000` | HTTP 模式绑定端口 |
| `http_path` | `"/mcp"` | HTTP 模式路径前缀 |

### Crypto Key 加载

加密密钥加载集中化在 `datasource/manager.py:_get_crypto_utils()`，所有需要 `CryptoUtils` 的代码必须调用此函数，**不得直接实例化 `CryptoUtils()`**（它需要 `key: bytes` 参数）。

## 22.2 共享基础设施（Shared Infrastructure）

| 模块 | 职责 | 关键设计 |
|------|------|----------|
| `common/database.py` | 全局引擎单例（`_ensure_engine()`） | 所有 ORM 访问通过 `get_db()` async generator（FastAPI `Depends`） |
| `common/response.py` | 统一响应格式 | `ResponseBase[T]`（5 字段：code/message/data/trace_id/timestamp）、`PageResult[T]`（分页） |
| `common/exceptions.py` | 异常层次 | `BusinessError`、`AuthError(11001)`、`DataSourceError(12001)`、`SkillError(10001)`、`PathSecurityError(16001)` |
| `datasource/manager.py` | 数据源连接参数桥接 | `ConnectionParams` dataclass，`_get_crypto_utils()` 读取密钥 |
| `audit/logger.py` | 审计日志写入 | `write_audit_log(...)` 异步函数，直接 commit 到 `pmcp_audit_log` |

### BaseModel 公共字段

所有 ORM 模型继承 `BaseModel`，自动获得：`id`、`inserted_at`、`updated_at`、`inserted_by`、`updated_by` 字段。

## 22.3 Skill System Design

Skills 实现一个 `typing.Protocol` 接口，包含方法：`skill_name()`、`list_tools()`、`validate()`、`execute()`、`support()`。注册通过 `@register_skill("name")` 装饰器完成。

**注意**：`@register_skill` 只把 Skill 类加入 `_pending_skills` 队列（`mcp_server/skill/decorator.py`），**不主动注册到 registry**。实际注册发生在 MCP Server 启动时 `_register_skills()` 消费队列。

Registry（`mcp_server/skill/registry.py`）维护 `dict[skill_name → Skill]` + `dict[tool_name → Skill]`，按 tool_name prefix 路由。

当前已注册 2 个 Skill：
- `database`（一期）：`DatabaseSkill` — 5 tools（execute_sql_text/file、validate_sql、list_datasources、get_execution_status）
- `server`（一期后增补，2026-08-07）：`ServerSkill` — 6 tools（execute_command、upload_file、download_file、list_servers、validate_command、get_server_execution_status）— Linux SSH/SFTP，详见 §8.2 备注

共用层 `platform_mcp/skills/common/`（2026-08-07 抽离）：`risk_types.py` 提供 `RiskLevel` / `RiskResult` / `_LEVEL_ORDER`；`permission.py` 提供 `check_env_permission`。database 与 server skill 均从此导入。

### Web 进程的 Registry 陷阱

FastAPI web 进程不启动 MCP server，因此 `_pending_skills` 永远不会被消费，`registry.get_skill()` 返回 `None`。若 web 层（如 `api/guide.py`）需要 Skill 实例获取 `list_tools()`，应直接 `from platform_mcp.skills.database import DatabaseSkill; DatabaseSkill().list_tools()`，**不要依赖 registry**。

### Skill 注册方式

一期仅支持 decorator-based 静态注册（`@register_skill`）。页面表单提交、源码上传自动解析为二期功能（开发计划 L497，`api/skills.py:create_skill` 当前返回 501，前端 `SkillPage.vue:94` 置灰按钮 title="二期功能"）。

## 22.4 MCP 接入指南 API

`GET /guide/config` 返回双套配置（dev stdio + prod streamable-http），含统一 `PLATFORM_MCP_API_KEY` 凭证位（`<your-api-key>` 占位）。

`GET /guide/tools` 按 skill 分组返回：`[{skill_code, skill_name, description, register_method, tool_count, tools: [...]}]`。Web 进程用工厂函数 `_get_skill_instance(skill_code)` 直接实例化（绕开 registry pending 队列问题）。

---

# 23. 技术结论

Platform-MCP 首期正式技术路线：

| 维度 | 选型 |
|---|---|
| 后端 | Python 3.11.9 + FastAPI 0.115.0 |
| 运行时 | Gunicorn 23.0.0 + Uvicorn 0.30.6 |
| 前端 | Vue 3.5.34 + Vite 8.0.12 + Element Plus 2.8.1 + TypeScript 6.0.2 |
| 系统库 | PostgreSQL 16.4（asyncpg） |
| 目标数据库连接 | oracledb 2.4.1 thick 模式 + run_in_executor（Oracle 11g）+ aiomysql（MySQL 5.6） |
| 部署方式 | 虚拟环境 + systemd + Nginx |
| 扩展模式 | MCP 统一入口 + Skill 插件式扩展 |
| 架构形态 | 双入口（FastAPI Web + MCP Server stdio） |

**启动前必须完成项：**

1. ~~Oracle 11g + oracledb 2.4.1 async thin 模式全量验证~~ **已完成** — thin 模式不支持 11g（DPY-3010），已切换至 thick 模式 + run_in_executor，6/6 项通过
2. ~~MySQL 5.6 + aiomysql 兼容性验证~~ **已完成** — 14/14 子项全部通过
3. Claude Code + MCP Python SDK stdio 模式最小化 PoC
4. 统一异步策略验证（asyncpg + aiomysql + oracledb thick + run_in_executor）

**部署新增要求：** Oracle 目标库所在服务器需预装 Oracle Instant Client 64-bit。

---
