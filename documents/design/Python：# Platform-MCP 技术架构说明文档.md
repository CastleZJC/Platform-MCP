# Platform-MCP 技术架构说明文档

- **适用对象**：架构师、后端开发、前端开发、运维工程师、测试工程师
- **文档用途**：用于项目启动阶段的 IT 内部宣讲、技术评审、系统设计与实施基线对齐

---

## 版本更新日志

| 版本 | 日期 | 修订性质 | 修订摘要 | 修改人 |
|---|---|---|---|---|
| V1.0 | 2026-08-08 | 正式发布 | 一期 + Server Skill 二期专项全量上线 | castle |
| V2.1 补记 | 2026-08-31 | 欠账补齐 | 补记 2026-08-13 已交付的 V2.1（Skill 源码上传/14 条合规审计/README 自动生成/两类分组管理/系统配置 API/前端 12 页），修正表清单 15→17、角色口径、501 陈旧口径，并记录 3 条实测勘误 | castle |
| V3.0 | 2026-08-31 | 大版本设计 | 二期大版本总体设计：双 AI 通道（glm 5.3 外部 + BGE-M3/Qwen3 本地栈）、多语种 i18n、Skill 广场与 8 状态生命周期、统一组模型、一般用户第三角色、邮件组提醒、运行时配置中心、MCP 工具 11→22（定稿规划；最终落地 31，见 §8.2.1）按角色过滤、三期 KB 骨架（§19.5/§19.6） | castle |

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

### 4.2.2 MCP Server 入口（mcp_server/ 包，入口 __init__.py）

- 使用官方 `mcp` Python SDK，支持双传输模式：
  - **stdio 模式**（dev 默认）：由 Claude Code 作为子进程启动和管理
  - **streamable-http 模式**（prod 推荐）：作为独立 systemd 进程运行，通过 HTTP/SSE 远程调用
- 模式由 `settings.yml` 的 `mcp.transport` 字段控制
- 负责：MCP Tool 接入、Skill 路由、Tool 执行

### 4.2.3 共享业务逻辑层（skills/ + audit/ + common/）

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
| py7zr | 0.22.0 | 7z 解压（V2.1 Skill 源码包上传，2026-08-13 已引入） |
| fastembed | 待锁定（V3.0 规划） | BGE-M3 ONNX int8 纯 CPU 向量化（Skill 广场语义搜索/相似度比对），无 torch 依赖 |
| llama-cpp-python | 待锁定（V3.0 规划） | Qwen3-4B/1.7B GGUF 纯 CPU 本地生成（Web 端双语 README/审核报告/diff 描述） |
| aiosmtplib | 待锁定（V3.0 规划） | 异步 SMTP 客户端（V3.0 邮件组提醒，outbox 模式） |

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
| vue-i18n | 9.14.x（V3.0 规划，精确版本实施时锁定） | 多语种（中/英，可扩展），lazy JSON 语言包 |
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

> **计数口径**（2026-08-31 实测）：顶级 Python 包 9 个（`platform_mcp/{api, auth, datasource, server, group, mcp_server, skills, audit, common}`；`skills/` 含 database/server/common 3 子包 + V2.1 audit/readme/upload 模块；`group/` 为 V2.1 新增）；API 路由模块 12 个（`api/*.py` 目录实测）；MCP 工具 11 个（database 5 + server 6），V3.0 规划扩至约 26。

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

### 8.2.1 二期功能清单（V2.1 已实现 + V3.0 规划，2026-08-31 与代码实测对齐）

**V2.1（2026-08-13，commit bd178b6）已实现：**

| # | 功能 | 实现状态 |
|---|---|---|
| 1 | Skill 源码上传注册 | ✅ `api/skills.py:POST /skills/upload`（.7z/.zip ≤50MB，py7zr）→ 解压 → SKILL.md frontmatter 解析 → 14 条合规审计（`skills/audit/engine.py`，🔴阻止/🟡警告/🟢建议）→ README 模板自动生成（`skills/readme/generator.py`）→ 写 `pmcp_skill`（status=2 待审核）+ `pmcp_skill_audit_report` 每规则存底。**内容脱敏环节已于 2026-09-07 移除**（用户裁决：企业内部 skill 含公司/项目名为正常注册场景，平台不做内容脱敏，脱敏仅存在于仓库提交环节；`sanitizer.py` 删除，上传/MCP 草稿/审核重放/产物回传四链路同步去除） |
| 2 | Skill 审核流 | ✅ `POST /skills/{id}/review`（admin approve→ENABLED / reject→REJECTED），审计报告审核时展示、归档不可删 |
| 3 | 分组管理 | ✅ 数据源组 + 服务器组两类（5 张表：`pmcp_datasource_group` / `pmcp_server_group` / 2 张 group_member / `pmcp_user_group`），admin CRUD+分配、dev 只读；Web 层列表已按组过滤（⚠️ MCP 层过滤缺口见 §19.4 勘误 1，V3.0 M0 整改）。**历史口径**：本行 5 张分组表已随 migration 005/008 统一为 `pmcp_group` + 3 成员表并 DROP，本行为 V2.1 交付时存档 |
| 4 | 系统配置管理 API | ✅ `/system-configs` CRUD（`pmcp_system_config`，admin 专用），前端 SystemConfigPage 已交付（菜单项暂隐藏，见勘误 4） |
| 5 | 废弃表清理 | ✅ migration 002 DROP `pmcp_permission` / `pmcp_role_permission` / `pmcp_datasource_permission` / `pmcp_server_permission` 4 张空表 |

**V3.0（二期大版本，2026-08-31 规划）—— 详见 §19.5：**

| # | 功能 | 要点 |
|---|---|---|
| 1 | 双 AI 通道 | CC+MCP 走外部大模型 glm 5.3；Web 走本地模型栈（BGE-M3 检索 + Qwen3-4B 生成） |
| 2 | 多语种 i18n | 中/英切换（默认中文），系统标签/Skill README/审核报告/Tool 描述；个人设置即时生效不重启服务（`sys.default_locale` 仅影响未设置偏好的用户） |
| 3 | Skill 广场 + 黑名单 | 公共池审核制、语义搜索、添加至我的、用户屏蔽；功能广场一级导航 |
| 4 | Skill 生命周期 | 8 状态状态机 + 版本化双语存档 + MCP 双通道创建/更新 + 分享迭代 |
| 5 | 统一组模型 | 合并两类组为 `pmcp_group`（组员+数据源+服务器多对多） |
| 6 | 一般用户角色 | 第三角色：无 database/server 权限，有 Skill 创建/分享/广场权限 |
| 7 | 邮件组提醒 ×4 | 生产 HIGH+ 数据库操作 / 生产 HIGH+ 服务器操作 / Skill 审核（含结果全量通知提交人）/ 用户管理安全事件（API Key 变更+账号权限安全，同步告知相关用户及 admin 组），仅 admin 入组，outbox 模式（✅ M5 已落地 2026-09-05，§19.5.5） |
| 8 | 运行时配置中心 | 系统配置页管理非重启生效项（默认语言/会话失效时间/超时/并发/文件上限/白名单等，见 §19.5.2 参数盘点），重登录或即时生效 |
| 9 | MCP 工具扩展 | 11→31 工具（Skill 生态/双通道 16 + 审核/审计/个人设置 4，M3/M4 已落地），registry ToolMeta 增 roles 按角色动态过滤；MCP/Web 双端能力边界见 §19.5.7 |
| 10 | 三期 KB 骨架 | 知识库表结构 + 空模块 + RAG/GRAPH 抽象 + 7 切片枚举（✅ M6 已落地 2026-09-05，§19.6） |

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

### 角色定义（V1.0 双角色 → V3.0 三角色）

V1.0 预置两个角色；V3.0 新增第三个角色"一般用户"（role_code=`user`，migration 005 seed），完整权限矩阵见 §19.5.4：

| 角色 | 标识 | 说明 |
|---|---|---|
| 系统管理员 | admin | 全页面、全操作权限；邮件提醒组唯一可入组角色 |
| 开发人员 | developer | 受限权限，详见下表；仅可访问所属组的数据源/服务器（V3.0 统一组模型） |
| 一般用户 | user（V3.0 新增） | 无 database/server 权限（相关页面与 10 个执行类 MCP 工具均不可见）；拥有 Skill 创建/分享、Skill 广场、Skill 黑名单权限 |

#### developer 角色权限范围

| 功能域 | developer 权限 |
|---|---|
| Skill 管理 | 可上传/创建 Skill（草稿/审核中仅本人可见），可更新自己的 Skill；广场审核操作仅 admin |
| 数据源管理 | 仅查看所属组 + 测试连接，不可新增/修改/禁用数据源（V3.0 复核：仅"测试"按钮可见） |
| 服务器管理 | 同数据源管理（仅"测试"按钮可见） |
| 审计日志 | 仅可查看自己的操作记录 |
| 密码加密页 / 用户管理页 / 分组管理页 | 页面不可见 |
| MCP 接入指南 / 功能广场 | 可见 |

#### user（一般用户）角色权限范围（V3.0）

| 功能域 | user 权限 |
|---|---|
| 功能广场（Skill 广场/黑名单） | 可见；涉数据库/涉服务器的 Skill 对其不可见（Web 与 MCP 双端） |
| Skill 创建/分享 | 可经 Web 上传或 MCP 创建；可提交审核分享入广场 |
| 数据源/服务器管理 | 页面与 MCP 工具均不可见 |
| 审计日志 | 仅可查看自己的操作记录 |

#### Skill 审核流程

1. 用户通过 Web 上传或 MCP 创建 Skill → 个人库（未提交审核仅本人可见，含 admin 不可见）
2. 提交分享 → 状态"审核中"（本人 + admin 可见），邮件通知 Skill 审核组
3. admin 审核后可"新增入广场"（含合并到已有广场 Skill，需填迭代说明）或"拒绝"（需填原因并邮件告知）
4. 仅 admin 可执行广场审核操作；审核结论仅影响广场，不影响用户自用

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
- Skill 创建/更新/分享/审核/黑名单（V3.0 扩展，resource_type 归属 Skill 管理，操作明细可区分）
- 分组调整（组 CRUD + 数据源/服务器/组员分配，V3.0 扩展）
- 邮件提醒组变更与通知发送留痕（V3.0 扩展，outbox 可审计）

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
| MCP 接入指南页 | P1 | Claude Code 配置步骤、JSON 配置示例（stdio 模式）、已注册 Skill/Tool 列表、环境要求、FAQ；所有用户可见。已注册 Skill/Tool 列表经 `pmcp_skill` 动态驱动（2026-09-07 起：Web 启动时 `skills/bootstrap.py` 按 registry 内置清单 `BUILTIN_SKILL_CODES` 自动同步装饰器注册的 Skill 落库——插入 status=ENABLED/register_method=decorator/tool_count 实测，已有行仅刷新 tool_count 不覆盖停用状态与用户编辑；功能描述按登录用户 locale 经 `skill.desc.*` 双语字典取值）；使用建议场景/提示为静态页面文案，走前端 i18n（zh/en），不经后端下发 |

### 侧边栏分组

侧边栏按以下分组组织，根据登录角色动态显隐（V2.1 后系统管理扩至 4 页，V3.0 新增功能广场分组）：

| 分组 | 包含页面 | 可见角色 |
|---|---|---|
| 管理中心 | Skill 管理、数据源管理、服务器管理、审计日志 | admin + developer |
| 功能广场（V3.0） | Skill 广场、Skill 黑名单（双二级页签） | admin + developer + 一般用户 |
| 系统管理 | 密码加密、用户管理、分组管理（V2.1 交付，菜单项暂隐藏→V3.0 M0 启用）、系统配置（V2.1 交付，菜单项暂隐藏→V3.0 M1 启用并升级运行时配置中心）、邮件提醒（V3.0） | 仅 admin |
| 帮助 | MCP 接入指南 | 全部角色 |

> 一般用户（V3.0 第三角色）仅可见"功能广场 + 帮助"两个分组。

### 一期延后至二期（4 个页面）的处置（2026-08-31 更新）

| 页面 | 处置 |
|---|---|
| 系统概览页 | 仍延后 |
| 角色权限管理页 | 不再需要独立页——角色仍为预置角色（三角色），权限随角色硬编码 |
| MCP 调用状态页 | 仍由审计日志页替代 |
| 系统配置页 | ✅ V2.1 已交付（SystemConfigPage）；✅ V3.0 M1 已升级为运行时配置中心并启用菜单项（注册表驱动：已知键 13 项生效语义/凭证值掩码/可选值下拉/自定义键合并，§19.5.2，勘误 4 关闭） |

> 前端页面实测 **11 个**（`router/index.ts` 路由实测：login / skills / datasources / servers / audit / crypto / users / groups / system-config / profile / mcp-guide；V2.1 的"Skill 上传页"按计划合并入 SkillPage 未单列）。V3.0 新增功能广场（Skill 广场 + Skill 黑名单）与邮件提醒页后预计 **14 个**。

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

> 2026-09-07 实测更新（head=012）：migration 002 DROP 4 张废弃权限表；003 新增 V2.1 分组 5 表 + `pmcp_skill_audit_report` + `pmcp_skill` 扩展；005（V3.0 M0）：统一组 4 表落地并 DROP 旧分组 5 表 + `pmcp_user.locale` 列 + role seed `user` + `pmcp_skill.status` 转 varchar 状态机；006（M2）：plaza/version/blacklist 三表；007（M3）：plaza embedding 列；008（M3R 后）：`pmcp_group` DROP env_code（组与环境正交，同名组已合并，UNIQUE(group_name)）；009（M5）：notify 三表 + `pmcp_user` 锁定字段；010（M6）：kb 骨架五表（三期）；011（2026-09-07）：notify param_descriptions 双重编码数据修复；012（2026-09-07）：`pmcp_user.page_size` 个人每页条数列（存量回填 20）。grep `__tablename__` 实测 **27 张**（16 + M2 三表 + M5 三表 + M6 五表）：

- `pmcp_user` — 用户信息（✅ 005 已加 `locale` 界面语言列；✅ 009 已加 `failed_attempts`/`locked_until` 连续登录失败锁定字段，5 次锁 15 分钟；✅ 012 已加 `page_size` 个人每页条数列〔5/10/20/50/75/100，存量回填 20，创建时经 sys.default_page_size seed〕）
- `pmcp_role` — 角色信息（✅ 005 已 seed 第三角色 `user` 一般用户，三角色生效）
- `pmcp_user_role` — 用户角色关系
- `pmcp_api_key` — API Key 双存储（key_hash SHA-256 校验 + key_encrypted AES-GCM admin reveal）
- `pmcp_datasource` — 数据源配置
- `pmcp_server` — 服务器配置（Linux SSH/SFTP 目标，含 encrypted_password + encrypted_ssh_key + allowed_paths）
- `pmcp_audit_log` — 审计日志
- `pmcp_mcp_call_log` — MCP 调用日志
- `pmcp_crypto_operation_log` — 加解密操作日志
- `pmcp_system_config` — 系统参数配置（✅ V2.1 已启用 CRUD API；✅ V3.0 M1 运行时配置中心已落地：已知键注册表 12 键 + 30s 快照缓存 + 登录/会话读取点改造 §19.5.2）
- `pmcp_skill` — Skill 注册信息（V2.1 扩展：source_path / source_checksum / source_format / version / audit_status / audit_result JSONB / readme_generated；✅ 005 status 已转 varchar 状态机；✅ 006 已加 plaza_id / origin / share_status / review_comment）
- `pmcp_skill_audit_report` — Skill 合规审计报告存底（V2.1 新增，每规则一行，归档不可删）
- `pmcp_group` — ✅ 统一组（005 新增；008 组去环境维度后 UNIQUE(group_name)，组与环境正交；组员+数据源+服务器多对多，§19.5.4）
- `pmcp_group_user` / `pmcp_group_datasource` / `pmcp_group_server` — ✅ 统一组三张成员表（005 新增，FK CASCADE，UNIQUE(group_id, 资源id)）
- `pmcp_skill_plaza` / `pmcp_skill_version` / `pmcp_skill_blacklist` — ✅ V3.0 M2（006）：广场公共池（007 加 embedding）/ 版本化双语存档（UNIQUE(skill_id,version) 不可篡改）/ 用户黑名单
- `pmcp_notify_group` / `pmcp_notify_group_member` / `pmcp_notify_outbox` — ✅ V3.0 M5（009）：邮件提醒事项组（notify_type ×4 + 参数化模板 + enabled 独立启停，seed 四组默认模板）/ 组成员（仅 admin 可入组）/ 发件箱（pending/sent/failed + retry_count，失败可重试全程可审计，§19.5.5）
- `pmcp_kb` / `pmcp_kb_doc` / `pmcp_kb_chunk` / `pmcp_kb_version` / `pmcp_kb_share` — ✅ V3.0 M6（010）：三期 KB 骨架——主体（personal/shared + owner + status 复用 review 状态机）/ 文档 / 切片（7 策略枚举 + embedding JSONB）/ 版本存档（双语同 Skill 惯例，UNIQUE(kb_id,version)）/ 分享审核关联（§19.6，业务三期实现）
- （已 DROP：`pmcp_datasource_group` / `pmcp_server_group` / 2 张 group_member / `pmcp_user_group`，存量按"同 env 同名合并"回填入统一组）

**V3.0 迁移链**：✅ 005（统一组，M0）→ ✅ 006（plaza/version/blacklist + pmcp_skill 加列，M2）→ ✅ 007（plaza embedding JSONB + 条件 pgvector，M3）→ ✅ 008（pmcp_group DROP env_code 组与环境正交，M3R 后插入——编号占用了原拆分口径的 notify 位）→ ✅ 009（notify 三表 + pmcp_user 锁定字段 + 四组 seed，M5）→ ✅ 010（kb 骨架五表，M6，F-42 终核完成）→ ✅ 011（notify param_descriptions 双重编码数据修复，2026-09-07）→ ✅ 012（pmcp_user.page_size 个人每页条数 + 存量回填 20，head=012）。V1.0 alembic 单一发布修订：`alembic/versions/001_initial_tables.py`（合并历史 10 个迭代 ba0102b846dd → ch0101a947f6 的最终态）。

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

> **完整 11 工具清单**：database skill 5 tools 见下表；server skill 6 tools（execute_command / upload_file / download_file / list_servers / validate_command / get_server_execution_status）详见 §8.3.1。V3.0 已扩展至 **31 工具**（M3/M4 落地：Skill 生态/双通道 16 + 审核/审计/个人设置 4，按角色动态过滤，MCP/Web 双端边界见 §19.5.7）。

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
| SQL 执行错误 | 13001-13999 | 语法错误、执行失败、超时（**漂移注记**：实际 13001-13003 已被 servers CRUD〔api/servers.py:151-182〕、13001-13007 已被邮件通知〔api/notify.py〕占用；新增模块应避开 13001-13007 区间） |
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

- MCP Server 入口搭建（mcp_server/ 包）
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

## 19.4 V2.1 交付记录与勘误（2026-08-31 实测对齐）

### V2.1 已交付（2026-08-13，commit bd178b6）

Skill 源码上传注册 + 14 条合规审计引擎 + README 自动生成 + 分组管理（两类组）+ 系统配置 API + 废弃表清理 + 前端 SkillPage 重写/GroupPage/SystemConfigPage，明细见 §8.2.1。

### 勘误（2026-08-31 实测发现，V3.0 整改）

| # | 勘误 | 实测证据 | 整改归属 |
|---|---|---|---|
| 1 | **MCP 层组过滤缺口**：组过滤仅在 Web 层实现；MCP 工具 `list_datasources` 未按用户所属组过滤（V2.1 计划任务 2.6 / 验收 F-16 声称完成，实为半成品） | `skills/database/__init__.py:589` 调 `list_accessible_datasources(env_code)` 无用户参数；过滤逻辑仅在 `api/datasources.py:118`、`api/servers.py:108`（Web API 层） | V3.0 M0：组过滤下沉至 `datasource/server/manager.py`（`list_*` 增 user_id 参数），双入口复用 |
| 2 | 表清单口径过时：文档原记 15 张且引用已 DROP 表 | grep `__tablename__` 实测 **17 张**（§14.1 已更正） | 本版已更正 |
| 3 | 开发计划 R-06（无组用户"渐进继承原环境可见"）与 §3.7（无组返回空列表）自相矛盾 | 两处口径冲突 | **裁决：采用 §3.7 语义（无组 dev → 空列表）**——"渐进继承"属权限旁路，与组过滤下沉后的代码行为冲突；现网用户量小，admin 一次性配组即可。计划文档已按裁决改写 |
| 4 | **分组管理/系统配置侧边栏菜单项被注释隐藏**：页面组件与 adminOnly 路由均已交付，但 `MainLayout.vue:29-30` 菜单项注释为"二期功能，暂隐藏"——导航闭环未打通（仅可直接 URL 访问） | `MainLayout.vue:16-37` menuGroups | V2.1 收尾项：随 V3.0 M0（分组管理改统一组口径）与 M1（系统配置升级运行时配置中心）启用菜单项 |
| 5 | **内置 Skill 启停为装饰性操作**：SkillPage 启停/审核仅写 `pmcp_skill.status`，MCP 注册与路由（registry/`_register_skills`）不读取该状态——启停对 MCP 层零效果 | grep `PmcpSkill` 消费点仅 `skills/upload.py`（写入），`mcp_server/` 无读取 | V3.0 M2 整改：registry 启动与路由按 `pmcp_skill.status` 过滤内置 Skill；上传 Skill 动态加载同步消费状态机（§19.5.3） |

### 原"二期规划方向"清单处置（2026-08-31）

| 原规划项 | 处置 |
|---|---|
| Skill 扩展（config/file/log/deploy/shell 内置包） | 取消——V3.0 转向"用户 Skill 广场生态"（§19.5.3），平台内置 Skill 维持 database + server 两个 |
| Skill 热插拔（Python 模块动态加载） | 由 V3.0"动态加载暴露"方案替代——Skill 为文档型资产经 MCP 暴露给 CC，平台不执行任意 Python（安全立场与审计引擎一致） |
| Web 页面补全 | 系统配置页 V2.1 已交付（菜单项暂隐藏）；角色权限管理页不再需要（预置三角色）；概览/调用状态页仍延后 |
| DatabaseDialect 方言抽象 / 配置化规则引擎 / 轻量连接池 / 熔断器 / 流式响应 / 多环境审批流 | 保留为远期架构增强方向，不占 V3.0 里程碑 |
| 数据库能力增强（存储过程封装/多结果集/执行计划） | 保留为远期方向（多语句 DDL/PLSQL 块已于一期后增补落地） |

---

## 19.5 V3.0 二期大版本设计（2026-08-31 立项）

V3.0 目标：**完成二期大版本功能 + 搭建三期框架**。三条工作线并行——功能线（广场/分组/邮件/页面）、Skill 线（生命周期/双通道/版本化/动态加载）、模型线（glm 5.3 外部 + BGE-M3/Qwen3 本地栈）。

### 19.5.1 双 AI 通道

| 通道 | 模型 | 职责 | 边界 |
|---|---|---|---|
| CC + MCP | **glm 5.3**（外部大模型，CC 侧配置） | Skill 创建前广场相似推荐、中英双语审核报告与 README 生成、Skill 版本差异描述、分享迭代差异提示 | 平台**不内置外网 LLM 客户端**（安全立场不变）；生成产物经 MCP 工具回传，平台侧重放确定性校验（14 条审计规则 + 脱敏器）后按版本存档 |
| Web | **BGE-M3**（fastembed ONNX int8，纯 CPU） | Skill 广场语义搜索、与广场已有 Skill 的相似度比对（推荐"合并/新增"结论素材） | 仅向量检索/比对，不做文本生成 |
| Web | **Qwen3-4B-Instruct** GGUF Q4_K_M（主选，~2.5GB，Apache-2.0；低配备选 Qwen3-1.7B ~1.2GB，settings 可切换；llama-cpp-python 纯 CPU） | Web 上传通道的中英双语审核报告/README/diff 描述生成 | 异步生成不阻塞交互（纯 CPU 时延数十秒级）；模板兜底 + `generated_by=template\|model` 留痕；输出经审计/脱敏规则重放校验 |

统一要求：本地通道全程提示"性能有限，建议使用外部大模型（CC + MCP 通道）"。

> **✅ V3.0 M4 落地（2026-09-05）**：本地生成侧 `platform_mcp/skills/llm/` 三模块——`__init__.py`（provider 实现：QwenLlamaCppProvider 进程级单例，单槽双层互斥〔per-loop `asyncio.Semaphore(1)` 跨 event loop 自动重建 + `threading.Lock` 全局串行〕+ `asyncio.wait_for` 60s 超时 + 权重/llama-cpp-python 缺失自动降级不可用，VNF-03 绝不联网）+ generation.py（中英 prompt 构造 + `replay_validate_artifact` 重放校验 + `build_iteration_diff` 含 BGE-M3 语义相似度）+ tasks.py（upload 后 BackgroundTasks 异步升级版本存档，VNF-01）；外部通道回传 `submit_skill_artifact`（🔴 拒绝回滚/🟡🟢 透传存档 generated_by=external）；`generated_by` 三态：template（模板兜底）/ model（本地 Qwen3）/ external（CC+glm 5.3 回传）；权重离线校验脚本 `scripts/_init_llm_weights.py`（GGUF 魔数/≥1MB/SHA-256/--probe 加载探测）。门禁：pytest 1470 / mypy 0（96 files）/ vitest 167 / vue-tsc 0 / build 通过。

### 19.5.2 多语种 i18n + 运行时配置中心

> **✅ V3.0 M1 落地（2026-09-03）**：前端 `src/i18n/zh-CN.ts` / `en-US.ts` 语言包（vue-i18n@9.14.5，legacy:false，测试 setup 全局安装）+ 顶栏选择器 + 全站文案 key 化；后端 `platform_mcp/i18n/` 资源字典（16 key × 双语 1:1，单测守护；M1 交付 23 key，复核移除 7 个零消费 `skill.status.*` 键；M2 已随 state_machine 消费方回加至 24 key）+ 注册表/生效语义标签按会话 locale 返回；11 MCP 工具静态描述中英并列；`platform_mcp/common/runtime_config.py` 已知键注册表（14 键）+ 30s 快照缓存 + 登录/会话读取点改造（`session.timeout_minutes` / `sys.default_locale` 登录快照，重登录生效）+ `log.level` 热切换；SystemConfigPage 注册表驱动重写并启用菜单项。门禁：后端 900 passed + mypy 0 errors（80 files）+ 前端 129 passed + vue-tsc 0。

**i18n 架构**：
- 前端：vue-i18n@9（语言包 `src/i18n/zh-CN.ts` / `en-US.ts`，TS 模块随构建打包），当前语言存 localStorage（`pmcp_locale`）+ `pmcp_user.locale`；顶栏语言选择器；所有系统标签/注释/按钮文案走 i18n key，禁止硬编码。
- 后端：`platform_mcp/i18n/` 资源字典（key → zh/en），API 返回的标签类文案经字典本地化。
- Skill 资产：`pmcp_skill_version` 按版本双列存 `readme_zh/readme_en`、`report_zh/report_en`；查看时按用户 locale 返回，缺失语言回退另一语言并标注。
- MCP 工具描述：静态注册的 11+11 工具描述采用"中文 / English"并列写入（FastMCP 描述为静态注册）；动态产物（README、审核报告、搜索结果、差异描述）按认证身份 `locale` 返回。
- **生效语义（2026-09-07 修订，用户裁决）**：默认中文；个人设置可选中/英，切换后**即时生效，平台服务不重启、无需重新登录**——前端 vue-i18n 即时切换；后端生成内容（接入指南 Skill 描述、系统配置注册表文案等）经 `auth.service.get_live_locale` 实时读 `pmcp_user.locale`（读库失败回退登录快照 `SessionInfo.locale`）；MCP streamable-http 每次认证实时读 `pmcp_user.locale`；stdio 进程启动时快照，CC 重开会话即生效。**系统默认语言 `sys.default_locale` 仅影响未设置个人偏好的用户**（如新建用户的初始登录回退值），已有个人偏好的老用户不受影响（个人偏好优先）。同模式扩展 `sys.default_page_size`（个人每页条数，2026-09-07）：用户创建时 seed、登录载荷未设置回退系统默认、`/auth/me` 实时读库；个人设置保存即更新前端 user store，全部列表页每页条数即时生效。
- **扩展性约束**：新增语言 = 加一份 JSON 语言包 + 后端字典条目 + locale 枚举，不允许任何硬编码语言分支。

**运行时配置中心**（系统管理底部"系统配置"标签页，基于现有 SystemConfigPage 升级语义）：
- 管理**非重启即生效**配置项，存储沿用 `pmcp_system_config`；已知键注册表 + 每键生效语义标注（重新登录生效 / 即时生效 / 仅新用户生效〔`sys.default_locale`：只作用于未设置个人偏好的用户〕）+ 值类型与安全级别。
- **参数盘点（2026-09-02，基于 `config.py` 全量 Settings 与消费点 grep 实测分类）**：

| 运行时键（动态，进配置中心） | 现值来源（settings.yml） | 生效语义 | 消费点改造 |
|---|---|---|---|
| `sys.default_locale` | 无（新增） | 仅新用户生效（未设置个人偏好的用户登录回退读取；个人偏好即时生效且优先） | 登录回退读取 |
| `sys.default_page_size` | 无（新增，2026-09-07） | 仅新用户生效（用户创建时作为个人每页条数初始值 seed；个人设置即时生效且优先） | 用户创建 seed + 登录回退 + /auth/me 实时读 |
| `session.timeout_minutes` | 无（新增） | 重新登录生效 | 登录与会话校验读取 |
| `datasource.default_query_timeout` | `datasource.default_query_timeout`（300） | 即时生效 | `datasource/manager.py:81` |
| `datasource.default_max_concurrent` | `datasource.default_max_concurrent`（5） | 即时生效 | `datasource/manager.py:82` |
| `datasource.max_file_size_mb` | `datasource.max_file_size_mb`（10） | 即时生效 | `skills/database/risk.py:273-284` |
| `skill.max_upload_size_mb` | `skill.max_upload_size_mb`（50） | 即时生效 | `skills/upload.py` |
| `smtp.*`（host/port/user/密码/发件人） | 无（V3.0 新增） | 即时生效（outbox flush 时读取） | `notify/` |
| `log.level` | `log.level`（INFO） | 即时生效（重配 loguru sink） | 日志初始化模块 |

> SMTP 键：仅 admin 可改，写操作全量审计留痕；`smtp.password` 为凭证值（列表掩码/编辑留空重写/审计脱敏）。二次确认按 2026-09-04 用户决策移除（装饰性仪式）。
>
> 可选值枚举（编辑下拉渲染 + 校验单一出处，2026-09-07）：`sys.default_locale` 候选派生自后端 `i18n.SUPPORTED_LOCALES`（随新增语言自动扩展）、`sys.default_page_size` = 5/10/20/50/75/100、`log.level` = loguru 七级（TRACE/DEBUG/INFO/SUCCESS/WARNING/ERROR/CRITICAL，大小写不敏感归一大写）；注册表 API 经 `choices` 字段下发（int/str 均可），前端编辑框按其渲染下拉，locale 候选显示语言自称（与顶栏/个人设置切换器同源 LOCALE_OPTIONS）。
>
> 保留为**静态引导配置**（settings.yml，重启生效；不进配置中心）：进程与接入绑定（`server.host/port/workers`、`server.cors_origins`、`mcp.transport/http_host/http_port/http_path`）、系统库引擎（`database.url/pool_size/max_overflow/echo`）、Oracle 客户端与安全路径（`datasource.oracle_instant_client_dir`、`datasource.crypto_key_path`、`datasource.sftp_exchange_dir`）、SQL 文件路径白名单（`datasource.allowed_sql_dirs`，各 PROD 环境自行设置）、日志布局（`log.dir/rotation/retention`，仅 `level` 动态）、Skill 存储布局（`skill.upload_dir`）、V3.0 模型权重路径（`skill.llm_model_path` / `skill.embedding_model_path` 等，加载期初始化，切换需重启）、应用标识（`app.name/version/env`）。

- **分类原则**：①进程/连接/路径/凭证/权重绑定类 + 环境级路径白名单（allowed_sql_dirs）→ 静态（重启生效）；②业务阈值/开关/模板/日志级别类 → 运行时中心。与 §16.3 一期预留口径（"限流参数、风险规则开关经 pmcp_system_config 动态调整"）衔接落位。
- **环境白名单参数取消（2026-09-04 用户决策）**：`mcp.allowed_envs`（MCP 可访问环境白名单）移除——环境访问控制由"角色规则（developer 禁 PROD）+ 组过滤（manager 层）"完整覆盖，admin 全权限、一般用户无 db/server 权限，该参数无实质使用场景，不再进注册表与 Settings。
- 读取点统一经带短缓存（30s）的配置服务，避免每请求查库；文档与代码均须维持此边界。

### 19.5.3 Skill 广场与生命周期状态机

> **✅ V3.0 M2/M3 落地（2026-09-03 / 2026-09-04）**：migration 006（`pmcp_skill_plaza` + `pmcp_skill_version`〔UNIQUE(skill_id,version) 不可篡改 + generated_by 留痕〕+ `pmcp_skill_blacklist`〔双 UNIQUE + 至少一目标 CHECK〕+ `pmcp_skill` 加 plaza_id/origin/share_status/review_comment）+ migration 007（embedding JSONB + 条件 pgvector `vector(1024)`，受限自动降级 JSONB+内存余弦）；8 状态 varchar 状态机 + 转移校验 + 个人库可见性过滤；registry 启动与路由真实消费 `pmcp_skill.status`（勘误 5 关闭）；`platform_mcp/review/` 可复用审核服务（Skill 与三期 KB 共用）；MCP 双通道 5 工具 + `api/plaza.py` 9 端点（含 admin 停用：停用后全角色双端不可见、版本存档与审计保留，可经重新分享恢复）+ `plaza_visible_to_role` 双端共用可见性（一般用户涉库/涉服务器不可见）+ 黑名单双端过滤 + 功能广场页 PlazaPage（广场/黑名单双 Tab + 语义搜索 + README 双语弹窗 + 复制/屏蔽/撤销/停用〔仅 admin〕；列表不显示版本/分享者/描述，RM 在操作列）。门禁：pytest 1364 / mypy 0（93 files）/ vitest 163 / vue-tsc 0 / build 通过。

**数据模型（独立表方案）**：个人库（`pmcp_skill`）与公共池（`pmcp_skill_plaza`，含独立 version 链、`involve_flags`、embedding、uploader_id、iteration_note）生命周期解耦——"广场副本不受未审核更新影响"天然成立。`pmcp_skill` 加 `plaza_id` / `origin(ORIGINAL|PLAZA)` / `share_status`。版本表 `pmcp_skill_version`（skill_id, version, checksum, readme_zh/en, report_zh/en, audit_snapshot JSONB, generated_by）。黑名单 `pmcp_skill_blacklist`(user_id, target_skill_id/plaza_id, unique)。

**状态机**（`pmcp_skill.status` 由 smallint 转 varchar 枚举，迁移 005 存量映射 1→ENABLED / 2→PENDING_REVIEW / 3→REJECTED / 0→DISABLED）：

```
草稿 DRAFT ──提交分享──→ 审核中 PENDING_REVIEW ──admin:新增入广场──→ 个人侧已启用 ENABLED（广场副本=已发布）
   ↑                          ├─admin:合并到广场已有 Skill(填迭代说明)──→ 分享迭代 SHARE_ITERATION*（若 origin=PLAZA）
   │                          ├─admin:拒绝(填原因+邮件)──→ 已拒绝 REJECTED ──修改后──→ DRAFT
   │                          └─用户停用──→ 撤回 WITHDRAWN(邮件 admin 组) ──恢复──→ DRAFT
   └── DRAFT/审核中 均可被本人经 MCP 使用（未过审仅本人可用）
SHARE_ITERATION ──用户选"迭代"(若本地已改则先出 diff：Web=BGE-M3+Qwen 比对 / MCP=外部大模型提示差异；迭代=覆盖本地) 或"保留"(忽略本次迭代)──→ ENABLED（不再显示版本迭代）
ENABLED ──停用──→ DISABLED（已过审 Skill 创建人停用，广场副本仍可正常使用）
```

\* 分享迭代出现条件：admin 审核结论 = 更新广场现有 Skill，且该 Skill 本身源自广场（origin=PLAZA）。重复分享：提示"已分享，正在审核中"二次确认后覆盖上一版本并重新邮件审核组。

**可见性矩阵**（√=可见；M=MCP 调用可用，W=Web 可见。Skill 一律 Web 不可执行、仅 MCP 可执行）：

| 状态 | 上传者本人 | 其他 dev | 一般用户 | admin |
|---|---|---|---|---|
| 草稿 / 已拒绝 / 撤回 | √ M | × | × | ×（含 admin 不可见） |
| 审核中 | √ M | × | × | √ W（审核操作） |
| 已启用（未分享） | √ M | × | × | × |
| 广场已发布 | √ M+W | √ W+M（复制/使用） | √ W+M（**涉库/涉服务器除外**） | √ W |
| 分享迭代 | √ M+W（选择页+迭代说明） | 广场旧版仍可见 | 广场旧版 | √ |

- **涉库/涉服务器标记**：由 `audit_result` JSONB 中 R2-xx / R3-xx 规则命中分类派生，写入 `pmcp_skill_plaza.involve_flags`；带此标记的广场 Skill 对一般用户在 Web 与 MCP 双端均不可见（需求 1.1.4）。
- **黑名单**：用户屏蔽某 Skill 后，该 Skill 在其 Web 与 MCP 双端不可见，仅黑名单页可见，可撤销。
- **动态加载暴露（用户确认）**：上传 Skill 经 MCP 动态暴露给 CC 使用——`list_my_skills`/`search_skills`/`get_skill_readme` 等工具按上述可见性返回；合规审计（14 条规则）为第一道审核；admin 审核控制入广场共享；未过审仅上传者本人可用。Skill 包形态 = SKILL.md + README + references 文档型资产（在 CC 侧生效），**平台不执行任意 Python**（与审计引擎 R2/R3 安全立场一致）。
- **MCP 双通道创建/更新**：CC 经 MCP `create_skill_draft`（先自动 `suggest_similar_skills` 扫广场，有类似优先推荐）/ `update_my_skill`（仅能更新自己个人库内的 Skill）；Web 上传 zip/7z 沿用 V2.1 链路并升级为版本化。每次新增/更新均生成中英双语审核报告（SkillStandard 14 条合规规则 + 广场比对"推荐合并/新增"结论）与中英双语 README，**每个版本存档**供 admin 审核与后续审计。
- **已提交未过审的 Skill 若用户停用**：视同撤回审核（→ WITHDRAWN），邮件通知 admin 审核组。

### 19.5.4 统一组模型与三角色权限矩阵

**统一组（用户确认，迁移 005）**：新 `pmcp_group`（group_name, env_code, description, status）+ 三张成员表 `pmcp_group_user` / `pmcp_group_datasource` / `pmcp_group_server`（外键完整性优先于多态单表）。迁移：建新表 → 按"同 env 同名合并"回填存量（数据源组与服务器组同名则并为一条）→ 校验 SQL → DROP 5 张旧表（pmcp_datasource_group / pmcp_server_group / 2 张 group_member / pmcp_user_group）。组可新增/停用/编辑（名称/调整组员/调整数据源/调整服务器）。**组员仅 developer 角色用户**（2026-09-07 收口）：组过滤不对 admin/一般用户生效（admin 直通、一般用户无 db/server 权限，入组无权限语义），`PUT /groups/{id}/members`（resource=user）与 `PUT /groups/users/{id}` 非 developer 角色返回 14005（校验先于覆盖式清空），分组管理页组员下拉仅列 dev 用户（用户管理页分配分组按钮本就仅 dev 行可用）。

**组过滤下沉**：`datasource/server/manager.py` 的 `list_*` 增 user_id 参数——admin 直通全部；developer 仅返回所属组内对象（无组返回空，勘误 3 裁决）；一般用户不适用（无 db/server 权限）。Web API 与 MCP 工具双入口统一走 manager 层（修复勘误 1）。

**三角色权限矩阵**（页面级）：

| 页面/能力 | admin | developer | 一般用户 |
|---|---|---|---|
| Skill 管理（个人库 CRUD/更新/分享/撤回） | √ | √ | √ |
| 广场审核（合并/新增/拒绝） | √（仅 admin；按钮仅"审核中"状态可用；Web 审核弹窗 + MCP `review_skill` 双端承接） | × | × |
| 数据源/服务器管理 | 全操作 | 仅查看所属组 + 测试连接（仅"测试"按钮可见） | × |
| 分组管理 | √ | × | × |
| 用户管理 | √ | × | × |
| 密码加密 / 系统配置 / 邮件提醒 | √ | × | × |
| 审计日志 | 全部 | 仅自己 | 仅自己 |
| 功能广场（广场+黑名单） | √ | √ | √（涉库 Skill 除外） |
| MCP 工具 | 31 全部 | 30（仅排除 `review_skill`） | 19（Skill 生态 + 查询/个人类；database/server 执行类与 `review_skill` 不可见；系统管理四类仅 Web，见 §19.5.7） |

### 19.5.5 邮件组提醒

> **✅ V3.0 M5 已全部落地（2026-09-05，head=009）**：migration 009（notify 三表 + `pmcp_user` 锁定字段 failed_attempts/locked_until + 四组默认模板 seed）+ `platform_mcp/notify/` 服务层（service：render_template 参数化渲染 + dispatch_notification 独立 session 异常全捕获不阻断业务；sender：outbox 取件发送 + 周期 flush 任务挂 Web 进程 lifespan）+ 捕捉点三类（`write_audit_log` 单一咽喉路由 `_resolve_high_risk_notify_type` 覆盖 Web+MCP 双入口；skill_review 提审/审核通过/合并/拒绝/撤回五流程点 + 结果全量通知提交人；user_mgmt 用户创建/停用/角色变更/API Key 重置撤销 + 连续登录失败锁定〔5 次锁 15 分钟，锁定期静默不计次〕）+ `api/notify.py` 六端点（组列表/组更新/成员加删/outbox 分页记录/测试发送，错误码 13001-13007）+ 前端 NotifyPage（四事项启停/成员管理〔候选仅 admin + 无邮箱提示〕/模板编辑含参数说明/outbox 发送记录/测试发送）。SMTP 参数经运行时配置中心 `smtp.*` 五键维护（密码 AES-GCM 加密落库、读出透明解密兼容历史明文；未配置时 outbox 堆积待发周期重试，不阻断业务）。验收 F-37（四组路由/仅 admin 入组/无邮箱提示/停用组静默）/ F-38（失败可重试、全程可审计、无 fire-and-forget）/ F-39（模板可编辑、参数替换正确）全过；R-13 SMTP 列为生产前置依赖（部署规范 §2.7），outbox 独立可测。

- **四个提醒事项**（`pmcp_notify_group.notify_type`，2026-09-02 定稿）：

| notify_type | 触发事件 | 收件人 |
|---|---|---|
| `db_high_op` | 生产（PROD）HIGH 及以上数据库操作 | 组内成员 |
| `server_high_op` | 生产（PROD）HIGH 及以上服务器操作 | 组内成员 |
| `skill_review` | Skill 审核事件：提审（通知审核组）/ 审核结果全量通知提交人（通过 / 合并 / 拒绝，非仅拒绝） | 组内成员；结果通知另发提交人本人 |
| `user_mgmt` | 用户管理安全事件：API Key 重置/撤销（通知本人）、用户创建/停用/角色变更/连续登录失败锁定 | 组内成员（admin 组）**∪ 相关用户本人** |

- 每项独立启停、独立成员、独立邮件模板。
- **成员**：`pmcp_notify_group_member`——**仅 admin 角色用户可入组**（录入时校验），未配置邮箱者录入时提示。
- **模板**：subject/body 可编辑，内置参数 `{{user}}` / `{{resource}}` / `{{env}}` / `{{risk}}` / `{{time}}` / `{{reason}}`（拒绝原因）/ `{{iteration_note}}`（迭代说明）/ `{{action}}`（创建/停用/角色变更/Key 重置等动作），参数描述可改。
- **捕捉点**：db_high_op / server_high_op 统一挂 `audit/logger.py:write_audit_log` 内部按 `(resource_type, risk_level ∈ {HIGH,CRITICAL}, env_code=PROD, notify_type)` 路由——单一咽喉同时覆盖 Web 与 MCP 双入口；skill_review 在提审/审核/撤回流程点显式触发；user_mgmt 在用户管理/API Key 服务层显式触发。
- **发送**：aiosmtplib + **outbox 模式**（`pmcp_notify_outbox` 表 + 周期 flush 任务），避免 async fire-and-forget（部署原则 #5），失败可重试、全程可审计。SMTP 参数经 settings + 运行时配置中心覆盖（密码 AES-GCM 加密列）；**生产 SMTP 服务器参数为部署前置依赖（用户提供）**。

### 19.5.6 本地模型栈（Web 通道）

> **✅ V3.0 M3/M4 已全部落地**：向量侧（M3）——`skills/embedding.py` EmbeddingStore 双实现 + migration 007，pgvector / JSONB 降级；生成侧（M4）——`skills/llm/`（provider + generation + tasks），Qwen3-4B GGUF 经 llama-cpp-python 纯 CPU，权重缺失/超时 60s/校验失败自动模板兜底，`generated_by` 三态留痕（template/model/external）。

| 层 | 选型 | 说明 |
|---|---|---|
| 向量 | BGE-M3（`BAAI/bge-m3`）经 **fastembed**（ONNX Runtime CPU int8） | 无 torch 依赖；广场语义搜索 + 相似度比对；`EmbeddingStore` 抽象双实现——pgvector（生产可装扩展时）或 JSONB 存储 + 内存余弦（Skill 量级 <数千可行，pgvector 受限时降级路径） |
| 生成 | Qwen3-4B-Instruct GGUF Q4_K_M（主选）/ Qwen3-1.7B（低配备选），**llama-cpp-python** 纯 CPU | ✅ M4 已落地（provider 实现位于 `skills/llm/__init__.py`：单槽互斥 + 60s 超时 + 进程级单例）：中英双语 README/审核报告/diff 描述；异步生成不阻塞交互（upload 后 BackgroundTasks 后台升级，VNF-01）；RAM ~3-4GB |
| 兜底 | 确定性模板（复用 V2.1 README 模板 + 审计规则结构化报告） | 权重缺失/超时 60s/输出校验失败 → 模板兜底，`generated_by=template\|model\|external` 三态落版本存档（Web 前端版本行标签 + 弹窗提示） |
| 校验 | 14 条审计规则 + 脱敏器重放 | 本地模型与外部模型产物一律重放校验后入档 |
| 部署 | 权重内网离线分发 | settings 配 `skill.llm_model_path` / `skill.embedding_model_path`（SkillSettings 段，静态配置重启生效）；权重不入仓库、不联网下载；离线校验脚本 `scripts/_init_llm_weights.py`（GGUF 魔数/体积/SHA-256/--probe 加载探测） |

### 19.5.7 MCP/Web 双端能力边界与工具扩展（11 → 31）

> **✅ V3.0 M3/M4 落地（2026-09-04 / 2026-09-05）**：registry `ToolMeta` 增 `roles: set[str]`，`list_tools` 与调用路由按认证身份 role_code 动态过滤（stdio 进程级绑定同样生效）；工具 11→**31**（skill 生态/双通道 16 + 双端承接 4；M3 交付 29，M4 追加 `submit_skill_artifact` / `get_skill_iteration_diff`）；三角色过滤矩阵实测 **admin 31 / developer 30（仅排除 review_skill）/ 一般用户 19**（database/server 执行类与 review_skill 对一般用户不可见；单测矩阵固化）。

**双端能力边界原则（2026-09-02 用户定稿）**：除以下四类**仅 Web** 外，其余功能 MCP 与 Web 双端均可操作；每个功能有前端展示即有后端承接，且（除四类外）有对应 MCP 工具承接——**禁止装饰性功能**（有 UI 无实效、或写库无消费方）。

**仅 Web 的四类（MCP 不设管理工具）**：

| 类别 | MCP 端边界 |
|---|---|
| 装饰器注册的内置 Skill（database/server）管理 | 工具调用可用；**不可**更新/屏蔽/移除/启停（启停等管理仅 Web SkillPage） |
| 数据库/服务器管理 | `list`/执行/校验类工具可用；**不可**新增/修改/删除/启停/分组分配/测试连接 |
| 系统管理 | 用户管理、分组管理、系统配置（运行时配置中心）、邮件提醒、密码加密——全类仅 Web（admin） |
| 帮助 | MCP 接入指南页仅 Web |

registry `ToolMeta` 增 `roles: set[str]`，`list_tools` 与调用路由按认证身份 `role_code` 动态过滤（stdio 进程级绑定同样生效）。V3.0 新增 20 个工具：

| 工具 | 用途 | 可见角色 |
|---|---|---|
| `search_skills` | 广场语义搜索（query → embedding → topK） | 全部角色（按可见性过滤结果） |
| `suggest_similar_skills` | 创建前相似推荐（推荐合并/新增结论） | admin + developer + 一般用户 |
| `get_skill_readme` | README 内容（按 locale） | 全部角色（按可见性） |
| `add_skill_to_my` / `remove_my_skill` | 广场复制到个人库 / 移除 | admin + developer + 一般用户 |
| `create_skill_draft` / `update_my_skill` | MCP 创建草稿 / 更新自己的 Skill | 同上 |
| `submit_skill_for_review` / `withdraw_review` | 提交分享审核 / 撤回（停用视同撤回） | 同上 |
| `resolve_share_iteration` | 分享迭代：迭代（覆盖本地）/ 保留 | 同上 |
| `submit_skill_artifact` | ✅ M4：外部大模型产物回传（CC+glm 5.3 生成中英报告/README 回传；重放校验 🔴 拒绝/🟡🟢 透传后按版本存档 generated_by=external） | 同上 |
| `get_skill_iteration_diff` | ✅ M4：分享迭代差异（广场快照 vs 本地 SKILL.md：行级 diff + 语义相似度 + 双语描述 + 性能提示） | 同上 |
| `block_skill` / `unblock_skill` / `list_blocked_skills` | 黑名单屏蔽/撤销/清单 | 同上 |
| `list_my_skills` | 个人 Skill 清单 + 状态 | 同上 |
| `review_skill` | 广场审核（action=approve 新增 / merge 合并（含迭代说明）/ reject 拒绝（含原因）；触发 skill_review 邮件） | **仅 admin**（对应 Web 审核弹窗的双端承接） |
| `query_audit_logs` | 审计日志查询（分页/时间/资源类型过滤；admin 全量、其他角色仅自己——同 Web 可见性） | 全部角色 |
| `update_profile` | 个人设置（nickname / email / locale，重登录生效语义同 §19.5.2） | 全部角色 |
| `change_password` | 修改密码（校验当前密码） | 全部角色 |

- database/server 的 10 个执行类工具 `roles` 排除一般用户；四类"仅 Web"功能不设 MCP 工具（见上表边界）。
- 工具描述"中文 / English"并列（§19.5.2）；工具数扩至 31 后 CC 端建议按需启用（风险清单 R11）。
- **反装饰性验收（强制）**：每个前端按钮 → API → 真实业务效果全链路可验证；每个写库状态必须有消费方（如 `pmcp_skill.status` 须被 MCP 注册/路由真实读取——见 §19.4 勘误 5 整改）。

### 19.5.8 数据模型迁移链与可行性结论

迁移链：✅ **005**（统一组 + `pmcp_user.locale` + role seed `user` + `pmcp_skill.status` 转 varchar，M0）→ ✅ **006**（`pmcp_skill_plaza` / `pmcp_skill_version` / `pmcp_skill_blacklist` + `pmcp_skill` 加 plaza_id/origin/share_status/review_comment，M2）→ ✅ **007**（plaza embedding JSONB 列 + 条件 pgvector `vector(1024)` 列，M3）→ ✅ **008**（`pmcp_group` DROP env_code 组与环境正交〔跨环境同名组已合并 + UNIQUE(group_name)〕，M3R 后插入，原拆分口径的 notify 位被占用）→ ✅ **009**（`pmcp_notify_group` / `pmcp_notify_group_member` / `pmcp_notify_outbox` + `pmcp_user` 锁定字段 + 四组模板 seed，M5）→ ✅ **010**（`pmcp_kb` 五表骨架，§19.6，M6）→ ✅ **011**（notify param_descriptions 双重编码数据修复，2026-09-07）→ ✅ **012**（`pmcp_user.page_size` 个人每页条数 + 存量回填 20，head=012）。均含 documents/db 同步 SQL 与可回滚 down（统一组迁移需停机窗口 + 回填校验 SQL）。编号按里程碑消费顺序拆分（原 007=notify+embedding 捆绑口径已于 M3 落地时更正；008 插入后 notify/KB 依次顺延 009/010；F-42 编号一致性终核已于 M6 收口时完成全文档核验）。

| 模块 | 可行性结论 | 量级 |
|---|---|---|
| Skill 8 状态生命周期 + 版本化双语存档 | 可行 | M |
| 统一组迁移 | 有条件可行（停机窗口 + 回填校验 + 可回滚） | M |
| i18n（含 MCP 描述并列 + 动态产物按 locale） | 可行（stdio 快照语义文档明示） | L |
| 双模型栈 | 有条件可行（CPU 时延→异步+模板兜底；权重离线分发；pgvector 受限时 JSONB 降级） | L |
| 邮件 outbox | 可行（SMTP 参数为生产前置依赖） | S |
| MCP 角色过滤 + 工具翻倍 | 可行（过滤单测矩阵覆盖） | M |
| 一般用户第三角色 | 可行 | S |
| 广场独立表方案 | 可行 | M |

---

## 19.6 三期框架（知识库，V3.0 末里程碑搭建骨架）

> **✅ V3.0 M6 已落地（2026-09-05，head=010）**：migration 010（kb 骨架五表：`pmcp_kb`〔kb_type personal/shared CHECK + owner + status 值域复用 review 8 状态〕/ `pmcp_kb_doc` / `pmcp_kb_chunk`〔chunking_strategy 7 枚举 + embedding JSONB 同 plaza 惯例，pgvector 原生列三期条件创建〕/ `pmcp_kb_version`〔双语字段同 pmcp_skill_version 惯例，UNIQUE(kb_id,version)〕/ `pmcp_kb_share`〔merge_target_id + review_comment〕）+ `platform_mcp/kb/` 空包（models 五表 ORM + chunking.py 7 切片枚举〔fixed/sentence/paragraph/semantic/recursive/markdown_heading/sliding_window〕+ rag.py Indexer/Retriever 抽象 + graph.py GraphStore 抽象，F-41）+ `api/kb.py` 七端点 501 占位（HTTP 501 + 统一响应 code=15002，沿用二期前占位惯例；三期实现 RAG 检索/GRAPH 查询/文档导入/分享送审）。审核流挂接点就绪：status/review_status 值域与 `platform_mcp/review/` 状态机同构，三期直接挂接不另建。单测 22 例（五表 ORM/枚举值域/ABC 抽象强制/501 端点参数化）。门禁：pytest 1554 / mypy 0（108 files）/ vitest 174 / vue-tsc 0 / build 通过。F-42 一致性终核随 M6 收口完成（本节 + §14.1 + §19.5.8 + 正式版/计划/CLAUDE.md/README×2 编号与表数 27 张对齐）。

三期定位：个人知识库 / 专用知识库（可分享）/ 个人精炼成专用；**RAG + GRAPH 双维护**，RAG 支持常规 7 种切片方式；审核流与 Skill 同构（审核报告/合并或新增结论/迭代差异/拒绝原因/分享迭代选择）；全功能双通道（MCP+外部大模型 / Web+本地模型栈，兑底提示性能有限）。

**V3.0 仅搭骨架（用户确认）**：
- 表结构（迁移 010，编号按 §19.5.8 拆分口径，008 组去环境维度插入后 KB 由 009 顺延至 010）：`pmcp_kb`（知识库主体：personal/shared 类型、owner、状态机复用 review 抽象）/ `pmcp_kb_doc`（文档）/ `pmcp_kb_chunk`（切片，含切片策略与 embedding 列）/ `pmcp_kb_version`（版本存档，双语字段同 Skill 版本表惯例）/ `pmcp_kb_share`（分享与审核关联）。
- 空模块 `platform_mcp/kb/`：`api/kb.py`（端点返回 501，沿用二期前占位惯例）、`rag.py`（`Retriever` / `Indexer` 抽象接口）、`graph.py`（`GraphStore` 抽象接口）、`chunking.py`（7 种切片策略枚举：`fixed` / `sentence` / `paragraph` / `semantic` / `recursive` / `markdown_heading` / `sliding_window`）。
- 审核流复用：V3.0 把 Skill 的"提交-审核-合并/拒绝-分享迭代"抽为可复用服务 `platform_mcp/review/`，三期 KB 直接挂接，不再另建。

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

- **decorator 静态注册**（V1.0）：`@register_skill` 装饰 database/server 两个内置 Skill 包，进程启动时注册。
- **源码包上传注册**（✅ V2.1 已实现，2026-08-13）：`api/skills.py:POST /skills/upload` 支持 .7z/.zip（≤50MB），链路=解压→SKILL.md frontmatter 解析→14 条合规审计→README 模板生成→写 `pmcp_skill`（待审核）+ `pmcp_skill_audit_report`→admin 审核启用（内部引用脱敏环节 2026-09-07 移除，见 §8.2.1 注记）。原 501 占位（`create_skill`）与前端置灰按钮已被此实现取代。
- **V3.0 演进**：上传注册升级为"双通道 + 版本化 + 动态加载暴露"——Web 上传 zip/7z 与 CC 经 MCP 直接创建/更新并存；每次新增/更新生成中英双语审核报告与 README 并按版本存档（`pmcp_skill_version`）；上传 Skill 经 MCP 按可见性动态暴露给 Claude Code 使用（合规审计为第一道审核、admin 审核控制入广场共享、未过审仅上传者本人可用、Web 端不可执行仅 MCP 可执行——平台不执行任意 Python，Skill 包形态为 SKILL.md+README+references 文档型资产，在 CC 侧生效）。详见 §19.5.3。

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
