# Platform-MCP 技术架构说明文档

- **适用对象**：架构师、后端开发、前端开发、运维工程师、测试工程师
- **文档用途**：用于项目启动阶段的 IT 内部宣讲、技术评审、系统设计与实施基线对齐

---

## 版本更新日志

| 版本 | 日期 | 修订性质 | 修订摘要 | 修改人 |
|---|---|---|---|---|
| V1.0 | 2026-05-28 | 新建 | 初版技术架构说明文档，整合架构设计与三份技术评审共识，确立项目启动技术基线 | castle.zhang |
| V1.1 | 2026-05-29 | 修订 | 新增 Skill 管理页与个人设置页；密码加解密页更名为密码加密页；补充 Skill 注册方式说明；登录页改为双栏布局；补充 sys_skill 系统表 | castle.zhang |

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

**与传统 SQL 平台的区别：** 本系统核心执行入口为 MCP，Web 端主要承担管理、审计和运维支撑职责，不作为主要 SQL 编写执行入口。

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

- **Java 单体模块化架构**
- **Web 管理端 + MCP Server + Skill 层 + PostgreSQL 系统库**
- **JDBC 连接目标数据库**
- **Jar 包部署 + systemd + Nginx**

## 4.2 逻辑架构分层

### 4.2.1 调用侧

- Claude Code（通过 MCP 协议调用）
- Web 管理用户（通过浏览器访问）
- 运维管理员

### 4.2.2 接入层

- MCP Tool 接口
- Web REST API

### 4.2.3 业务服务层

- 权限认证
- MCP 请求分发与 Skill 路由
- 数据源管理
- 密码加解密
- SQL 执行与风险识别
- 审计日志与状态监控

### 4.2.4 数据层

- PostgreSQL 系统库（系统管理数据）
- Oracle 11g / MySQL 5.6（业务执行目标库）

## 4.3 核心使用场景

### 场景 A：Claude Code 接入

Claude Code 通过添加 MCP Server 配置接入本系统，MCP Server 作为能力提供方响应 Tool 调用请求。

### 场景 B：指定环境执行 SQL 脚本

用户在本地持有 SQL 脚本，通过 Claude Code 提示"执行数据库是测试环境"，系统自动匹配对应环境的数据源，读取 SQL 文件内容，执行 SQL 并审计过程及结果。

**调用链：**
1. Claude Code 调用 MCP Tool，传入文件路径、目标环境等参数
2. MCP Server 接收请求，路由至 Database Skill
3. 读取本地 `.sql` 文件内容，校验文件路径安全性
4. 执行 SQL 风险识别
5. 根据数据源配置建立 JDBC 连接
6. 执行 SQL，返回执行结果
7. 写入 MCP 调用日志和审计日志

### 场景 C：高风险操作二次确认

当 SQL 执行触发高风险标识（INSERT、DELETE、UPDATE、存储过程调用等），系统返回风险提示，要求用户二次确认后方可继续执行。

**调用链：**
1. 用户发起 SQL 执行请求
2. 风险引擎识别为高风险操作（如 DELETE 无 WHERE、DROP、TRUNCATE、存储过程调用）
3. 系统返回风险等级、风险原因，等待用户确认
4. 用户确认后继续执行，或用户取消放弃执行
5. 确认/取消操作均写入审计日志

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
| JDK | 17.0.11 LTS | 长期支持版本，兼顾稳定性与生态成熟度 |
| Spring Boot | 3.2.8 | 长期稳定企业级版本 |
| Spring Framework | 6.1.12 | 随 Spring Boot 3.2.8 配套 |
| Spring Security | 6.2.5 | 权限与认证控制 |
| Spring Session | 6.2.5 | Session 持久化至 PostgreSQL |
| MyBatis Spring Boot Starter | 3.0.3 | 系统库访问与管理数据持久化 |
| HikariCP | 5.0.1 | 系统库连接池 |
| PostgreSQL JDBC Driver | 42.7.3 | PostgreSQL 系统库连接驱动 |
| MySQL Connector/J | 5.1.49 | 针对 MySQL 5.6 的稳定兼容版本 |
| Oracle JDBC Driver | ojdbc8 19.22.0.0 | 需根据 JDK 17 + Oracle 11g 实际适配验证 |
| Jackson | 2.17.2 | JSON 序列化反序列化 |
| SLF4J | 2.0.13 | 日志门面 |
| Logback | 1.5.6 | 日志实现 |
| Apache Commons Lang3 | 3.14.0 | 常用工具库 |
| Apache Commons IO | 2.16.1 | 文件处理工具 |
| Hutool | 5.8.31 | 辅助工具类，可选 |
| Lombok | 1.18.34 | 简化 Java 开发，可选但建议规范使用 |
| Maven | 3.9.14 | 构建工具 |

## 5.3 前端技术栈

| 组件 | 版本 | 说明 |
|---|---|---|
| Node.js | 20.15.1 LTS | 前端构建运行环境 |
| npm | 10.7.0 | 包管理工具 |
| Vue | 3.4.38 | 稳定主流版本 |
| Vite | 5.4.2 | 构建工具 |
| TypeScript | 5.5.4 | 类型约束 |
| Vue Router | 4.4.3 | 路由管理 |
| Pinia | 2.2.2 | 状态管理 |
| Element Plus | 2.8.1 | UI 组件库 |
| Axios | 1.7.4 | HTTP 请求 |
| ECharts | 5.5.1 | 状态监控图表，可选 |
| ESLint | 9.9.1 | 代码规范 |
| Prettier | 3.3.3 | 代码格式化 |

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
| JUnit Jupiter | 5.10.3 | 单元测试 |
| Mockito | 5.12.0 | Mock 测试 |
| AssertJ | 3.26.3 | 断言增强 |
| Spring Boot Test | 3.2.8 | 集成测试 |
| Postman | 11.x | 接口测试 |
| Apache JMeter | 5.6.3 | 压测工具 |
| SonarQube | 10.6 | 代码质量检查，可选 |

---

# 6. 版本兼容性与前置验证

## 6.1 Spring Boot 版本策略

**正式目标：** Spring Boot 3.2.8 + JDK 17

**回退策略：** 若 Oracle JDBC 驱动联调验证存在不可接受风险，回退至 Spring Boot 2.7.18 + Spring Security 5.8.x，保持 JDK 17 或降至 JDK 11。

**锁定原则：** 项目启动前通过 PoC 验证后锁定单一路线，不保留双版本并行开发空间。若选择 3.2.8 路线则删除回退策略描述；若选择 2.7.18 路线则不再保留"后续可能升级"的模糊空间。

## 6.2 Oracle 11g 驱动兼容性

建议组合：JDK 17 + `ojdbc8 19.22.0.0`

**关注点：** ojdbc8 19.x 官方认证支持 Oracle 19c/21c，对 Oracle 11g 的支持为"尽力兼容"而非"官方认证"。项目正式启动前需完成以下专项验证：

| 验证项 | 验证内容 |
|---|---|
| 连接建立 | Basic/TNS 连接方式 |
| 字符集 | AL32UTF8 / ZHS16GBK 场景 |
| 日期类型 | DATE / TIMESTAMP 读写 |
| 存储过程 | IN/OUT/INOUT 参数、REF CURSOR |
| CLOB/BLOB | 大字段读写 |
| 事务控制 | autocommit=false + commit/rollback |

## 6.3 MySQL 5.6 驱动兼容性

建议版本：`mysql-connector-java 5.1.49`

选择理由：对 MySQL 5.6 兼容更稳，避免 8.x 驱动在旧认证或时区兼容上引入额外问题。

**重点验证：**

- 连接参数字符集配置（`useUnicode=true&characterEncoding=UTF-8` 作为 JDBC URL 强制参数）
- 时区参数
- 多语句执行开关
- 事务隔离与提交行为

## 6.4 HikariCP 连接池注意项

HikariCP 5.0.1 仅用于系统库（PostgreSQL）连接池。目标数据库采用按需建立连接策略，不长期持有连接池。

MySQL 5.6 场景建议显式设置：`connectionTimeout=30s`、`idleTimeout=600s`、`maxLifetime=7200s`。

---

# 7. 模块化架构设计

## 7.1 一期模块清单

一期采用精简模块方案，共 7 个模块：

| 模块 | 包含能力 | 说明 |
|---|---|---|
| `Platform-MCP-web-admin` | Web REST API | 前端对接接口与页面数据聚合输出 |
| `Platform-MCP-auth` | 认证鉴权 | 登录认证、用户/角色/权限管理 |
| `Platform-MCP-datasource` | 数据源管理 + 密码加解密 | 数据源配置、JDBC 连接参数、密码加密解密 |
| `Platform-MCP-mcp-core` | MCP 接入 + Skill 接口 + 注册路由 + Skill 管理 | MCP 协议接入、Skill 统一接口定义、Skill 注册与路由分发、Skill 管理与生命周期 |
| `Platform-MCP-skill-database` | 数据库 Skill + SQL 执行器 + 风险引擎 | 数据库 Skill 业务逻辑、SQL 执行、风险识别 |
| `Platform-MCP-audit` | 审计 + 状态监控 | 审计日志记录、MCP 调用状态统计、服务运行状态输出 |
| `Platform-MCP-common` | 通用工具 | 通用异常、响应模型、枚举、工具类、常量 |

## 7.2 模块职责详述

### 7.2.1 Platform-MCP-web-admin

- 提供 Web 管理 REST API
- 前端页面数据聚合输出
- 对接 auth、datasource、audit 等模块

### 7.2.2 Platform-MCP-auth

- 用户名密码登录认证
- 用户、角色、权限管理
- 资源访问鉴权
- Session 持久化至 PostgreSQL（Spring Session JDBC）

### 7.2.3 Platform-MCP-datasource

- 数据源信息管理（增删改查、启停）
- 环境管理（DEV/TEST/PROD）
- JDBC 连接参数管理
- 数据源权限控制
- 密码加密与解密
- 密钥读取与密码操作审计

### 7.2.4 Platform-MCP-mcp-core

- MCP 协议接入与 Tool 参数解析
- Skill 统一接口标准定义
- Skill 注册、发现与路由分发
- 调用链路上下文封装
- 统一响应结构
- MCP 调用并发限流
- Skill 管理与生命周期（查看、启停）
- Skill 注册方式支持：
  - 页面新增：通过 Web 管理端表单提交 Skill 信息
  - 源码上传解析：上传 .jar / .py 源码文件，系统自动解析 Skill 信息（编码、名称、Tool 列表），管理员确认后完成注册
  - 注解注册：通过代码注解在编译期静态注册

### 7.2.5 Platform-MCP-skill-database

- 数据库 Skill 业务逻辑
- Tool 能力落地（execute_sql_file、execute_sql_text、validate_sql、list_datasources、get_execution_status）
- SQL 执行（多语句分段、查询结果映射、存储过程调用）
- SQL 风险识别（语句类型、高危标记、解析失败记录）

### 7.2.6 Platform-MCP-audit

- 审计日志记录（登录登出、MCP 调用、SQL 执行、配置变更、安全操作）
- MCP 调用状态统计
- 服务运行状态输出
- 概览统计数据输出

### 7.2.7 Platform-MCP-common

- 通用异常与错误码
- 统一响应模型
- 公共枚举
- 工具类与常量

## 7.3 二期模块拆分预案

当第二个 Skill 落地时，按需从现有模块提取：

| 拆分项 | 来源 | 触发条件 |
|---|---|---|
| `Platform-MCP-skill-api` | mcp-core | 第二个 Skill 落地时提取 Skill 统一接口为独立模块 |
| `Platform-MCP-skill-registry` | mcp-core | Skill 注册路由逻辑复杂度增加时独立 |
| `Platform-MCP-sql-executor` | skill-database | 引入 DatabaseDialect 方言抽象层时独立 |
| `Platform-MCP-risk-engine` | skill-database | 风险规则可配置化改造时独立 |
| `Platform-MCP-monitor` | audit | 监控指标与审计日志职责分化时独立 |
| `Platform-MCP-crypto` | datasource | 加解密逻辑复杂度增加时独立 |

---

# 8. MCP 能力架构

## 8.1 设计原则

MCP 层按"统一入口 + Skill 扩展"设计：

- MCP Server 负责协议接入
- Skill 负责能力实现
- Registry 负责路由分发
- Audit 负责全链路记录

**关键约束：** Database Skill 相关逻辑不得侵入 mcp-core。mcp-core 只处理协议接入、参数标准化、上下文封装和响应封装。

## 8.2 一期 Skill 规划

一期仅建设 `database` Skill。

二期预留：`file`、`log`、`config`、`deploy`、`shell`。

## 8.3 一期 Tool 规划

Database Skill 提供：

| Tool | 说明 |
|---|---|
| `execute_sql_file` | 接收文件路径，读取本地 SQL 文件并执行 |
| `execute_sql_text` | 接收 SQL 文本直接执行 |
| `validate_sql` | 校验 SQL 语法并返回风险等级 |
| `list_datasources` | 列出当前用户可访问的数据源 |
| `get_execution_status` | 查询异步执行任务的状态 |

## 8.4 Skill 统一接口

每个 Skill 实现需统一具备以下方法：

| 方法 | 说明 |
|---|---|
| `skillName()` | 返回 Skill 名称 |
| `listTools()` | 返回该 Skill 提供的 Tool 列表 |
| `validate()` | 校验 Tool 输入参数 |
| `execute()` | 执行 Tool 逻辑 |
| `support()` | 判断是否支持指定 Tool |

二期扩展时预留生命周期方法：`initialize()`、`destroy()`。

## 8.5 统一上下文信息

MCP 调用上下文统一封装：

| 字段 | 说明 |
|---|---|
| traceId | 全链路追踪标识 |
| requestId | 请求唯一标识 |
| operator | 操作人 |
| skillName | Skill 名称 |
| toolName | Tool 名称 |
| targetDatasource | 目标数据源编码 |
| targetEnv | 目标环境标识 |
| requestTime | 请求时间 |
| riskLevel | 风险等级 |
| executionStatus | 执行状态 |

二期扩展时，数据库专有字段（datasource_code、env_code）作为可选扩展字段，不应成为所有 Skill 的强制字段。

---

# 9. 数据源与目标数据库设计

## 9.1 系统库与目标库分离原则

- PostgreSQL 用于系统管理数据
- Oracle/MySQL 用于业务执行目标库
- 系统库访问与目标库访问逻辑严格分离
- 系统库使用 Spring 管理数据源（HikariCP）
- 目标库采用动态 JDBC 连接工厂，按需建立连接

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
| 驱动类名 | JDBC 驱动类 |
| JDBC URL | 完整连接 URL |
| 备注信息 | 补充说明 |

## 9.3 目标库连接策略

- 每次执行创建连接 → 执行 → 关闭（try-with-resources）
- 全局配置 `connection.timeout`（默认 30s）和 `query.timeout`（默认 300s）
- 按数据源维护 Semaphore 控制最大并发连接数（默认 5）
- 不为所有目标数据库长期持有连接池

## 9.4 一期支持矩阵

| 能力 | Oracle 11g | MySQL 5.6 |
|---|---|---|
| SELECT 查询 | 支持 | 支持 |
| INSERT / UPDATE / DELETE | 支持 | 支持 |
| 多语句执行 | 需验证 | 支持 |
| 存储过程调用 | 支持 | 需验证 |
| 事务控制 | 支持 | 支持 |

---

# 10. SQL 执行设计

## 10.1 执行方式

| 方式 | 说明 |
|---|---|
| SQL 文件执行 | 接收文件路径，读取本地 `.sql` 文件执行 |
| SQL 文本执行 | 接收 SQL 文本直接执行 |

## 10.2 文件执行流程

1. 接收文件路径参数
2. **路径安全校验**（白名单目录、禁止路径穿越、禁止符号链接跟随、限制文件扩展名为 `.sql`、限制文件大小）
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
- 校验解析后的绝对路径是否在白名单目录内
- 禁止符号链接跟随
- 仅允许 `.sql` 扩展名
- 限制单文件大小，防止内存溢出

## 10.4 多语句处理

一期采用简单稳定策略：

- 按分号拆分，处理注释和字符串常量中的分号
- Oracle PL/SQL 块建议单语句执行或采用明确分隔符规范
- 一期不承诺完全通用 SQL 脚本解析能力
- 解析失败的 SQL 统一标记为 HIGH 风险

## 10.5 异步执行与超时控制

- SQL 执行设置超时上限（默认 5 分钟），超时自动终止
- `execute_sql_file/text` 可异步执行，立即返回 `executionId`
- 结果通过 `get_execution_status` 获取

## 10.6 返回结果结构

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

一期采用正则 + 关键词匹配，不引入 SQL AST 解析器：

| 识别项 | 说明 |
|---|---|
| 语句类型识别 | DDL / DML / DCL 分类 |
| DDL 检测 | CREATE、ALTER、DROP 等 |
| 高危操作标记 | DROP、TRUNCATE |
| 全表操作检测 | DELETE / UPDATE 无 WHERE |
| 解析失败记录 | 标记为 HIGH 风险 |

## 11.3 风险等级

| 等级 | 说明 | 处理策略 |
|---|---|---|
| LOW | SELECT 查询等低风险操作 | 正常执行 |
| MEDIUM | INSERT、带 WHERE 的 DML | 正常执行 |
| HIGH | 无 WHERE 的 UPDATE/DELETE、解析失败 | 提示用户二次确认 |
| CRITICAL | DROP、TRUNCATE、生产库 DDL | 强制二次确认 |

## 11.4 局限性声明

风险识别为辅助参考，不保证 100% 准确。一期不覆盖 PL/SQL 块内部语义分析、嵌套子查询风险、存储过程内部操作识别等复杂场景。

## 11.5 生产库保护

- 生产库（env_code=PROD）数据源默认标记为"受保护"
- 受保护数据源的 DDL 和 DELETE WITHOUT WHERE 操作强制标记为 CRITICAL
- 风险规则可通过 `sys_system_config` 表配置开关，无需改代码

---

# 12. 安全设计

## 12.1 认证方案

Web 管理端采用 Session 方案：

- 用户名密码登录
- Session 持久化至 PostgreSQL（Spring Session JDBC），避免进程重启导致会话失效
- Session 超时策略建议不超过 30 分钟

选择 Session 而非 JWT 的原因：内部系统简单稳定，后台管理场景更易控制，更适合权限收敛和会话失效管理。

登录页采用双栏布局：左侧为企业产品视觉区（产品名称、功能亮点），右侧为登录表单，底部版权说明。

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

## 12.3 密码加解密方案

- 算法：AES-256
- 模式：CBC 或 GCM
- IV：随机生成
- 输出：Base64 编码

**密钥管理：**

- 存储于独立 secret 文件（`crypto-secret.key`）
- 严禁入库明文保存
- 严禁写死在代码中
- secret 文件权限收敛

## 12.4 审计要求

以下操作必须审计，审计写入能力从第一阶段开始建设：

- 登录登出
- MCP Tool 调用
- SQL 执行
- 数据源新增修改删除
- 权限变更
- 密码加密
- 密码解密
- 系统参数修改

---

# 13. Web 前端设计基线

## 13.1 页面范围与优先级

### 一期必须交付（7 个核心页面）

| 页面 | 优先级 | 理由 |
|---|---|---|
| 登录页 | P0 | 无认证则无法使用 |
| Skill 管理页 | P0 | Skill 注册信息查看、使用方式说明、启停管理 |
| 数据源管理页 | P0 | MCP 调用的前置依赖 |
| 密码加密页 | P0 | 数据源配置的配套能力 |
| 审计日志页 | P0 | 合规要求 |
| 用户管理页 | P1 | 基本账号管理 |
| 个人设置页 | P1 | 用户自定义显示名称、邮件地址、修改密码 |

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

一期在 `package.json` 中使用精确版本号（不用 `^`），锁定当前版本组合，避免开发期间版本漂移。

---

# 14. 系统库设计基线

## 14.1 核心表清单

- `sys_user` — 用户信息
- `sys_role` — 角色信息
- `sys_user_role` — 用户角色关系
- `sys_permission` — 权限定义
- `sys_role_permission` — 角色权限关系
- `sys_datasource` — 数据源配置
- `sys_datasource_permission` — 数据源权限关系
- `sys_audit_log` — 审计日志
- `sys_mcp_call_log` — MCP 调用日志
- `sys_crypto_operation_log` — 加解密操作日志
- `sys_system_config` — 系统参数配置
- `sys_skill` — Skill 注册信息（编码、名称、描述、状态、注册方式、Tool 数量）

## 14.2 审计日志表核心字段

| 字段 | 说明 |
|---|---|
| id | 主键 |
| trace_id | 全链路追踪标识 |
| request_id | 请求唯一标识 |
| operator | 操作人 |
| skill_name | Skill 名称 |
| tool_name | Tool 名称 |
| datasource_code | 数据源编码（可选） |
| env_code | 环境标识（可选） |
| request_summary | 请求摘要 |
| result_status | 结果状态 |
| risk_level | 风险等级 |
| error_message | 错误信息 |
| start_time | 开始时间 |
| end_time | 结束时间 |
| duration_ms | 耗时毫秒 |
| created_at | 创建时间 |

**设计原则：** 审计主表保留通用字段，数据库专有字段（datasource_code、env_code）作为可选字段，确保审计结构面向所有 Skill 通用。

## 14.3 日志表增长策略

`sys_audit_log` 和 `sys_mcp_call_log` 数据量增长后，考虑按时间分区（PostgreSQL 原生分区表）。

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

- `execute_sql_file`
- `execute_sql_text`
- `validate_sql`
- `list_datasources`
- `get_execution_status`

## 15.3 统一响应格式

| 字段 | 类型 | 说明 |
|---|---|---|
| code | int | 状态码 |
| message | string | 状态描述 |
| data | object | 业务数据 |
| traceId | string | 追踪标识 |
| timestamp | long | 时间戳 |

---

# 16. 日志与监控设计

## 16.1 应用日志分类

| 类型 | 说明 |
|---|---|
| 应用运行日志 | 服务启动、停止、异常 |
| 安全日志 | 认证失败、权限拒绝 |
| 审计日志 | 关键操作记录（入库） |
| SQL 执行日志 | SQL 语句与执行结果 |
| MCP 调用日志 | MCP 请求与响应 |
| 错误日志 | 异常堆栈 |

## 16.2 日志输出

- 开发环境：控制台输出
- 测试/生产环境：文件输出，按天滚动
- 保留周期按运维规范设置

## 16.3 一期监控

采用轻量监控：

- 应用存活检查
- JVM 内存监控
- 线程数监控
- 错误率监控
- MCP 调用量统计
- 执行耗时统计

---

# 17. 部署与运维基线

## 17.1 部署形态

传统部署，不采用 Docker：

- 后端 Jar 部署
- 前端静态资源部署
- PostgreSQL 独立部署
- Nginx 反向代理
- systemd 托管

## 17.2 目录结构

```
/opt/Platform-MCP/
├── app/           # 后端 Jar 包
├── config/        # 配置文件
├── secret/        # 密钥文件
├── logs/          # 日志文件
├── scripts/       # 运维脚本
└── sql-scripts/   # SQL 脚本文件（白名单目录）
```

## 17.3 配置文件分离

| 文件 | 说明 |
|---|---|
| `application.yml` | 主配置 |
| `application-dev.yml` | 开发环境配置 |
| `application-test.yml` | 测试环境配置 |
| `application-prod.yml` | 生产环境配置 |
| `datasource-template.yml` | 数据源配置模板 |
| `crypto-secret.key` | 加密密钥 |

## 17.4 systemd 服务

服务名：`Platform-MCP.service`

## 17.5 Nginx 职责

- 托管前端静态资源
- 反向代理后端接口
- 路由转发
- 访问日志记录

## 17.6 运维注意事项

- Linux 发行版与 JDK 安装方式统一
- systemd 启停、重启、日志路径标准化
- secret 文件权限收敛（仅应用运行用户可读）
- Nginx 访问日志与应用 traceId 的关联

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
| Skill 数量 | 1（database） | 3-5（+ file / log / config） |
| 模块数量 | 7 | 按需拆分至 10-13 |
| Web 页面 | 5 个核心页面 | 7 个核心页面（+Skill 管理、个人设置） | 补全至 9 个 |
| 风险引擎 | 正则 + 关键词 | 配置化规则引擎 |
| 数据库方言 | Oracle + MySQL 基础支持 | DatabaseDialect 方言抽象层 |
| Skill 注册 | 编译期静态注册 | SPI 插件式动态注册（热插拔） |
| 连接管理 | 按需连接 | 轻量连接池（每数据源 HikariCP） |
| 限流 | 基础并发控制 | Resilience4j 熔断器 |

## 19.2 一期实施阶段

### 阶段一：技术兼容验证

- JDK + Spring Boot + Oracle 11g 驱动组合验证
- JDK + Spring Boot + MySQL 5.6 驱动组合验证
- PostgreSQL 系统库连接验证
- MCP 协议与 Claude Code 对接方式验证
- MCP 协议最小化 PoC（一个 Tool 全链路跑通）

### 阶段二：基础框架与系统库

- 后端工程骨架（7 模块结构）
- 系统库表结构初始化
- 用户、角色、权限基础模型
- 数据源配置模型
- **审计日志基础设施**（AuditLogger 接口 + sys_audit_log 写入能力）
- 通用响应、异常、traceId 机制

### 阶段三：MCP Core 与 Skill Registry

- MCP 请求接入
- Tool 参数解析
- Skill 接口定义与固化
- Skill 注册与路由
- MCP 调用日志
- 统一返回结构
- 基础并发限流

### 阶段四：Database Skill 闭环

- list_datasources
- execute_sql_text
- execute_sql_file（含路径安全校验）
- validate_sql（正则 + 关键词风险识别）
- 高风险操作二次确认机制
- 基础事务控制
- Oracle / MySQL 基础执行支持
- 生产库受保护标记

### 阶段五：Web 管理端

- 登录页（双栏布局：左侧产品视觉区 + 右侧登录表单）
- Skill 管理页（Skill 列表、使用方式、启停操作、新增入口）
- 数据源管理页
- 密码加密页
- 审计日志页
- 用户管理页
- 个人设置页（显示名称、邮件地址、修改密码，通过头像下拉菜单进入）

### 阶段六：测试与上线

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
- 高风险操作（INSERT/DELETE/UPDATE/存储过程调用等）触发二次确认

### 兼容性验收

- Oracle 11g 基础连接和 SQL 执行通过
- MySQL 5.6 基础连接和 SQL 执行通过
- PostgreSQL 系统库访问稳定
- 目标数据库连接失败时不影响系统库和管理端
- 驱动版本、JDK 版本、Spring Boot 版本形成最终固化清单

### 安全与审计验收

- 目标数据库密码不明文入库
- secret 文件不写入代码
- 解密操作受权限控制
- SQL 执行全链路可追踪
- MCP 调用、配置变更、权限变更均有审计记录

### 运维验收

- 支持 Jar 启动
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
| SPI 插件机制 | Skill 作为独立 JAR 放入指定目录后自动注册，实现热插拔 |
| Capability 抽象层 | 执行器、风险识别、审计等公共服务可跨 Skill 复用 |
| 分层上下文 | 基础上下文（所有 Skill 共享）+ Skill 专用上下文（扩展字段） |
| 配置化规则引擎 | 风险规则按数据库类型配置，新增规则不改代码 |
| 轻量连接池 | 高频调用数据源启用独立 HikariCP 实例 |
| Resilience4j 熔断 | 按数据源的熔断器，连续失败自动熔断 |
| 流式响应 | MCP SSE 流式返回执行进度 |
| 多环境隔离增强 | 操作审批流、IP 白名单校验、操作窗口控制 |

### Web 页面补全

补全系统概览页、角色权限管理页、MCP 调用状态页、系统配置页。

### 数据库能力增强

- Oracle 存储过程高级支持（OUT 参数、REF CURSOR）
- MySQL 多语句执行增强
- SQL 执行计划辅助查看
- 高危 SQL 二次确认或审批机制

---

# 20. 开源协议与合规说明

## 20.1 后端依赖协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| OpenJDK | 17.0.11 | GPLv2 with Classpath Exception | Classpath Exception 允许商业使用 |
| Spring Boot | 3.2.8 | Apache License 2.0 | 无传染性，可商业使用 |
| Spring Framework | 6.1.12 | Apache License 2.0 | 无传染性 |
| Spring Security | 6.2.5 | Apache License 2.0 | 无传染性 |
| Spring Session | 6.2.5 | Apache License 2.0 | 无传染性 |
| MyBatis Spring Boot Starter | 3.0.3 | Apache License 2.0 | 无传染性 |
| HikariCP | 5.0.1 | Apache License 2.0 | 无传染性 |
| PostgreSQL JDBC Driver | 42.7.3 | BSD 2-Clause License | 无传染性 |
| MySQL Connector/J | 5.1.49 | GPLv2 + FOSS Exception | 仅当与 GPL 兼容的开源软件一起分发时适用 FOSS Exception；内部使用需确认 Oracle 商业许可或适用 FOSS Exception 条款 |
| Oracle JDBC (ojdbc8) | 19.22.0.0 | Oracle Technology Network License (OTN) | 需持有有效的 Oracle 许可证，生产环境使用需遵守 OTN 协议条款 |
| Jackson | 2.17.2 | Apache License 2.0 | 无传染性 |
| SLF4J | 2.0.13 | MIT License | 无传染性 |
| Logback | 1.5.6 | EPL 1.0 / LGPL 2.1 | EPL 可商业使用 |
| Apache Commons Lang3 | 3.14.0 | Apache License 2.0 | 无传染性 |
| Apache Commons IO | 2.16.1 | Apache License 2.0 | 无传染性 |
| Hutool | 5.8.31 | Mulan PSL v2 | 中国开源协议，可商业使用 |
| Lombok | 1.18.34 | MIT License | 无传染性 |

## 20.2 前端依赖协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| Vue | 3.4.38 | MIT License | 无传染性 |
| Vite | 5.4.2 | MIT License | 无传染性 |
| TypeScript | 5.5.4 | Apache License 2.0 | 无传染性 |
| Vue Router | 4.4.3 | MIT License | 无传染性 |
| Pinia | 2.2.2 | MIT License | 无传染性 |
| Element Plus | 2.8.1 | MIT License | 无传染性 |
| Axios | 1.7.4 | MIT License | 无传染性 |
| ECharts | 5.5.1 | Apache License 2.0 | 无传染性 |
| ESLint | 9.9.1 | MIT License | 无传染性 |
| Prettier | 3.3.3 | MIT License | 无传染性 |

## 20.3 数据库与中间件协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|---|
| PostgreSQL | 16.4 | PostgreSQL License | 类 BSD 协议，无传染性 |
| Nginx | 1.26.1 | BSD 2-Clause License | 无传染性 |

## 20.4 测试工具协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| JUnit Jupiter | 5.10.3 | EPL 2.0 | 可商业使用 |
| Mockito | 5.12.0 | MIT License | 无传染性 |
| AssertJ | 3.26.3 | Apache License 2.0 | 无传染性 |
| Apache JMeter | 5.6.3 | Apache License 2.0 | 无传染性 |

## 20.5 构建工具协议

| 组件 | 版本 | 开源协议 | 合规要求 |
|---|---|---|---|
| Maven | 3.9.14 | Apache License 2.0 | 无传染性 |
| Node.js | 20.15.1 | MIT License (OpenJS Foundation) | 无传染性 |
| npm | 10.7.0 | Artistic License 2.0 | 可商业使用 |

## 20.6 重点合规关注

| 风险项 | 说明 | 建议 |
|---|---|---|
| Oracle JDBC (ojdbc8) | OTN License 限制 | 确认持有有效的 Oracle 数据库许可证，ojdbc8 随 Oracle 数据库授权分发 |
| MySQL Connector/J 5.1.49 | GPLv2 + FOSS Exception | 内部使用不构成分发，合规风险低；若作为产品对外分发需评估 GPL 传染性或购买商业许可 |

---

# 21. 非功能性要求

| 维度 | 要求 |
|---|---|
| 可用性 | 服务支持稳定持续运行，异常请求不影响整体服务可用性 |
| 可维护性 | 模块职责清晰，日志可定位，配置可管理，错误信息可追踪 |
| 安全性 | 密码密文存储，解密操作受控，权限最小化，全链路审计 |
| 可扩展性 | MCP 统一入口不绑定单一数据库能力，Skill 可逐步扩展，接口和日志结构可复用 |

---

# 22. 技术结论

Platform-MCP 首期正式技术路线：

| 维度 | 选型 |
|---|---|
| 后端 | JDK 17.0.11 + Spring Boot 3.2.8 |
| 前端 | Vue 3.4.38 + Vite 5.4.2 + Element Plus 2.8.1 |
| 系统库 | PostgreSQL 16.4 |
| 目标数据库连接 | JDBC（Oracle 11g / MySQL 5.6） |
| 部署方式 | Jar + systemd + Nginx |
| 扩展模式 | MCP 统一入口 + Skill 插件式扩展 |
| 构建工具 | Maven 3.9.14 |

**启动前必须完成项：**

1. Oracle 11g + ojdbc8 19.22.0.0 + JDK 17 全量联调验证
2. MySQL 5.6 + mysql-connector-java 5.1.49 联调验证
3. MCP 协议与 Claude Code 对接方式确认与最小化 PoC
4. Spring Boot 版本路线锁定（PoC 验证后确定 3.2.8 或 2.7.18）

---
