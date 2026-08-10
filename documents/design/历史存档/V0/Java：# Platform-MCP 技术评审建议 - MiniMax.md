# Java：# Platform-MCP 技术评审建议 - MiniMax

> 评审人：MiniMax | 日期：2026-05-28
> 评审依据：Java：# Platform_MCP 技术架构说明文档 - GPT.md、Java：# Platform_MCP 架构说明（正式版）- GPT.md
> 方向：一期可行性·软件兼容性；二期扩展性·hard think

---

## 一、一期可行性：软件兼容性评审

### 1.1 JDK 17 + Spring Boot 3.2.8 对 Oracle 11g 的兼容风险（核心风险）

**风险点**：Spring Boot 3.x 要求 JDK 17+，但 Oracle 11g 发布于 2013 年，其官方 JDBC 驱动对 JDK 17+ 的兼容性从未作为 Oracle 的设计目标。

**关键矛盾**：
- 文档建议 `ojdbc8 19.22.0.0`（2019 年发布，支持 JDK 8/11/17）
- 但 Oracle 11g 的认证协议（Oracle SYSTEM 认证）和 SQL 语法仍基于 11g 本身版本
- `ojdbc6 11.2.0.4` 虽为 Oracle 11g 原生配套驱动，但无法在 JDK 17 上运行
- **结论**：JDK 17 + `ojdbc8` 是形式兼容，Oracle 11g 实际行为（如游标、存储过程、字符集）需要实测验证，不能认为"跑通即兼容"

**建议**：
- 启动前必须完成 Oracle 11g + `ojdbc8 19.22.0.0` + JDK 17 的**全量联调验证**
- 验证项至少包括：连接认证、字符集编码、DATE/TIMESTAMP 类型、存储过程调用（含 OUT 参数）、多语句执行（`;` 分割）、事务控制
- 验证不通过时的回退方案应提前准备：Spring Boot 2.7.18 + JDK 11 + `ojdbc6`，但需评估降级对其他技术栈的影响

---

### 1.2 HikariCP 对老数据库的连接池风险

**风险点**：HikariCP 5.0.1 在连接 Oracle 11g、MySQL 5.6 时，连接池初始化和超时策略可能出现预期外行为。

**关注点**：
- Oracle 11g 的 TNS 连接方式与 HikariCP 默认超时设置可能冲突
- MySQL 5.6 的 `wait_timeout`（默认 8 小时）与连接池保活策略需对齐
- 连接池验证不能仅测"能拿到连接"，需在**长连接保活、断线重连、网络闪断**场景下验证

**建议**：
- 准备 Oracle RAC 场景下多点连接的连接池配置模板
- MySQL 5.6 建议显式设置 `connectionTimeout=30s`、`idleTimeout=600s`、`maxLifetime=7200s`

---

### 1.3 Spring Security 6.2.5 + Session 方案稳定性

**评估**：方案选用 Session 而非 JWT，是合理的内部管理台选择。

**兼容性关注**：
- Spring Security 6.x 相比 5.x 有较大变化，首期使用需确保团队熟悉度
- Session 存储使用 PostgreSQL（Spring Session JDBC）或内存？文档未明确
- 内部场景的 Session 超时策略建议不超过 30 分钟，需考虑 Claude Code 长时间运行 SQL 的场景

**建议**：明确 Session 存储方案，推荐 Spring Session JDBC 持久化到 PostgreSQL，避免进程重启导致管理员 Session 失效。

---

### 1.4 MySQL 5.6 + mysql-connector-java 5.1.49 兼容性

**评估**：选择 5.1.49 是务实的决策，避免了 MySQL 8.x 驱动的认证协议和时区问题。

**补充关注**：
- MySQL 5.6 的 `character_set_server` 默认 latin1，需确认目标库字符集配置
- `useUnicode=true&characterEncoding=UTF-8` 应作为 JDBC URL 强制参数
- MySQL 5.6 不支持 `GET_LOCK()` 等高版本特性，如风险引擎依赖此类特性需重构

---

### 1.5 Node.js 20.15.1 + Vue 3 前端栈稳定性

**评估**：前端技术栈主流且版本适中，无重大兼容性风险。

**关注点**：
- Element Plus 2.8.1 对 Vue 3.4.38 的兼容已验证，不是风险点
- Vite 5.4.2 在 Node.js 20 下运行正常
- 潜在风险：Element Plus 未来升级路径与 Vue 3.5+ 的兼容性，建议锁定 minor 版本

---

## 二、二期扩展性：hard think

### 2.1 Skill 插件式扩展的真实复杂度

**文档描述**：MCP 统一入口 + Skill 插件式扩展，预留 file、log、config、deploy 等 Skill。

**Hard Think**：

当前设计核心问题是 **Skill 接口过于业务化**，未能真正抽象为可插拔模式。

| 当前设计 | 问题 | 理想方向 |
|---|---|---|
| `skillName()` + `listTools()` + `execute()` | Tool 级别的耦合埋在 Skill 内部 | 接口应该只定义 `execute(context)`，Tool 是上层路由概念 |
| Skill 直接依赖 `sql-executor`、`risk-engine` | 不同 Skill 底层能力不可共享 | 应存在独立的 **Capability 层**，Skill 可复用 executor、risk 等公共服务 |
| Skill 注册仅靠 Registry 映射 | 新增 Skill 需修改 MCP Core 路由逻辑 | 应该是声明式注册，MCP Core 通过 SPI 发现 |

**建议**：
- 引入 Java SPI（`ServiceLoader`）机制，实现真正的插件式加载
- 设计 **Capability 抽象层**（执行器、风险识别、审计），各 Skill 按需组合使用
- 每个 Skill 应该是独立的 JAR，放入指定目录后自动注册，而非编译时耦合

---

### 2.2 SQL Executor 的扩展性缺陷

**问题**：当前 `sql-executor` 模块以**多语句分割**为核心设计，但 Oracle 和 MySQL 的 SQL 语法差异巨大，第一期用"按分号分割"的方式在二期扩展到其他数据库（如 PostgreSQL、SQL Server）时将遇到严重阻碍。

**具体风险**：
- Oracle 的 `BEGIN...END;` PL/SQL 块不能简单按分号分割
- MySQL 的 `DELIMITER` 语法在 JDBC 中无法直接模拟
- 不同数据库的游标处理、存储过程调用方式各不相同

**建议**：
- 设计 **数据库方言抽象层（DatabaseDialect）**，类似 JPA 的 `Dialect` 概念
- 每个目标数据库一个 `Dialect` 实现：方言识别、语句分割、特殊语法处理、结果集映射
- `sql-executor` 只调用 `Dialect` 接口，不感知具体数据库差异
- 二期新增数据库支持，只需实现新的 `Dialect`，无需改动 `sql-executor` 核心逻辑

---

### 2.3 Risk Engine 的扩展性

**问题**：当前风险识别逻辑硬编码在 `risk-engine` 中，识别规则（如"DROP/TRUNCATE 是高危"）在代码中写死。

**建议**：
- 设计 **风险规则引擎**，支持配置化规则加载（JSON/YAML 规则文件）
- 按数据库类型分别配置风险规则集（Oracle 规则 vs MySQL 规则）
- 二期扩展新风险类型（如"无 WHERE 的 UPDATE"）不应修改代码，而是增加规则配置
- 建议参考 `Netflix/conductor` 的规则引擎思路，或引入 `Drools` 轻量规则引擎

---

### 2.4 MCP 调用上下文与 Skill 解耦

**问题**：当前设计的统一上下文（traceId、requestId、operator...）与 Skill 实现紧绑定。如果未来新增 Skill 需要扩展上下文字段（如 `file skill` 需要 `filePath`），当前设计可能导致上下文膨胀或兼容性问题。

**建议**：
- 设计 **分层上下文**：基础上下文（所有 Skill 共享）+ Skill 专用上下文（作为 extension 字段）
- 基础上下文只保留 traceId、requestId、operator、skillName、startTime 等通用字段
- Skill 专用上下文以 Map 或结构化 JSON 字段存储，按 Skill 类型动态解析

---

### 2.5 模块间循环依赖隐患

**Hard Think**：审视 13 个模块的依赖关系，存在潜在的循环依赖风险。

当前模块依赖关系（推断）：

```
mcp-core → skill-api → skill-registry → skill-database → sql-executor
                                                    → risk-engine
mcp-core → audit
web-admin → auth, datasource, crypto, audit, monitor
```

**风险点**：
- `skill-database` 同时依赖 `sql-executor` 和 `risk-engine`，但两者如果相互依赖则形成循环
- `audit` 被多个模块直接调用，需确认是 AOP 切面还是直接注入
- `crypto` 被 `datasource` 调用，但 `datasource` 如果被 `auth` 调用则存在隐蔽循环

**建议**：
- 绘制完整的模块依赖图，识别所有循环依赖
- 使用 `@DependsOn` 或构造器注入显式管理依赖顺序
- 建议 `audit` 使用 AOP 切面实现，对业务模块零侵入，避免直接依赖注入

---

### 2.6 二期新增 Skill 的接入成本预估

| 预留 Skill | 接入难度 | 关键依赖 |
|---|---|---|
| `file` | 中 | 文件系统权限、路径校验、沙箱隔离 |
| `log` | 中低 | 日志文件解析、编码检测、大文件处理 |
| `config` | 低 | 配置文件读写、配置变更审计 |
| `deploy` | 高 | 远程连接、权限提升、幂等性保障、rollback 能力 |
| `shell` | 高 | 命令注入防护、超时控制、执行日志 |

**建议**：二期优先落地 `config` Skill 以验证 MCP 框架扩展性，再推进 `file` 和 `log`，`deploy` 和 `shell` 应作为独立安全评审项，不建议与二期其他 Skill 同期开发。

---

## 三、综合评审结论

### 3.1 一期可行性

| 评审项 | 结论 | 备注 |
|---|---|---|
| JDK 17 + Spring Boot 3.2.8 | ⚠️ 待验证 | Oracle 驱动兼容性需专项验证，否则降级至 Spring Boot 2.7.18 |
| Oracle 11g 接入 | ⚠️ 风险可控 | 必须完成联调验证，不能假设兼容 |
| MySQL 5.6 接入 | ✅ 风险低 | 5.1.49 驱动选择合理 |
| PostgreSQL 16.4 系统库 | ✅ 无风险 | 主流版本，兼容性无忧 |
| 前端技术栈 | ✅ 无风险 | 版本组合主流稳定 |

**一期总体结论**：方案技术选型方向正确，主要风险集中在 Oracle 11g 驱动兼容性。**必须**在项目启动前完成 Oracle 11g + `ojdbc8` 的全量联调验证，以验证结果固化最终技术组合。

---

### 3.2 二期扩展性

| 评审项 | 结论 | 建议 |
|---|---|---|
| Skill 插件机制 | ⚠️ 需加强设计 | 引入 SPI + Capability 抽象层 |
| SQL Executor 扩展性 | ⚠️ 架构隐患 | 设计 DatabaseDialect 方言抽象 |
| Risk Engine 扩展性 | ⚠️ 规则硬化 | 配置化规则引擎改造 |
| 上下文扩展性 | ⚠️ 紧耦合 | 分层上下文设计 |
| 模块依赖管理 | ⚠️ 需审查 | 绘制完整依赖图，消除循环依赖 |
| 二期 Skill 优先级 | ✅ 合理 | file → log → config，deploy/shell 独立评审 |

**二期总体结论**：当前设计为二期扩展预留了接口，但接口设计偏业务化，未实现真正的插件式架构。建议在完成一期后、二期启动前，对 Skill 插件机制和 SQL 方言层进行架构强化设计，避免后续扩展时推翻核心模块设计。

---

## 四、启动前必须确认的检查项

1. ✅ Oracle 11g + `ojdbc8 19.22.0.0` + JDK 17 全量联调验证（连接、SQL执行、存储过程、事务、字符集）
2. ✅ MySQL 5.6 + `mysql-connector-java 5.1.49` 联调验证（多语句、字符编码、时区）
3. ✅ HikariCP 在 Oracle RAC 和 MySQL 下的连接池配置模板
4. ✅ Session 存储方案确认（内存 vs Spring Session JDBC）
5. ✅ SPI 插件机制的技术验证（Skill 动态加载）
6. ✅ 完整模块依赖图绘制（识别循环依赖）

---

*评审完成*