# Platform-MCP 架构说明（正式版）

- **适用对象**：项目管理人员、架构师
- **文档用途**：用于项目评审、立项汇报、方案说明与实施边界对齐

---

## 版本更新日志

| 版本 | 日期 | 修订性质 | 修订摘要 | 修改人 |
|---|---|---|---|---|
| V1.0 | 2026-05-28 | 新建 | 初版架构说明文档，明确系统定位、总体架构、技术选型、模块划分、部署方案、实施边界及扩展原则 | castle.zhang |
| V1.1 | 2026-05-29 | 修订 | 新增 Skill 管理页与个人设置页；密码加解密页更名为密码加密页；补充 Skill 注册方式说明；登录页改为双栏布局；补充 sys_skill 系统表 | castle.zhang |

---

# 1. 文档概述

## 1.1 项目背景

Platform-MCP 项目面向内部场景建设统一的 MCP（Model Context Protocol）能力平台。项目首期聚焦数据库 Skill，通过标准 MCP 接口承接 Claude Code 等调用方的数据库执行请求，同时建设配套的管理界面、权限控制、状态查看和审计能力。

本文档在前期架构设计与多轮技术评审基础上，整合形成项目启动阶段的统一技术基线，作为项目评审、立项汇报和实施边界对齐的正式依据。

## 1.2 建设目标

- 建设统一的 MCP 服务入口，支撑 Claude Code 调用
- 首期落地数据库 Skill，支持执行本地 `.sql` 文件和 SQL 文本
- 提供统一的用户、权限、环境和数据源管理能力
- 提供完整的执行审计、风险识别和调用状态查看能力
- 支持 Oracle 11g、MySQL 5.6 等存量数据库兼容接入
- 保留后续扩展其他 Skill 的能力，避免首期架构固化

## 1.3 文档范围

本文档说明以下内容：

- 项目定位与建设原则
- 总体架构设计
- 技术选型方案
- 核心模块设计
- MCP 能力架构与扩展原则
- 安全设计
- 数据存储设计
- 部署架构
- 实施边界与分期规划
- 兼容性风险与合规说明

---

# 2. 系统定位与建设原则

## 2.1 系统定位

| 定位 | 说明 |
|---|---|
| MCP 能力服务平台 | 面向内部使用的统一 MCP 服务入口 |
| 数据库 Skill 服务 | 首期聚焦数据库执行能力 |
| 管理与审计平台 | 具备权限、审计、配置管理、状态监控能力的 Web 管理平台 |
| 可扩展能力底座 | 可持续扩展其他 Skill 的统一技术底座 |

**与传统 SQL 平台的区别：** 本项目核心执行入口为 MCP，Web 端主要承担管理、审计和运维支撑职责，不作为主要 SQL 编写执行入口。

## 2.2 核心建设原则

| 原则 | 说明 |
|---|---|
| 稳定优先 | 选择成熟、长期维护稳定的技术组件 |
| 兼容优先 | 兼容存量数据库（Oracle 11g、MySQL 5.6）、老驱动和传统部署方式 |
| 简单优先 | 不引入 Docker、K8s、微服务等当前阶段不必要的复杂度 |
| 扩展优先 | MCP 层按 Skill 插件式能力扩展设计，首期即固化接口规范 |
| 审计优先 | 所有关键调用、配置变更、安全操作全链路可追溯 |

## 2.3 非目标说明

以下内容不纳入建设范围：

- Web 在线 SQL 富编辑器
- 工作流审批引擎
- 微服务拆分
- Docker/K8s 云原生部署
- 多机房高可用架构
- 大规模分布式任务调度平台

---

# 3. 总体架构设计

## 3.1 架构结论

系统采用以下架构形态：

- **Java 单体模块化架构**
- **Web 管理端 + MCP Server + Skill 层 + PostgreSQL 系统库**
- **JDBC 连接目标数据库**
- **Jar 包部署 + systemd + Nginx**

## 3.2 架构分层

| 层次 | 职责 |
|---|---|
| 调用侧 | Claude Code（MCP 协议调用）、Web 管理用户（浏览器访问）、运维管理员 |
| 接入层 | MCP Tool 接口、Web REST API |
| 业务服务层 | 权限认证、MCP 请求分发与 Skill 路由、数据源管理、密码加解密、SQL 执行与风险识别、审计日志与状态监控 |
| 数据层 | PostgreSQL 系统库（系统管理数据）、Oracle 11g / MySQL 5.6（业务执行目标库） |

## 3.3 核心使用场景

**场景 A：Claude Code 接入** — Claude Code 通过添加 MCP Server 配置接入本系统，MCP Server 作为能力提供方响应 Tool 调用请求。

**场景 B：指定环境执行 SQL 脚本** — 用户通过 Claude Code 提示目标环境，系统自动匹配对应数据源，读取本地 `.sql` 文件内容，执行 SQL 并审计过程及结果。

**场景 C：高风险操作二次确认** — 当 SQL 执行触发高风险标识（如 DELETE 无 WHERE、DROP、TRUNCATE），系统返回风险提示，要求用户确认后方可继续执行，确认或取消操作均写入审计日志。

---

# 4. 技术选型方案

## 4.1 后端技术栈

| 组件 | 版本 | 选型说明 |
|---|---|---|
| JDK | 17.0.11 LTS | 长期支持版本，兼顾稳定性与生态成熟度 |
| Spring Boot | 3.2.8 | 长期稳定企业级版本 |
| Spring Framework | 6.1.12 | 随 Spring Boot 3.2.8 配套 |
| Spring Security | 6.2.5 | 权限与认证控制 |
| Spring Session | 6.2.5 | Session 持久化至 PostgreSQL |
| MyBatis Spring Boot Starter | 3.0.3 | 系统库访问与管理数据持久化 |
| HikariCP | 5.0.1 | 系统库连接池 |
| PostgreSQL JDBC Driver | 42.7.3 | 系统库连接驱动 |
| MySQL Connector/J | 5.1.49 | 针对 MySQL 5.6 的稳定兼容版本 |
| Oracle JDBC Driver | ojdbc8 19.22.0.0 | 需根据 JDK 17 + Oracle 11g 实际适配验证 |
| Jackson | 2.17.2 | JSON 序列化反序列化 |
| SLF4J + Logback | 2.0.13 / 1.5.6 | 日志门面与实现 |
| Maven | 3.9.14 | 构建工具 |

辅助工具库：Apache Commons Lang3 3.14.0、Apache Commons IO 2.16.1、Hutool 5.8.31（可选）、Lombok 1.18.34（可选但建议规范使用）。

## 4.2 前端技术栈

| 组件 | 版本 | 选型说明 |
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
| ECharts | 5.5.1 | 状态监控图表（可选） |

一期在 `package.json` 中使用精确版本号（不用 `^`），锁定当前版本组合，避免开发期间版本漂移。

## 4.3 数据库与中间件

| 组件 | 版本 | 选型说明 |
|---|---|---|
| PostgreSQL | 16.4 | 系统库，稳定且适合管理类数据 |
| Nginx | 1.26.1 | 静态资源托管与反向代理 |
| systemd | OS 自带 | 服务托管 |
| Linux OS | Rocky Linux 9.4 / RHEL 9.x / CentOS Stream 9 | 推荐服务器环境 |

---

# 5. 版本兼容与前置验证

## 5.1 Spring Boot 版本策略

**正式目标：** Spring Boot 3.2.8 + JDK 17

**回退策略：** 若 Oracle JDBC 驱动联调验证存在不可接受风险，回退至 Spring Boot 2.7.18 + Spring Security 5.8.x，保持 JDK 17 或降至 JDK 11。

**锁定原则：** 项目启动前通过 PoC 验证后锁定单一路线，不保留双版本并行开发空间。

## 5.2 驱动兼容性验证要求

项目正式启动前需完成以下专项验证：

**Oracle 11g（JDK 17 + ojdbc8 19.22.0.0）：**

| 验证项 | 验证内容 |
|---|---|
| 连接建立 | Basic/TNS 连接方式 |
| 字符集 | AL32UTF8 / ZHS16GBK 场景 |
| 日期类型 | DATE / TIMESTAMP 读写 |
| 存储过程 | IN/OUT/INOUT 参数、REF CURSOR |
| 大字段 | CLOB/BLOB 读写 |
| 事务控制 | autocommit=false + commit/rollback |

**MySQL 5.6（mysql-connector-java 5.1.49）：** 重点验证字符集配置、时区参数、多语句执行开关及事务隔离行为。

---

# 6. 核心模块设计

## 6.1 一期模块清单

一期采用精简模块方案，共 7 个模块：

| 模块 | 包含能力 | 说明 |
|---|---|---|
| `Platform-MCP-web-admin` | Web REST API | 前端对接接口与页面数据聚合输出 |
| `Platform-MCP-auth` | 认证鉴权 | 登录认证、用户/角色/权限管理 |
| `Platform-MCP-datasource` | 数据源管理 + 密码加解密 | 数据源配置、JDBC 连接参数、密码加密解密 |
| `Platform-MCP-mcp-core` | MCP 接入 + Skill 接口 + 注册路由 | MCP 协议接入、Skill 统一接口定义、Skill 注册与路由分发 |
| `Platform-MCP-skill-database` | 数据库 Skill + SQL 执行器 + 风险引擎 | 数据库 Skill 业务逻辑、SQL 执行、风险识别 |
| `Platform-MCP-audit` | 审计 + 状态监控 | 审计日志记录、MCP 调用状态统计、服务运行状态输出 |
| `Platform-MCP-common` | 通用工具 | 通用异常、响应模型、枚举、工具类、常量 |

## 6.2 模块职责边界

**Platform-MCP-web-admin：** 提供 Web 管理 REST API，前端页面数据聚合输出，对接 auth、datasource、audit 等模块。

**Platform-MCP-auth：** 用户名密码登录认证、用户/角色/权限管理、资源访问鉴权、Session 持久化至 PostgreSQL（Spring Session JDBC）。

**Platform-MCP-datasource：** 数据源信息管理（增删改查、启停）、环境管理（DEV/TEST/PROD）、JDBC 连接参数管理、数据源权限控制、密码加密与解密、密钥读取与密码操作审计。

**Platform-MCP-mcp-core：** MCP 协议接入与 Tool 参数解析、Skill 统一接口标准定义、Skill 注册发现与路由分发、调用链路上下文封装、统一响应结构、MCP 调用并发限流。

**关键约束：** Database Skill 相关逻辑不得侵入 mcp-core。mcp-core 只处理协议接入、参数标准化、上下文封装和响应封装。

**Platform-MCP-skill-database：** 数据库 Skill 业务逻辑、Tool 能力落地（execute_sql_file、execute_sql_text、validate_sql、list_datasources、get_execution_status）、SQL 执行（多语句分段、查询结果映射、存储过程调用）、SQL 风险识别。

**Platform-MCP-audit：** 审计日志记录（登录登出、MCP 调用、SQL 执行、配置变更、安全操作）、MCP 调用状态统计、服务运行状态输出。

**Platform-MCP-common：** 通用异常与错误码、统一响应模型、公共枚举、工具类与常量。

---

# 7. MCP 能力架构

## 7.1 设计原则

MCP 层按"统一入口 + Skill 扩展"设计：

- MCP Server 负责协议接入
- Skill 负责能力实现
- Registry 负责路由分发
- Audit 负责全链路记录

## 7.2 一期 Skill 与 Tool 规划

一期仅建设 `database` Skill，提供以下 Tool。一期 Web 管理端新增 Skill 管理页，支持查看已注册 Skill 列表、使用方式、Skill 启停操作。Skill 注册方式支持三种：页面新增、源码上传解析（解析后人工确认注册）、注解注册。

| Tool | 说明 |
|---|---|
| `execute_sql_file` | 接收文件路径，读取本地 SQL 文件并执行 |
| `execute_sql_text` | 接收 SQL 文本直接执行 |
| `validate_sql` | 校验 SQL 语法并返回风险等级 |
| `list_datasources` | 列出当前用户可访问的数据源 |
| `get_execution_status` | 查询异步执行任务的状态 |

二期预留 Skill：`file`、`log`、`config`、`deploy`、`shell`。

## 7.3 Skill 统一接口

每个 Skill 实现需统一具备以下方法：

| 方法 | 说明 |
|---|---|
| `skillName()` | 返回 Skill 名称 |
| `listTools()` | 返回该 Skill 提供的 Tool 列表 |
| `validate()` | 校验 Tool 输入参数 |
| `execute()` | 执行 Tool 逻辑 |
| `support()` | 判断是否支持指定 Tool |

二期扩展时预留生命周期方法：`initialize()`、`destroy()`。

---

# 8. 安全设计

## 8.1 认证方案

Web 管理端采用 Session 方案，用户名密码登录，Session 持久化至 PostgreSQL（Spring Session JDBC），Session 超时策略不超过 30 分钟。

选择 Session 而非 JWT 的原因：内部系统简单稳定，后台管理场景更易控制会话失效和权限收敛。

登录页采用双栏布局：左侧为企业项目视觉区（项目名称、功能亮点），右侧为登录表单，底部版权说明。

## 8.2 权限模型

| 控制维度 | 说明 |
|---|---|
| 用户 | 系统用户 |
| 角色 | 用户分组 |
| Skill | 能力模块 |
| Tool | 具体操作 |
| 环境 | DEV / TEST / PROD |
| 数据源 | 具体数据库实例 |
| 页面功能点 | 菜单或按钮级控制 |

一期重点控制 Tool + 环境 + 数据源维度，页面功能点权限先做到菜单级基础控制。个人设置页（显示名称、邮件地址、修改密码）仅当前登录用户可修改自己的信息。

## 8.3 密码加解密方案

- 算法：AES-256
- 密钥管理：存储于独立 secret 文件（`crypto-secret.key`），严禁入库明文保存、严禁写死在代码中，secret 文件权限收敛

## 8.4 审计要求

以下操作必须审计，审计能力从第一阶段开始建设：

- 登录登出
- MCP Tool 调用
- SQL 执行
- 数据源新增修改删除
- 权限变更
- 密码加密与解密
- 系统参数修改

---

# 9. 数据存储设计

## 9.1 系统库与目标库分离原则

- PostgreSQL 用于系统管理数据，使用 Spring 管理数据源（HikariCP 连接池）
- Oracle/MySQL 用于业务执行目标库，采用动态 JDBC 连接工厂，按需建立连接
- 系统库访问与目标库访问逻辑严格分离

## 9.2 目标库连接策略

- 每次执行创建连接 → 执行 → 关闭（try-with-resources），不为所有目标数据库长期持有连接池
- 全局配置连接超时（默认 30s）和查询超时（默认 300s）
- 按数据源维护 Semaphore 控制最大并发连接数（默认 5）

## 9.3 核心表清单

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

审计主表保留通用字段，数据库专有字段（datasource_code、env_code）作为可选字段，确保审计结构面向所有 Skill 通用。`sys_audit_log` 和 `sys_mcp_call_log` 数据量增长后考虑按时间分区。

---

# 10. 部署架构

## 10.1 部署形态

采用传统部署方式，不采用 Docker：

- 后端 Jar 部署
- 前端静态资源部署
- PostgreSQL 独立部署
- Nginx 反向代理（托管前端静态资源、反向代理后端接口）
- systemd 托管

## 10.2 目录结构

```
/opt/Platform-MCP/
├── app/           # 后端 Jar 包
├── config/        # 配置文件
├── secret/        # 密钥文件
├── logs/          # 日志文件
├── scripts/       # 运维脚本
└── sql-scripts/   # SQL 脚本文件（白名单目录）
```

## 10.3 运维要点

- systemd 统一管理服务启停（服务名：`Platform-MCP.service`）
- secret 文件权限收敛，仅应用运行用户可读
- 配置文件按环境分离（application-dev/test/prod.yml）
- 日志按天滚动，保留周期按运维规范设置

---

# 11. 实施边界说明

## 11.1 一期纳入范围

- Java 后端服务建设（7 模块）
- Web 管理端建设（5 个核心页面）
- MCP 统一入口与 Database Skill 实现
- 用户/角色/权限管理
- 数据源管理与密码加解密管理
- 审计日志与 MCP 调用状态查看
- PostgreSQL 系统库建设
- Oracle 11g / MySQL 5.6 兼容接入
- SQL 风险识别与高风险操作二次确认

## 11.2 一期核心页面

| 页面 | 优先级 | 说明 |
|---|---|---|
| 登录页 | P0 | 系统认证入口 |
| Skill 管理页 | P0 | Skill 注册信息查看、使用方式说明、启停管理 |
| 数据源管理页 | P0 | MCP 调用的前置依赖 |
| 密码加密页 | P0 | 数据源配置的配套能力 |
| 审计日志页 | P0 | 合规要求 |
| 用户管理页 | P1 | 基本账号管理 |
| 个人设置页 | P1 | 用户自定义显示名称、邮件地址、修改密码 |

一期延后至二期的页面：系统概览页、角色权限管理页、MCP 调用状态页、系统配置页。

## 11.3 一期不纳入范围

- 多微服务拆分
- Docker / K8s 平台化部署
- 复杂工作流审批
- 大规模分布式调度
- 多 Skill 同步开发落地
- Web 在线 SQL 富编辑器

## 11.4 前端职责边界

前端负责页面交互、表单校验、数据展示和后端接口调用。前端不负责 SQL 真正执行、数据库密码真实加解密、风险识别逻辑和权限判定最终决策。

---

# 12. 兼容性与风险说明

## 12.1 一期支持矩阵

| 能力 | Oracle 11g | MySQL 5.6 |
|---|---|---|
| SELECT 查询 | 支持 | 支持 |
| INSERT / UPDATE / DELETE | 支持 | 支持 |
| 多语句执行 | 需验证 | 支持 |
| 存储过程调用 | 支持 | 需验证 |
| 事务控制 | 支持 | 支持 |

## 12.2 风险识别策略

一期采用正则 + 关键词匹配进行 SQL 风险识别：

| 风险等级 | 说明 | 处理策略 |
|---|---|---|
| LOW | SELECT 查询等低风险操作 | 正常执行 |
| MEDIUM | INSERT、带 WHERE 的 DML | 正常执行 |
| HIGH | 无 WHERE 的 UPDATE/DELETE、解析失败 | 提示用户二次确认 |
| CRITICAL | DROP、TRUNCATE、生产库 DDL | 强制二次确认 |

风险识别为辅助参考，不保证 100% 准确。一期不覆盖 PL/SQL 块内部语义分析、嵌套子查询风险、存储过程内部操作识别等复杂场景。

生产库（env_code=PROD）数据源默认标记为"受保护"，其 DDL 和 DELETE WITHOUT WHERE 操作强制标记为 CRITICAL。风险规则可通过 `sys_system_config` 表配置开关，无需改代码。

## 12.3 主要风险项

| 风险项 | 说明 | 应对措施 |
|---|---|---|
| Oracle 11g 驱动兼容性 | ojdbc8 19.x 对 Oracle 11g 为"尽力兼容"而非"官方认证" | 项目启动前完成全量联调验证 |
| MySQL 5.6 驱动兼容性 | 字符集、时区、多语句等需专项验证 | 项目启动前完成联调验证 |
| SQL 多语句解析 | 一期不承诺完全通用 SQL 脚本解析能力 | 解析失败的 SQL 统一标记为 HIGH 风险 |
| 密码解密权限控制 | 解密操作涉及敏感信息暴露 | 严格限制解密权限并记录审计 |

---

# 13. 迭代分期与验收标准

## 13.1 分期边界

| 维度 | 一期 | 二期 |
|---|---|---|
| 核心目标 | Database Skill 落地闭环 | Skill 扩展 + 能力增强 |
| Skill 数量 | 1（database） | 3-5（+ file / log / config） |
| 模块数量 | 7 | 按需拆分至 10-13 |
| Web 页面 | 5 个核心页面 | 7 个核心页面（+Skill 管理、个人设置） | 补全至 9 个 |
| 风险引擎 | 正则 + 关键词 | 配置化规则引擎 |
| 数据库方言 | Oracle + MySQL 基础支持 | DatabaseDialect 方言抽象层 |
| Skill 注册 | 编译期静态注册 | SPI 插件式动态注册 |
| 连接管理 | 按需连接 | 轻量连接池 |
| 限流 | 基础并发控制 | Resilience4j 熔断器 |

## 13.2 一期实施阶段

| 阶段 | 内容 |
|---|---|
| 阶段一：技术兼容验证 | JDK + Spring Boot + Oracle/MySQL 驱动组合验证；MCP 协议与 Claude Code 对接 PoC |
| 阶段二：基础框架与系统库 | 后端工程骨架（7 模块）；系统库表结构初始化；用户/角色/权限基础模型；审计日志基础设施；通用响应与异常机制 |
| 阶段三：MCP Core 与 Skill Registry | MCP 请求接入与 Tool 参数解析；Skill 接口定义与固化；Skill 注册路由与 MCP 调用日志；基础并发限流 |
| 阶段四：Database Skill 闭环 | list_datasources / execute_sql_text / execute_sql_file / validate_sql；高风险操作二次确认；基础事务控制；Oracle / MySQL 执行支持；生产库受保护标记 |
| 阶段五：Web 管理端 | 登录页（双栏布局）、Skill 管理页、数据源管理页、密码加密页、审计日志页、用户管理页、个人设置页 |
| 阶段六：测试与上线 | 兼容性测试、权限隔离测试、审计完整性测试、部署启停与日志检查 |

## 13.3 一期验收标准

**功能验收：**

- Claude Code 可通过 MCP 调用 Database Skill
- 可执行 SQL 文本和受控范围内的本地 `.sql` 文件
- 可查询可用数据源并查看审计日志
- 可配置数据源及密文密码
- 可按用户/角色/数据源/环境控制访问
- 高风险操作触发二次确认

**兼容性验收：**

- Oracle 11g 基础连接和 SQL 执行通过
- MySQL 5.6 基础连接和 SQL 执行通过
- PostgreSQL 系统库访问稳定
- 目标数据库连接失败时不影响系统库和管理端
- 驱动版本、JDK 版本、Spring Boot 版本形成最终固化清单

**安全与审计验收：**

- 目标数据库密码不明文入库，secret 文件不写入代码
- 解密操作受权限控制，SQL 执行全链路可追踪
- MCP 调用、配置变更、权限变更均有审计记录

**运维验收：**

- 支持 Jar 启动、systemd 启停、Nginx 反向代理
- 日志按目录输出，配置文件与 secret 文件分离
- 服务异常可通过日志定位

## 13.4 二期规划方向

**Skill 扩展：** 按优先级逐步扩展：`config`（低风险，验证框架扩展性）→ `file` → `log` → `deploy`（高风险，独立安全评审）→ `shell`（高风险，独立安全评审）

**架构增强：** DatabaseDialect 方言抽象、SPI 插件机制、Capability 抽象层、配置化规则引擎、轻量连接池、Resilience4j 熔断、流式响应、多环境隔离增强。

**Web 页面补全：** 系统概览页、角色权限管理页、MCP 调用状态页、系统配置页。

---

# 14. 合规与许可说明

## 14.1 总体合规结论

本项目后端主要依赖组件均为 Apache License 2.0、MIT License 或 BSD 协议，无传染性风险。前端依赖组件均为 MIT 或 Apache License 2.0，无传染性风险。系统库 PostgreSQL 采用 PostgreSQL License（类 BSD），Nginx 采用 BSD 2-Clause，均无传染性。

## 14.2 重点合规关注

| 风险项 | 说明 | 建议 |
|---|---|---|
| Oracle JDBC (ojdbc8) | OTN License 限制 | 确认持有有效的 Oracle 数据库许可证，ojdbc8 随 Oracle 数据库授权分发 |
| MySQL Connector/J 5.1.49 | GPLv2 + FOSS Exception | 内部使用不构成分发，合规风险低；若作为项目对外分发需评估 GPL 传染性或购买商业许可 |

---

# 15. 方案结论

## 15.1 技术路线结论

| 维度 | 选型 |
|---|---|
| 后端 | JDK 17.0.11 + Spring Boot 3.2.8 |
| 前端 | Vue 3.4.38 + Vite 5.4.2 + Element Plus 2.8.1 |
| 系统库 | PostgreSQL 16.4 |
| 目标数据库连接 | JDBC（Oracle 11g / MySQL 5.6） |
| 部署方式 | Jar + systemd + Nginx |
| 扩展模式 | MCP 统一入口 + Skill 插件式扩展 |
| 构建工具 | Maven 3.9.14 |

## 15.2 启动前必须完成项

1. Oracle 11g + ojdbc8 19.22.0.0 + JDK 17 全量联调验证
2. MySQL 5.6 + mysql-connector-java 5.1.49 联调验证
3. MCP 协议与 Claude Code 对接方式确认与最小化 PoC
4. Spring Boot 版本路线锁定（PoC 验证后确定 3.2.8 或 2.7.18）
