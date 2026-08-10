# Platform-MCP 架构说明

- **适用对象**：项目管理人员、架构师
- **文档用途**：用于项目评审、立项汇报、方案说明与实施边界对齐

---

## 版本记录

| 版本 | 日期 | 修订摘要 | 修改人 |
|---|---|---|---|
| V1.0 | 2026-05-28 | 基于技术架构说明文档 V1.0 提炼，形成正式版架构说明 | castle.zhang |
| V1.1 | 2026-05-29 | 新增 Skill 管理页与个人设置页；密码加解密页更名为密码加密页；补充 Skill 注册方式说明；登录页改为双栏布局；补充 pmcp_skill 系统表 | castle.zhang |
| V1.2 | 2026-06-03 | POC 验证结论同步：Oracle 驱动策略从 thin async 切换为 thick 模式 + run_in_executor（thin 模式不支持 11g，thick 6/6 通过）；MySQL aiomysql 14/14 项全量通过；双角色模型（admin/developer）与 Skill 审核流程定稿；新增 MCP 接入指南页；PROD 数据源仅 admin 可调用 | castle.zhang |

---

# 1. 文档概述

## 1.1 编写背景

Platform-MCP 项目面向内部场景建设统一的 MCP（Model Context Protocol）能力平台。项目首期聚焦数据库 Skill，通过标准 MCP 接口承接 Claude Code 等调用方的数据库执行请求，同时建设配套的管理界面、权限控制、状态查看和审计能力。

## 1.2 文档目标

- 明确系统定位、建设范围与实施边界
- 明确总体架构形态与核心设计决策
- 明确技术选型结论与兼容性风险
- 明确模块职责划分与 MCP 扩展方式
- 明确迭代分期规划与验收标准

## 1.3 适用范围

| 角色 | 用途 |
|---|---|
| 项目管理人员 | 了解建设范围、分期计划与验收标准 |
| 架构师 | 架构评审、方案对齐与演进设计 |

---

# 2. 系统定位与建设原则

## 2.1 系统定位

- MCP 统一能力服务平台
- 首期聚焦数据库 Skill 的执行服务
- 带 Web 管理台的内部管理平台
- 可扩展其他 Skill 的技术底座

本系统核心执行入口为 MCP（通过 Claude Code 调用），Web 端主要承担管理、审计和运维支撑职责，不作为主要 SQL 编写执行入口。

## 2.2 建设范围

**一期目标：**

- 提供 Claude Code 可调用的 MCP 服务入口
- 首期支持数据库 Skill，执行本地 `.sql` 文件和 SQL 文本
- 提供统一权限管理、数据源管理和审计能力
- 支持 Oracle 11g、MySQL 5.6 等存量数据库接入
- 提供密码加解密管理界面和 MCP 调用状态查看页面
- 保留后续扩展其他 Skill 的能力

**不纳入建设范围：**

- Web 在线 SQL 富编辑器
- 工作流审批引擎
- 微服务拆分
- Docker/K8s 云原生部署
- 多机房高可用架构
- 大规模分布式任务调度平台

## 2.3 建设原则

| 原则 | 说明 |
|---|---|
| 稳定优先 | 选择成熟、长期维护稳定的技术组件 |
| 兼容优先 | 兼容存量数据库（Oracle 11g、MySQL 5.6）、老驱动和传统部署方式 |
| 简单优先 | 不引入 Docker、K8s、微服务等当前阶段不必要的复杂度 |
| 扩展优先 | MCP 层按 Skill 插件式能力扩展设计，首期即固化接口规范 |
| 审计优先 | 所有关键调用、配置变更、安全操作全链路可追溯，审计从首阶段贯穿建设 |

---

# 3. 总体架构设计

## 3.1 架构结论

系统采用以下架构形态：

- **Python 单体模块化架构**
- **双入口设计：FastAPI Web 管理端 + MCP Server（stdio 模式）**
- **共享业务逻辑层 + PostgreSQL 系统库**
- **Python 数据库驱动连接目标数据库（Oracle thick 模式通过 run_in_executor 异步包装）**
- **虚拟环境部署 + systemd + Nginx**

## 3.2 双入口架构

系统存在两个独立运行的入口进程，共享同一套业务逻辑：

| 入口 | 运行方式 | 职责 |
|---|---|---|
| FastAPI Web（main.py） | systemd 托管，Gunicorn + Uvicorn Worker 运行 | 登录认证、数据源管理、密码加解密、审计查询、用户管理 |
| MCP Server（mcp_server.py） | Claude Code 以子进程启动，stdio 模式运行 | MCP Tool 接入、Skill 路由、Tool 执行 |

两个入口共享以下业务逻辑模块：Skill 注册与路由、SQL 执行器、风险识别引擎、数据源管理、密码加解密、审计日志、通用工具。

Skill 注册方式一期仅支持装饰器注册（通过 `@register_skill` 静态注册）。页面新增（Web 表单提交）、源码上传解析（.py / .jar 文件解析后由管理员确认注册）为二期功能（开发计划 L497 明确推迟，`api/skills.py:create_skill` 当前返回 501，前端 `SkillPage.vue:94` 置灰按钮 title="二期功能"）。

## 3.3 逻辑架构分层

| 层次 | 内容 |
|---|---|
| 调用侧 | Claude Code（MCP 协议）、Web 管理用户（浏览器）、运维管理员 |
| 接入层 | MCP Tool 接口（stdio）、Web REST API（HTTP/HTTPS） |
| 业务服务层 | 权限认证、MCP 请求分发与 Skill 路由、数据源管理、密码加解密、SQL 执行与风险识别、审计日志与状态监控 |
| 数据层 | PostgreSQL 16.4（系统库）、Oracle 11g / MySQL 5.6（业务执行目标库） |

## 3.4 核心使用场景

### 场景 A：Claude Code 执行 SQL 脚本

Claude Code 通过 MCP Server 接入本系统。用户持有本地 SQL 脚本，通过提示指定目标环境，系统自动匹配对应数据源，读取 SQL 文件内容，执行 SQL 并审计过程及结果。

### 场景 B：高风险操作二次确认

当 SQL 执行触发高风险标识（DELETE 无 WHERE、DROP、TRUNCATE、存储过程调用等），系统返回风险提示，要求用户二次确认后方可继续执行。确认与取消操作均写入审计日志。

### 场景 C：管理员配置数据源密码

管理员通过 Web 管理端输入明文密码，后端执行 AES-256 加密后返回密文，保存至数据源配置，并写入加密操作审计日志。

---

# 4. 技术栈概览

| 领域 | 技术选型 |
|---|---|
| 后端语言 | Python 3.11.9（全环境统一锁定） |
| Web 框架 | FastAPI + Uvicorn + Gunicorn |
| 数据校验 | Pydantic v2 + pydantic-settings |
| 系统库 ORM | SQLAlchemy 2.0（AsyncSession）+ asyncpg + Alembic |
| Oracle 驱动 | oracledb thick 模式 + run_in_executor（需 Oracle Instant Client） |
| MySQL 驱动 | aiomysql |
| 加解密 | cryptography（AES-256-GCM） |
| MCP SDK | mcp Python SDK（stdio 模式） |
| 前端框架 | Vue 3 + TypeScript + Vite |
| UI 组件库 | Element Plus |
| 状态管理 | Pinia |
| HTTP 客户端（前端） | Axios |
| 系统数据库 | PostgreSQL 16.4 |
| 反向代理 | Nginx |
| 进程管理 | systemd |
| 部署环境 | Rocky Linux 9.4 / RHEL 9.x / CentOS Stream 9 |

**统一异步策略：** 数据库驱动统一采用异步方案（asyncpg、aiomysql）；Oracle 11g 因 thick 模式仅提供同步 API，通过 asyncio.run_in_executor 包装，事件循环保持非阻塞。

---

# 5. 模块化架构设计

## 5.1 一期模块清单

一期共 7 个模块：

| 模块 | 职责 |
|---|---|
| `platform_mcp.api` | FastAPI Web 接口，前端对接与页面数据聚合 |
| `platform_mcp.auth` | 认证鉴权，登录认证、用户/角色/权限管理 |
| `platform_mcp.datasource` | 数据源管理与密码加解密 |
| `platform_mcp.mcp_server` | MCP 协议接入、Skill 接口定义、注册与路由分发、Skill 管理与生命周期 |
| `platform_mcp.skills.database` | 数据库 Skill 业务逻辑、SQL 执行、风险识别 |
| `platform_mcp.audit` | 审计日志记录、MCP 调用状态统计、服务运行状态输出 |
| `platform_mcp.common` | 通用异常、响应模型、枚举、工具类、常量 |

## 5.2 Skill 架构

MCP 层按"统一入口 + Skill 扩展"设计：

- MCP Server 负责协议接入
- Skill 负责能力实现
- Registry 负责路由分发
- Audit 负责全链路记录

**关键约束：** Database Skill 相关逻辑不得侵入 mcp_server 模块。mcp_server 仅处理协议接入、参数标准化、上下文封装和响应封装。

一期采用基于 `typing.Protocol` 的 Skill 接口定义和装饰器注册模式，维护 Tool 名称前缀到 Skill 的映射表。

### 一期 Skill 与 Tool 规划

一期仅建设 `database` Skill，提供以下 Tool。一期 Web 管理端新增 Skill 管理页，支持查看已注册 Skill 列表、使用方式、Skill 启停与审核操作。developer 提交 Skill 进入"待审核"，admin 审核后启用或驳回。

| Tool | 说明 |
|---|---|
| `execute_sql_file` | 接收文件路径，读取本地 SQL 文件并执行 |
| `execute_sql_text` | 接收 SQL 文本直接执行 |
| `validate_sql` | 校验 SQL 语法并返回风险等级 |
| `list_datasources` | 列出可访问的数据源 |
| `get_execution_status` | 查询异步执行任务的状态 |

每个 Skill 需统一实现 `skill_name`、`list_tools`、`validate`、`execute`、`support` 五个方法。

二期预留 Skill：`file`、`log`、`config`、`deploy`、`shell`。

### MCP 认证策略

一期通过 **API Key 机制** 实现 MCP 层用户级认证。admin 创建用户时自动生成 Key（`pmcp_` + 43 字符随机串），用户写入 `~/.claude.json` 配置（stdio 模式 `env.PLATFORM_MCP_API_KEY`，streamable-http 模式 `headers.PLATFORM_MCP_API_KEY`）。MCP Server 校验 Key 后确定调用者身份和角色，按角色判定数据源/环境访问权限。Key 的 SHA-256 哈希存储于 `pmcp_api_key` 表，支持撤销/重置。

## 5.3 二期模块拆分预案

当第二个 Skill 落地或模块复杂度增加时，按需从现有模块提取：

| 拆分项 | 来源 | 触发条件 |
|---|---|---|
| skill_api | mcp_server | 第二个 Skill 落地时 |
| skill_registry | mcp_server | 注册路由复杂度增加时 |
| sql_executor | skills.database | 引入数据库方言抽象层时 |
| risk_engine | skills.database | 风险规则可配置化改造时 |
| monitor | audit | 监控与审计职责分化时 |
| crypto | datasource | 加解密逻辑复杂度增加时 |

---

# 6. 核心能力设计

## 6.1 数据源管理

- 系统库（PostgreSQL）与目标库（Oracle/MySQL）逻辑严格分离
- 系统库使用 SQLAlchemy AsyncSession 访问；目标库采用按需异步连接，不长期持有连接池
- 每个数据源包括：编码、名称、数据库类型、主机、端口、实例名、用户名、密文密码、环境标识（DEV/TEST/PROD）、启停状态、连接串等配置
- 连接超时默认 30 秒，执行超时默认 300 秒
- 按数据源维护独立 Semaphore 控制最大并发连接数（默认 5）

### 一期支持矩阵

| 能力 | Oracle 11g | MySQL 5.6 |
|---|---|---|
| SELECT 查询 | 支持（已验证） | 支持（已验证） |
| INSERT / UPDATE / DELETE | 支持（已验证） | 支持（已验证） |
| 多语句执行 | 需验证（一期 sqlparse 拆分处理） | 支持（已验证，nextset） |
| 存储过程调用 | 支持（已验证，IN/OUT/INOUT + REF CURSOR） | 支持（已验证，IN/OUT） |
| 事务控制 | 支持（已验证） | 支持（已验证） |
| CLOB/BLOB 大字段 | 支持（已验证，10k+） | 支持（已验证，10k+） |
| 字符集 | 支持（已验证，NVARCHAR2/NCLOB 中英文混合） | 支持（已验证，utf8mb4 中文+emoji） |

### 数据源环境权限约束

PROD 环境数据源仅 admin 角色可调用。developer 角色通过 MCP 调用 PROD 数据源时，系统返回"权限不足"错误。此为数据源级别限制，非 Skill 级别。

## 6.2 SQL 执行

支持两种执行方式：SQL 文件执行（接收本地 `.sql` 文件路径）和 SQL 文本执行（接收 SQL 文本直接执行）。

**安全约束：**

- 配置允许读取的根目录白名单
- 校验文件绝对路径是否在白名单内，禁止路径穿越和符号链接跟随
- 仅允许 `.sql` 扩展名，限制单文件大小（建议 10MB）

**执行控制：**

- 基于 `sqlparse` 按分号拆分多语句，解析失败的 SQL 统一标记为 HIGH 风险
- 支持异步执行模式，立即返回 execution_id，通过 `get_execution_status` 查询结果
- 状态值：PENDING / RUNNING / SUCCESS / FAILED / TIMEOUT
- 全局和按数据源两级并发限流

## 6.3 风险识别

SQL 执行前进行基础风险识别，采用 `sqlparse` + 正则 + 关键词匹配方式，不引入 SQL AST 解析器。

| 风险等级 | 典型操作 | 处理策略 |
|---|---|---|
| LOW | SELECT 查询 | 正常执行 |
| MEDIUM | INSERT、带 WHERE 的 DML | 正常执行 |
| HIGH | 无 WHERE 的 UPDATE/DELETE、存储过程调用、解析失败 | 用户二次确认 |
| CRITICAL | DROP、TRUNCATE、生产库 DDL | 强制二次确认 |

**生产库保护：** 生产库（env_code=PROD）数据源默认标记为"受保护"，受保护数据源的 DDL 和 DELETE WITHOUT WHERE 操作强制标记为 CRITICAL。

**局限性声明：** 风险识别为辅助参考，一期不覆盖 PL/SQL 块内部语义分析、嵌套子查询风险评估和存储过程内部操作识别。

## 6.4 安全设计

### 认证方案

Web 管理端采用 Session 方案（用户名密码登录，Session 存储于 PostgreSQL），选择 Session 而非 JWT 的原因：内部系统简单稳定，后台管理场景更易控制会话失效管理。登录页采用双栏布局：左侧为企业产品视觉区（产品名称、功能亮点），右侧为登录表单（含角色选择下拉框），底部版权说明。

### 权限模型

| 维度 | 说明 |
|---|---|
| 用户 | 系统用户 |
| 角色 | 用户分组 |
| Skill | 能力模块 |
| Tool | 具体操作 |
| 环境 | DEV / TEST / PROD |
| 数据源 | 具体数据库实例 |
| 页面功能点 | 菜单或按钮级控制 |

一期重点控制 Tool + 环境 + 数据源维度，页面功能点权限先做到菜单级基础控制。

### 一期双角色模型

| 角色 | 标识 | 权限范围 |
|---|---|---|
| 系统管理员 | admin | 全页面、全操作权限 |
| 开发人员 | developer | Skill 可新增（待审核，仅可见自己上传的 Skill），数据源仅查看/测试，审计仅自己记录，密码加密/用户管理页不可见 |

Skill 审核流程：developer 提交 → 状态"待审核" → admin 审核通过（启用）或驳回。仅 admin 可禁用/审核 Skill。

### 密码加解密

- 算法：AES-256-GCM（CBC 作为兼容备选）
- 密钥存储于独立 secret 文件，严禁入库明文保存或写死在代码中
- 解密操作默认受控，仅授权用户可执行，解密结果仅用于连接测试
- 每次加解密操作写入审计日志，审计日志中严禁记录明文密码

### 审计要求

以下操作必须审计，审计写入能力从第一阶段开始建设：

- 登录登出
- MCP Tool 调用
- SQL 执行
- 数据源新增修改删除
- 权限变更
- 密码加解密
- 系统参数修改

分期覆盖策略：Sprint 1 覆盖登录登出、数据源变更、加密操作审计；Sprint 2 覆盖 MCP 调用、SQL 执行、风险记录审计。

---

# 7. Web 管理端规划

## 7.1 一期页面范围

### 必须交付（8 个核心页面）

| 页面 | 优先级 | 理由 |
|---|---|---|
| 登录页 | P0 | 无认证则无法使用 |
| Skill 管理页 | P0 | Skill 注册信息查看、使用方式说明、启停管理、审核操作 |
| 数据源管理页 | P0 | MCP 调用的前置依赖 |
| 密码加密页 | P0 | 数据源配置的配套能力 |
| 审计日志页 | P0 | 合规要求 |
| 用户管理页 | P1 | 基本账号管理 |
| 个人设置页 | P1 | 用户自定义显示名称、邮件地址、修改密码；仅当前登录用户可修改自己的信息 |
| MCP 接入指南页 | P1 | Claude Code 配置步骤、JSON 配置示例、已注册 Skill/Tool 列表、环境要求、FAQ；所有用户可见 |

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

## 7.2 前端职责边界

**前端负责：** 页面交互、表单校验、数据展示、调用后端接口

**前端不负责：** SQL 真正执行、数据库密码真实加解密、风险识别逻辑、权限判定最终决策

---

# 8. 系统库与接口概览

## 8.1 系统库核心表

| 表名 | 说明 |
|---|---|
| `pmcp_user` | 用户信息 |
| `pmcp_role` | 角色信息 |
| `pmcp_user_role` | 用户角色关系 |
| `pmcp_permission` | 权限定义 |
| `pmcp_role_permission` | 角色权限关系 |
| `pmcp_api_key` | API Key 双存储（key_hash SHA-256 校验 + key_encrypted AES-GCM admin reveal） |
| `pmcp_datasource` | 数据源配置 |
| `pmcp_datasource_permission` | 数据源权限关系（表已建，业务逻辑二期实现） |
| `pmcp_audit_log` | 审计日志 |
| `pmcp_mcp_call_log` | MCP 调用日志 |
| `pmcp_crypto_operation_log` | 加解密操作日志 |
| `pmcp_system_config` | 系统参数配置（表已建，CRUD API 二期实现） |
| `pmcp_skill` | Skill 注册信息（编码、名称、描述、状态、注册方式、Tool 数量） |

共 13 张系统表。其中 `pmcp_datasource_permission` 和 `pmcp_system_config` 为一期已建未用资产（ORM 已定义，业务逻辑/API 留待二期实现）。

审计日志表采用通用字段设计，数据源和环境相关字段作为可选扩展字段，确保审计结构面向所有 Skill 通用。扩展数据使用 JSONB 类型，为二期新增 Skill 预留扩展空间。日志表数据量增长后采用 PostgreSQL 原生按时间分区。

## 8.2 接口概览

**Web 管理接口：** 登录接口、用户管理接口、角色管理接口、数据源管理接口、密码加解密接口、审计日志查询接口、MCP 状态查询接口、系统配置接口。

**MCP Tool 接口：**

| Tool | 输入 | 输出 |
|---|---|---|
| `execute_sql_file` | file_path, datasource_code, env_code, confirm_token（可选） | 执行结果结构 |
| `execute_sql_text` | sql_text, datasource_code, env_code, confirm_token（可选） | 执行结果结构 |
| `validate_sql` | sql_text, datasource_code | 风险等级与风险原因 |
| `list_datasources` | env_code（可选） | 数据源列表 |
| `get_execution_status` | execution_id | 状态与结果 |

---

# 9. 部署方案

## 9.1 部署形态

传统部署，不采用 Docker：

- Python 虚拟环境部署
- Gunicorn + Uvicorn Worker 运行 FastAPI Web 端
- MCP Server 由 Claude Code 以子进程方式启动（stdio 模式）
- 前端静态资源部署
- PostgreSQL 独立部署
- Nginx 反向代理
- systemd 托管 Web 进程

## 9.2 双进程部署

| 进程 | 启动方式 | 运行内容 |
|---|---|---|
| Web 进程 | systemd 托管（Platform-MCP.service） | Gunicorn + Uvicorn Worker |
| MCP Server 进程 | Claude Code 以子进程启动 | MCP Python SDK stdio 模式 |

两个进程共享应用代码目录和配置文件目录。

## 9.3 目录结构

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

## 9.4 运维支撑

- 应用日志按环境分类输出（运行、安全、审计、SQL 执行、MCP 调用、错误），生产环境按天滚动
- 一期采用轻量监控：进程存活、资源使用、错误率、MCP 调用量、执行耗时统计
- 测试范围覆盖：Web 功能、后端接口、MCP Tool 调用、数据源管理、密码加解密、审计日志、Oracle/MySQL 兼容验证、安全与压力测试

---

# 10. 兼容性风险与前置验证

## 10.1 关键兼容性风险

| 风险项 | 说明 | 应对策略 |
|---|---|---|
| Oracle 11g 驱动兼容 | oracledb thin 模式确认不支持 11g（DPY-3010），已切换至 thick 模式 + run_in_executor（POC 已验证通过） | 部署时需安装 Oracle Instant Client 64-bit |
| MySQL 5.6 驱动兼容 | aiomysql 14/14 子项全部通过（连接池、字符集、日期、存储过程、多语句、事务、认证） | 已确认可用 |
| Python 版本统一 | 全环境必须统一 Python 3.11.9 | 不允许开发与生产环境混用 3.10/3.12 |

## 10.2 启动前必须完成的验证

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

# 11. 迭代分期规划与验收标准

## 11.1 分期边界

| 维度 | 一期 | 二期 |
|---|---|---|
| 核心目标 | Database Skill 落地闭环 | Skill 扩展 + 能力增强 |
| Skill 数量 | 1（database） | 3-5（+ config / file / log） |
| 模块数量 | 7 | 按需拆分至 10-13 |
| Web 页面 | 8 个核心页面（含 Skill 管理、个人设置、MCP 接入指南） | 补全至 10 个 |
| 风险引擎 | sqlparse + 正则 + 关键词 | 配置化规则引擎 |
| 连接管理 | 按需连接 | 轻量连接池 |
| 限流 | Semaphore 基础并发控制 | 熔断器 |

## 11.2 一期实施阶段

| 阶段 | 内容 |
|---|---|
| 阶段零：技术兼容验证 | Python 3.11.9 + FastAPI 空项目验证、Oracle 11g thick 模式连接与执行验证（已完成，6/6 通过）、MySQL 5.6 连接与执行验证（已完成，14/14 通过）、PostgreSQL 系统库验证、MCP SDK stdio 模式 PoC |
| 阶段一：基础框架与系统库 | 后端工程骨架（7 模块）、系统库表结构初始化、用户/角色/权限基础模型、数据源配置模型、审计日志基础设施、通用响应与异常机制、配置管理 |
| 阶段二：MCP Core 与 Skill Registry | MCP Server 入口搭建、Tool 参数解析、Skill 接口定义与固化、Skill 注册与路由、MCP 调用日志、统一返回结构、基础并发限流 |
| 阶段三：Database Skill 闭环 | list_datasources、execute_sql_text、execute_sql_file（含路径安全校验）、validate_sql（风险识别）、高风险二次确认、事务控制、Oracle/MySQL 基础执行、生产库保护标记 |
| 阶段四：Web 管理端 | 登录页（双栏布局）、Skill 管理页、数据源管理页、密码加密页、审计日志页、用户管理页、个人设置页、MCP 接入指南页 |
| 阶段五：测试与上线 | Oracle/MySQL 兼容测试、权限隔离测试、审计完整性测试、SQL 文件执行边界测试、部署启停与日志检查 |

## 11.3 一期验收标准

### 功能验收

- Claude Code 可通过 MCP 调用 Database Skill
- 可执行 SQL 文本和受控范围内的本地 `.sql` 文件
- 可查询可用数据源
- 可查看审计日志
- 可配置数据源及密文密码
- 可按用户/角色/数据源/环境控制访问
- 高风险操作触发二次确认

### 兼容性验收

- Oracle 11g 基础连接和 SQL 执行通过
- MySQL 5.6 基础连接和 SQL 执行通过
- PostgreSQL 系统库访问稳定
- 目标数据库连接失败时不影响系统库和管理端

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

## 11.4 二期规划方向

### Skill 扩展

按优先级逐步扩展：`config`（低风险，验证框架扩展性）→ `file` → `log` → `deploy`（高风险，独立安全评审）→ `shell`（高风险，独立安全评审）

### 架构增强

- 数据库方言抽象层（DatabaseDialect），新增数据库支持只需实现新 Dialect
- Skill 热插拔机制，支持动态加载与卸载
- Capability 抽象层，公共服务跨 Skill 复用
- 配置化风险规则引擎，新增规则不改代码
- 轻量连接池，高频数据源启用独立连接池
- 熔断器，按数据源连续失败自动熔断
- 流式响应（MCP SSE）
- 多环境隔离增强（审批流、IP 白名单、操作窗口控制）

### 数据库能力增强

- Oracle 存储过程高级支持（OUT/REF CURSOR 已在一期 POC 验证通过，二期封装优化）
- MySQL 多语句执行增强（nextset 已在一期 POC 验证通过，二期结果集映射优化）
- SQL 执行计划辅助查看

---

# 12. 非功能性要求

| 维度 | 要求 |
|---|---|
| 可用性 | 服务支持稳定持续运行，异常请求不影响整体服务可用性 |
| 可维护性 | 模块职责清晰，日志可定位，配置可管理，错误信息可追踪 |
| 安全性 | 密码密文存储，解密操作受控，权限最小化，全链路审计 |
| 可扩展性 | MCP 统一入口不绑定单一数据库能力，Skill 可逐步扩展，接口和日志结构可复用 |

---

# 13. 开源合规结论

项目全部依赖均采用 MIT、BSD、Apache License 2.0 或同等宽松协议，无传染性风险。

**重点关注项：**

| 组件 | 说明 |
|---|---|
| oracledb 2.4.1 | 已确认使用 thick 模式，需引入 Oracle Instant Client。确认 Oracle Instant Client 许可证条款覆盖内部使用 |

---

# 14. 架构总结

Platform-MCP 首期正式技术路线：

| 维度 | 选型 |
|---|---|
| 后端 | Python 3.11.9 + FastAPI |
| 前端 | Vue 3 + Vite + Element Plus |
| 系统库 | PostgreSQL 16.4（asyncpg） |
| 目标数据库连接 | oracledb thick 模式 + run_in_executor（Oracle 11g）+ aiomysql（MySQL 5.6） |
| 部署方式 | 虚拟环境 + systemd + Nginx |
| 扩展模式 | MCP 统一入口 + Skill 插件式扩展 |
| 架构形态 | 双入口（FastAPI Web + MCP Server stdio） |

**启动前必须完成项：**

1. ~~Oracle 11g + oracledb async thin 模式全量验证~~ **已完成** — thin 模式不支持 11g（DPY-3010），已切换至 thick 模式 + run_in_executor，6/6 项通过
2. ~~MySQL 5.6 + aiomysql 兼容性验证~~ **已完成** — 14/14 子项全部通过
3. Claude Code + MCP Python SDK stdio 模式最小化 PoC
4. 统一异步策略验证（asyncpg + aiomysql + oracledb thick + run_in_executor）

**部署新增要求：** Oracle 目标库所在服务器需预装 Oracle Instant Client 64-bit。
