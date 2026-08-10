# Platform-MCP 技术架构评审建议

- **评审对象**：《Java：# Platform-MCP 技术架构说明文档》、《Python：# Platform-MCP 技术架构说明文档》
- **评审日期**：2026-05-28
- **评审维度**：一期可行性、版本兼容性、二期扩展性、安全合规、文档质量
- **评分体系**：1-10 分制，10 分为最优

---

## 一、评审总览

### 1.1 综合评分总表

| 评审维度 | Java（Spring Boot） | Python（FastAPI） | 评分说明 |
|---|---|---|---|
| 架构完整性 | **9** | **9** | 两份文档架构设计均非常完整、层次清晰 |
| 一期技术可行性 | **7** | **8** | Python MCP SDK 为官方实现，Java 侧 MCP SDK 成熟度存疑 |
| 版本兼容性 | **7** | **6** | Java JDBC 对 Oracle 11g/MySQL 5.6 更成熟；Python 异步驱动对旧库兼容性风险更高 |
| MCP 集成成熟度 | **4** | **9** | 关键分水岭：Python MCP SDK 是官方参考实现，Java 侧未指明具体 MCP 库 |
| 安全设计 | **8** | **8** | 两者安全设计相当，Java Spring Security 更成熟，Python 需自定义 Session 管理 |
| 二期扩展性 | **8** | **9** | Python 动态加载天然适合插件化，Java SPI 需更多样板代码 |
| 部署运维 | **8** | **7** | Java Jar 部署更成熟稳定，Python venv 部署需要额外离线安装方案 |
| 文档质量 | **9** | **9** | 两者文档质量均属优秀，结构完整、表述清晰 |
| 风险可控性 | **7** | **7** | Java 存在 Spring Boot 版本不确定性；Python 存在 Oracle 11g 异步驱动兼容性风险 |
| 合规性 | **7** | **9** | Java Oracle JDBC/MySQL Connector 存在许可证风险；Python 依赖多为 MIT/Apache |
| **综合得分** | **74** | **81** | — |

### 1.2 雷达图概览（文字描述）

- **Java 强项**：版本兼容性（JDBC 成熟度）、部署运维（Jar 包）、安全（Spring Security）
- **Python 强项**：MCP 集成成熟度（官方 SDK）、二期扩展性（动态加载）、合规性（MIT/Apache）
- **共同强项**：架构完整性、文档质量
- **共同短板**：Oracle 11g 兼容性均需专项验证

---

## 二、Java 技术架构评审

### 2.1 一期可行性评审

**评分：7/10**

**可行项：**

| 评估点 | 结论 | 理由 |
|---|---|---|
| Web 管理端 + REST API | ✅ 可行 | Spring Boot + Spring Security + MyBatis 组合成熟，企业级 Web 开发有大量最佳实践 |
| 认证鉴权 | ✅ 可行 | Spring Security + Spring Session JDBC 是标准方案，Session 持久化至 PostgreSQL 有成熟路径 |
| 数据源管理 | ✅ 可行 | HikariCP + 动态 JDBC 连接工厂是标准模式 |
| 审计日志 | ✅ 可行 | AOP 拦截 + 入库写入，Java 生态有成熟方案 |
| 前端对接 | ✅ 可行 | 统一响应格式 + REST API，前端 Vue 对接无障碍 |

**风险项：**

| 风险点 | 风险等级 | 说明 |
|---|---|---|
| **MCP Server 实现** | 🔴 **高** | 文档未指明 Java MCP SDK 或协议实现库。MCP 官方 SDK 为 Python 实现，Java 侧需确认使用哪个库（如 mcp-java-sdk 社区版或其他），且成熟度和协议覆盖度需独立评估 |
| **Spring Boot 版本不确定性** | 🟡 **中** | 文档提出 3.2.8 正式目标 + 2.7.18 回退策略，说明存在不确定性。两种路线的依赖管理、API 风格差异大，项目启动前必须通过 PoC 锁定单一路线 |
| **MCP Server 进程模型** | 🟡 **中** | Java 单体架构如何同时承载 Web 服务（HTTP）和 MCP Server（stdio）两个入口？文档未明确说明是双进程还是单进程双入口。若为单进程，stdio 与 HTTP 端口共存方案需设计 |

**关键建议：**

1. **必须补充 MCP Java SDK 选型**：明确使用哪个 Java MCP 库，评估其协议支持度、社区活跃度、维护状态。这是项目核心入口，不能留白。
2. **明确 MCP Server 进程架构**：是独立 main class 启动 stdio 进程，还是与 Web 共享 JVM？这对部署模型和资源管理影响重大。
3. **PoC 优先锁定 Spring Boot 版本**：3.2.8 vs 2.7.18 的决策必须在项目启动前完成，不建议保留双路线并行开发空间（文档已有此原则，需严格执行）。

### 2.2 版本兼容性评审

**评分：7/10**

| 兼容项 | 评估 | 风险 |
|---|---|---|
| Oracle 11g + ojdbc8 19.22.0.0 | ojdbc8 19.x 对 11g 为"尽力兼容"非官方认证，但生产实践中广泛使用，风险可控 | 🟡 中 |
| MySQL 5.6 + mysql-connector-java 5.1.49 | 经典稳定组合，兼容性极佳 | 🟢 低 |
| JDK 17 + Spring Boot 3.2.8 | Jakarta EE 命名空间迁移完成，稳定组合 | 🟢 低 |
| JDK 17 + ojdbc8 19.22.0.0 | 官方支持组合 | 🟢 低 |
| PostgreSQL 16.4 + PG JDBC 42.7.3 | 官方支持组合 | 🟢 低 |

**总体评价：** Java 侧的版本兼容性整体可控。MySQL 5.6 驱动选择非常稳妥。Oracle 11g 虽非官方认证，但 ojdbc8 19.x 在社区有大量成功案例。主要不确定性来自 Spring Boot 版本选择。

### 2.3 二期扩展性评审

**评分：8/10**

**扩展性优势：**

- SPI 机制是 Java 生态标准的插件化方案，Skill 热插拔有成熟的 ClassLoader 管理模式可参考
- 模块化 Maven 多模块结构天然支持职责拆分（7 → 10-13 模块路径清晰）
- DatabaseDialect 作为 Java Interface/Abstract Class 实现是惯用做法
- Resilience4j 是成熟的熔断器库
- 强类型约束确保插件契约在编译期检查

**扩展性挑战：**

- Java SPI 的 META-INF/services 配置增加了 Skill 开发者的接入成本
- 运行时热加载 JAR 需自定义 ClassLoader，有内存泄漏风险
- 模块拆分涉及 Maven 依赖重构，改动面较大
- 添加新 Skill 的开发-构建-部署周期比 Python 长

---

## 三、Python 技术架构评审

### 3.1 一期可行性评审

**评分：8/10**

**可行项：**

| 评估点 | 结论 | 理由 |
|---|---|---|
| Web 管理端 + REST API | ✅ 可行 | FastAPI 是现代高性能异步 Web 框架，Pydantic 数据校验、自动 OpenAPI 文档均为开箱能力 |
| MCP Server | ✅ 可行 | `mcp` Python SDK（v1.9.4）是官方参考实现，stdio 模式是原生支持方式，与 Claude Code 对接成熟度最高 |
| 双入口架构 | ✅ 可行 | FastAPI Web 入口 + MCP Server stdio 入口共享业务逻辑层，架构设计清晰 |
| Skill 注册路由 | ✅ 可行 | 基于 `Protocol` + 装饰器的注册模式简洁高效 |
| 审计日志 | ✅ 可行 | 分 Sprint 覆盖策略合理，不会因为审计需求阻塞核心功能开发 |

**风险项：**

| 风险点 | 风险等级 | 说明 |
|---|---|---|
| **oracledb 2.4.1 thin + Oracle 11g** | 🔴 **高** | oracledb thin 模式官方支持矩阵起始为 Oracle 12.1，Oracle 11g 不在支持范围内。异步模式 + 11g 的组合风险叠加 |
| **aiomysql 0.2.0 成熟度** | 🟡 **中** | aiomysql 0.2.0 版本号较低，社区维护活跃度一般，对 MySQL 5.6 的异步兼容性需专项验证 |
| **异步策略统一性** | 🟡 **中** | 文档要求全链路异步，但 Python async/await 生态中部分库（如旧版存储过程调用）可能只提供同步接口，混用风险需管控 |
| **双进程状态一致性** | 🟡 **中** | Web 进程与 MCP Server 进程共享 PostgreSQL 状态，但内存状态（如 Semaphore 限流计数）不共享，可能导致限流精度偏差 |

**关键建议：**

1. **Oracle 11g 验证为 P0 最高优先级**：oracledb thin 模式对 11g 兼容性验证必须在项目启动前完成。建议同时准备 thick 模式回退方案（引入 Oracle Instant Client），并在 PoC 中并行验证两条路径。
2. **评估 aiomysql 替代方案**：若 aiomysql 对 MySQL 5.6 兼容性验证不通过，可考虑 `asyncmy`（较新的异步 MySQL 驱动）或在 FastAPI 中使用 `run_in_executor` 包装同步驱动（如 PyMySQL）作为兜底。
3. **明确双进程限流策略**：建议限流以数据库层面的行锁或配置表为准，而非纯内存 Semaphore，确保双进程间限流一致。

### 3.2 版本兼容性评审

**评分：6/10**

| 兼容项 | 评估 | 风险 |
|---|---|---|
| Oracle 11g + oracledb 2.4.1 thin | 官方不支持 11g，需专项验证，回退至 thick 模式可行但增加部署复杂度 | 🔴 高 |
| MySQL 5.6 + aiomysql 0.2.0 | 异步驱动成熟度低于同步驱动，需验证认证协议和字符集 | 🟡 中 |
| Python 3.11.9 全环境统一 | 3.11 是稳定版本，生态成熟 | 🟢 低 |
| SQLAlchemy 2.0 + asyncpg + PG 16.4 | 成熟组合 | 🟢 低 |
| Pydantic v2 | API 与 v1 有较大差异，团队需统一 v2 范式 | 🟡 中 |
| MCP SDK 1.9.4 | 官方参考实现，稳定性好 | 🟢 低 |

**总体评价：** Python 侧的版本兼容性最大风险在于 Oracle 11g。oracledb thin 模式 + async + Oracle 11g 是三重不确定性叠加。MySQL 5.6 的 aiomysql 风险相对可控但需验证。系统库（PostgreSQL + SQLAlchemy + asyncpg）链路成熟。

### 3.3 二期扩展性评审

**评分：9/10**

**扩展性优势：**

- `@register_skill` 装饰器注册模式极其简洁，新 Skill 开发者接入成本极低
- `importlib` 动态模块加载是 Python 原生能力，热插拔无需额外框架
- `Protocol` 结构化类型轻量且灵活，不强制继承
- Python 的动态特性使得 Capability 抽象层、分层上下文等设计可快速实现
- JSONB 类型 + `extra_data` 字段为审计日志扩展预留了天然空间
- 新 Skill 可通过 pip install + 配置注册方式接入

**扩展性挑战：**

- 缺乏编译期类型检查，插件契约违规只能在运行时发现
- 动态加载的调试和排错难度高于静态语言
- 团队需建立严格的 Skill 接口文档和测试规范来弥补类型安全的缺失

---

## 四、关键对比分析

### 4.1 MCP 集成成熟度（核心分水岭）

| 对比维度 | Java | Python |
|---|---|---|
| MCP SDK | **未明确指定**（文档空白） | `mcp` 1.9.4（官方参考实现） |
| 协议覆盖度 | 待评估 | 完整覆盖（Tool、Resource、Prompt、Sampling） |
| stdio 模式 | 需自行实现或依赖社区库 | 原生支持，`mcp.Server` 开箱即用 |
| Claude Code 对接 | 需验证 | 已有大量实践案例 |
| SDK 版本跟进 | 社区驱动，可能滞后 | 官方同步发布 |

**评审结论：** 这是本项目最核心的技术决策点。Platform-MCP 的本质定位是 MCP 能力平台，MCP SDK 的成熟度直接决定项目成败。Python 在此维度具有压倒性优势。Java 文档在此关键点上存在空白，需紧急补充。

### 4.2 数据库驱动兼容性

| 对比维度 | Java | Python |
|---|---|---|
| Oracle 11g 驱动成熟度 | ojdbc8 19.x 生产实践丰富 | oracledb thin 模式较新，11g 不在官方矩阵 |
| MySQL 5.6 驱动成熟度 | mysql-connector-java 5.1.49 经典稳定 | aiomysql 0.2.0 成熟度一般 |
| 连接管理 | JDBC + HikariCP 标准 | asyncpg + aiomysql + oracledb async 统一异步 |
| 回退方案 | Spring Boot 版本降级 | thick 模式引入 Oracle Instant Client |

**评审结论：** Java 在数据库驱动层面有明显优势。如果团队的核心关注点是 Oracle 11g/MySQL 5.6 兼容性的确定性，Java 是更安全的选择。

### 4.3 开发效率与迭代速度

| 对比维度 | Java | Python |
|---|---|---|
| 初始开发速度 | 中等（类型安全+样板代码） | 快（动态类型+简洁语法） |
| 重构安全性 | 高（编译期检查） | 中（依赖测试覆盖） |
| 新 Skill 接入速度 | 慢（新模块+SPI配置+构建） | 快（装饰器+模块放入目录） |
| 调试便利性 | 好（IDE 支持完善） | 好（REPL + 丰富的调试工具） |

### 4.4 部署运维对比

| 对比维度 | Java | Python |
|---|---|---|
| 部署包 | 单一 Jar（含所有依赖） | venv + 依赖列表（requirements.txt/pyproject.toml） |
| 进程管理 | systemd 托管单一 Jar | systemd 托管 Web + Claude Code 启动 MCP Server |
| 环境一致性 | 高（Jar 自包含） | 中（依赖系统 Python 版本和 venv） |
| 离线部署 | Jar 直传即可 | 需准备 wheelhouse 离线包 |
| 版本锁定 | Maven 锁定依赖 | pyproject.toml + pip freeze |

---

## 五、专项风险评审

### 5.1 Oracle 11g 兼容性风险（共性问题）

两份方案均存在 Oracle 11g 兼容性风险，这是项目的最大技术不确定性。

**Java 侧风险：** ojdbc8 19.22.0.0 对 11g 为"尽力兼容"——但在生产实践中，ojdbc8 与 Oracle 11g 的组合使用非常广泛，成功率较高。文档的 6 项验证清单覆盖全面。

**Python 侧风险：** oracledb 2.4.1 thin 模式官方支持矩阵从 Oracle 12.1 起步，11g 完全不在官方范围内。加之使用 async 模式，不确定性更高。但文档提供了 thick 模式回退策略。

**建议：** 无论选择哪种技术路线，Oracle 11g 兼容性验证必须作为 Phase 0 最高优先级完成。建议准备真实的 Oracle 11g 测试环境，执行文档中列出的全部验证项。

### 5.2 MCP 协议演进风险

MCP 协议处于快速迭代期。选择非官方 SDK 的风险在于：

- 协议更新时，社区 SDK 的跟进速度可能滞后
- 协议行为差异可能导致与 Claude Code 对接异常
- 社区 SDK 的文档、测试覆盖可能不完善

**建议：** 若选择 Java 路线，必须优先评估 Java MCP SDK 的协议覆盖度和维护活跃度，建议直接与 MCP 协议规范逐项对照。

### 5.3 双入口架构一致性风险（Python 特有）

Python 方案的双入口设计（FastAPI Web + MCP Server stdio）共享业务逻辑层，引入以下一致性风险：

- **内存状态不共享**：Web 进程与 MCP Server 进程各自独立运行，内存中的限流计数器、缓存等不一致
- **部署版本一致性**：两进程共享同一代码目录，更新代码时需确保两进程同步生效
- **日志聚合**：两进程日志需统一收集和关联

**建议：**
- 限流控制以数据库配置表为准（而非内存 Semaphore），确保跨进程一致
- 明确代码更新时的进程重启顺序和策略
- traceId 贯穿两进程日志，便于统一追踪

---

## 六、评审建议与决策参考

### 6.1 综合推荐路线

**推荐：Python（FastAPI + MCP SDK）路线，附带条件。**

推荐理由：

| 优先级 | 理由 |
|---|---|
| 1 | **MCP SDK 是官方参考实现**——对于一个以 MCP 为核心定位的平台，这是决定性的技术优势 |
| 2 | **Skill 插件化扩展更自然**——Python 动态加载、装饰器注册与项目的扩展愿景高度契合 |
| 3 | **合规风险更低**——依赖多为 MIT/Apache，无 Oracle JDBC OTN License 风险 |
| 4 | **开发迭代更快**——新 Skill 接入、风险引擎调整等可快速实现 |

**附带条件（必须满足）：**

| 编号 | 条件 | 不满足时的处理 |
|---|---|---|
| C1 | oracledb 2.4.1 thin async 模式通过 Oracle 11g 全量验证 | 回退至 thick 模式（引入 Oracle Instant Client），重新评估部署复杂度 |
| C2 | aiomysql 通过 MySQL 5.6 兼容性验证 | 评估 asyncmy 或 run_in_executor + PyMySQL 方案 |
| C3 | MCP Python SDK stdio 模式与 Claude Code 完成最小化 PoC | — |
| C4 | 团队 Python 3.11 + FastAPI + SQLAlchemy 2.0 异步范式能力评估通过 | 安排专项培训或调整人员 |

**若 C1 验证失败且回退成本过高**：重新评估 Java 路线。

### 6.2 若选择 Java 路线的必要补充

若团队最终选择 Java 路线，必须补充以下内容：

1. **明确 Java MCP SDK 选型**：调研 mcp-java-sdk 或其他 Java MCP 协议实现库，评估协议覆盖度、社区活跃度、维护状态。此为 Java 方案的生死项。
2. **明确 MCP Server 进程架构**：MCP Server 以 stdio 模式运行，需独立进程。Java 方案需设计双进程架构（Web 进程 + MCP Server 进程），而非假设单进程。
3. **在 PoC 阶段验证 Java MCP 与 Claude Code 的完整对接**：包括 Tool 注册、参数传递、响应格式、错误处理。
4. **锁定 Spring Boot 版本**：PoC 验证后立即删除未选择路线的所有描述，不保留模糊空间。

### 6.3 两份文档的共同改进建议

| 建议 | 说明 |
|---|---|
| **补充性能基线** | 两份文档均未定义一期性能指标（如 SQL 执行并发数、响应时间、MCP 调用 TPS 等），建议增加轻量性能目标 |
| **补充灾备与恢复** | 未描述 PostgreSQL 系统库的备份恢复策略，建议补充 |
| **补充监控告警** | 一期监控列了指标但未定义告警阈值和通知方式，建议补充 |
| **明确 MCP 调用频率限制** | 两份文档均提到限流但未定义默认阈值，建议明确 |
| **补充日志保留策略** | 审计日志和 MCP 调用日志的增长策略提到了分区，但保留周期和归档方式未明确 |
| **明确 API 版本管理** | Web REST API 和 MCP Tool 的版本策略未定义，建议至少明确 URL 路径是否带版本号 |

---

## 七、评分细项

### 7.1 Java 技术架构评分明细

| 维度 | 分项 | 评分 | 评语 |
|---|---|---|---|
| 架构完整性 | 分层设计 | 9 | 接入层、服务层、数据层分层清晰，模块职责边界明确 |
| | 模块划分 | 9 | 7 模块一期方案合理，二期拆分预案有据可依 |
| | 接口规范 | 9 | 统一响应格式、Skill 接口定义完整 |
| 一期可行性 | 技术栈成熟度 | 8 | Spring Boot + MyBatis + HikariCP 均为企业级成熟方案 |
| | MCP 实现 | 4 | 未指定 MCP Java SDK，此为核心缺口 |
| | 认证鉴权 | 9 | Spring Security + Session JDBC 方案成熟 |
| 版本兼容性 | Oracle 11g | 6 | ojdbc8 19.x 对 11g 非官方认证但实践广泛 |
| | MySQL 5.6 | 9 | mysql-connector-java 5.1.49 经典稳定 |
| | Spring Boot 版本 | 6 | 3.2.8 vs 2.7.18 存在不确定性 |
| MCP 集成 | SDK 成熟度 | 3 | Java 侧无官方 MCP SDK，社区方案成熟度待验证 |
| | Claude Code 对接 | 5 | 需独立验证，无参考案例 |
| | stdio 模式 | 4 | Java stdio 进程管理方案未明确 |
| 安全设计 | 认证方案 | 9 | Spring Security 全面可靠 |
| | 密码管理 | 8 | AES-256 + 独立密钥文件方案合理 |
| | 审计覆盖 | 8 | 审计范围全面，从首阶段贯穿建设 |
| 二期扩展性 | 插件化机制 | 8 | SPI 机制成熟但有样板代码开销 |
| | 动态加载 | 7 | 需自定义 ClassLoader，有内存泄漏风险 |
| | 新 Skill 接入 | 7 | 需新 Maven 模块 + SPI 配置 + 构建部署 |
| 部署运维 | 部署简单性 | 9 | Jar + systemd + Nginx 方案成熟 |
| | 环境一致性 | 9 | Jar 自包含，跨环境一致性高 |
| | 离线部署 | 9 | Jar 直传即可 |
| 文档质量 | 结构完整性 | 9 | 22 章覆盖全面，从目标到实施到验收 |
| | 技术深度 | 9 | 版本兼容性分析、驱动验证清单详尽 |
| | 合规分析 | 9 | 开源协议逐项分析，重点关注项清晰 |
| 风险可控性 | 风险识别 | 8 | 关键风险均有识别 |
| | 回退策略 | 7 | Spring Boot 版本有回退但引入不确定性 |
| | 验证计划 | 7 | 验证项明确但缺 MCP SDK 验证 |
| 合规性 | 协议风险 | 6 | Oracle JDBC OTN License 和 MySQL Connector/J GPLv2 需关注 |
| | 商业可行性 | 7 | 内部使用风险可控，但对外分发受限 |

### 7.2 Python 技术架构评分明细

| 维度 | 分项 | 评分 | 评语 |
|---|---|---|---|
| 架构完整性 | 分层设计 | 9 | 双入口架构设计清晰，共享业务逻辑层合理 |
| | 模块划分 | 9 | 7 模块一期方案与 Java 方案对齐，Python Package 组织合理 |
| | 接口规范 | 9 | 统一响应格式 + 错误码规范 + Tool 元数据定义更详细 |
| 一期可行性 | 技术栈成熟度 | 8 | FastAPI + SQLAlchemy + Pydantic 均为主流产线方案 |
| | MCP 实现 | 9 | 官方 MCP SDK，stdio 模式原生支持 |
| | 认证鉴权 | 7 | 需自定义 Session 管理，不如 Spring Security 开箱即用 |
| 版本兼容性 | Oracle 11g | 5 | oracledb thin 官方不支持 11g，async 模式增加不确定性 |
| | MySQL 5.6 | 6 | aiomysql 成熟度一般，需专项验证 |
| | Python/依赖版本 | 8 | Python 3.11.9 稳定，依赖版本锁定策略合理 |
| MCP 集成 | SDK 成熟度 | 10 | 官方参考实现，协议覆盖完整 |
| | Claude Code 对接 | 9 | 已有大量实践案例，stdio 模式是推荐方式 |
| | SDK 版本管理 | 8 | 锁定版本 + 评估后升级策略合理 |
| 安全设计 | 认证方案 | 7 | Session 方案合理但需自行实现持久化 |
| | 密码管理 | 8 | AES-256-GCM + cryptography 库方案安全 |
| | 审计覆盖 | 9 | 分 Sprint 覆盖策略更务实，审计字段设计含 extra_data JSONB 预留扩展 |
| 二期扩展性 | 插件化机制 | 9 | 装饰器 + Protocol 方式极简高效 |
| | 动态加载 | 10 | importlib 原生支持，热插拔无额外框架依赖 |
| | 新 Skill 接入 | 9 | 模块放入目录 + 装饰器注册，接入成本极低 |
| 部署运维 | 部署简单性 | 7 | venv 部署可行但不如 Jar 自包含 |
| | 环境一致性 | 7 | 依赖系统 Python 版本和 venv，一致性管理需规范 |
| | 离线部署 | 6 | 需准备 wheelhouse 离线包，内网部署需额外方案 |
| 文档质量 | 结构完整性 | 9 | 22 章覆盖全面，与 Java 文档对齐 |
| | 技术深度 | 9 | 异步策略统一说明、Pydantic v2 迁移提示、Tool 元数据结构等细节更丰富 |
| | 合规分析 | 9 | 依赖多为 MIT/Apache，风险项更少 |
| 风险可控性 | 风险识别 | 8 | Oracle 11g 风险识别清晰，有验证清单 |
| | 回退策略 | 8 | thick 模式回退方案明确 |
| | 验证计划 | 8 | 8 项验证清单覆盖全面，优先级划分合理 |
| 合规性 | 协议风险 | 9 | 绝大多数依赖为 MIT/Apache，无传染性 |
| | 商业可行性 | 9 | 内部使用无合规障碍 |

---

## 八、最终建议

### 8.1 推荐方案

**推荐选择 Python（FastAPI + MCP SDK）技术路线。**

核心决策依据：

1. **MCP SDK 是项目的根基**：Platform-MCP 的本质定位是 MCP 能力平台。Python MCP SDK 是官方参考实现，是该项目在技术选型上最重要的单一因素。选择非官方 SDK 是在根基上引入不确定性。

2. **扩展性与项目愿景匹配**：项目以 Skill 插件化扩展为长期演进方向。Python 的动态特性（装饰器注册、动态模块加载、Protocol 接口）与这一愿景天然契合。

3. **合规风险更优**：Python 依赖以 MIT/Apache 为主，规避了 Oracle JDBC OTN License 和 MySQL Connector/J GPLv2 的合规复杂性。

### 8.2 决策前置条件

选择 Python 路线须在项目启动前完成以下验证（任一不通过则需重新评估）：

| 优先级 | 验证项 | 通过标准 |
|---|---|---|
| P0 | oracledb 2.4.1 thin async + Oracle 11g 连接与执行 | 文档 6.2 节 6 项验证清单全部通过 |
| P0 | MCP Python SDK stdio + Claude Code 最小化 PoC | 一个 Tool 全链路跑通 |
| P0 | aiomysql + MySQL 5.6 连接与执行 | 基础 CRUD + 事务控制通过 |
| P1 | Python 3.11.9 全环境统一部署验证 | 开发/测试/生产环境部署成功 |

### 8.3 风险缓释措施

| 风险 | 缓释措施 |
|---|---|
| Oracle 11g oracledb thin 不兼容 | PoC 阶段同时验证 thin + thick 两种模式，确定最终路线 |
| aiomysql 对 MySQL 5.6 异常 | 评估 asyncmy 替代方案，或 run_in_executor + PyMySQL 兜底 |
| 团队 Python 异步编程经验不足 | 安排 FastAPI + SQLAlchemy 2.0 Async 专项培训 |
| 双进程状态不一致 | 限流以数据库配置为准，审计以数据库写入为准 |
| 内网离线部署 | 提前准备 wheelhouse 离线安装包，纳入运维手册 |

---

## 附录：评审方法论说明

- **评分体系**：1-10 分制，6 分为及格线，8 分为优秀，9-10 分为卓越
- **评审基准**：从普适的项目立项和技术评审角度出发，重点关注可行性、风险可控性和长期演进性
- **评分侧重**：本项目的核心定位是 MCP 能力平台，因此 MCP 集成成熟度在评审中被赋予最高权重
- **对比基准**：两份文档的系统定位、功能范围、模块划分完全对齐，评分差异反映的是技术路线差异而非设计质量差异
