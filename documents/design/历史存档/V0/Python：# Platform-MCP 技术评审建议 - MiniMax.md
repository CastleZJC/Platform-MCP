# Platform-MCP 技术评审建议 - MiniMax

- **评审对象**：技术架构说明文档 + 架构说明（正式版）
- **评审维度**：一期可行性 · 软件兼容性 · 二期扩展性
- **日期**：2026-05-28

---

## 一、一期可行性评审

### 1.1 总体判断：可行

Python 单体模块化架构定位清晰，与项目阶段匹配。

- **FastAPI** 作为 Web + MCP 双框架是合理选择，既有优秀的 REST API 能力，又可通过 Starlette 接入 MCP 协议
- **Gunicorn + UvicornWorker** 生产部署方案成熟，适合内部轻量服务场景
- **PostgreSQL 16.4** 作为系统库选型恰当，其 JSON/JSONB 支持对结构化审计日志有直接益处
- **虚拟环境 + systemd + Nginx** 跳过 Docker 的决策符合简单优先原则，降低运维学习成本

### 1.2 需关注的一期风险点

#### 风险 A：Oracle 11g 驱动验证未完成
文档明确指出 `oracledb 2.4.1` 的 thin 模式对 Oracle 11g 兼容性需专项验证，但全文未给出验证结果。

- **thin 模式**（纯 Python，无 Oracle Client）是方向，但 Oracle 11g 发布于 2007 年，驱动对其支持存在不确定窗口
- 建议：项目启动前**必须**完成 Oracle 11g thin 模式验证，输出验证报告。如遇阻，thick 模式作为 fallback 方案不应被视为延期项
- 文件路径参考（驱动层）：`app/skills/database/` 下的 Oracle 连接封装

#### 风险 B：SQL 多语句拆分边界模糊
文档描述"按分号拆分"并提及需处理注释、字符串常量、PL/SQL 块，但未定义**第一版明确不支持的场景**。

- `execute_sql_file` 的多语句执行如遇 PL/SQL 块边界问题，可能导致执行失败或数据不一致
- 建议：明确第一版**不支持**的 SQL 模式（如 `CREATE OR REPLACE` 多语句块），在文档中以"已识别限制"方式固化，避免实施歧义
- 文件路径参考（执行层）：`app/sql_executor/`

#### 风险 C：Session vs JWT 决策待确认
文档推荐 Session 方案，但未明确最终决策理由。

- Session 方案在内部管理场景确实更易控，但需确认 Web 端与未来可能的 API 调用方（如 Claude Code 直连 MCP 不走 Web）之间不存在会话断裂
- 建议：确认 Web Session 与 MCP 请求鉴权是否共用同一认证体系，或完全解耦

### 1.3 一期可行性结论

架构设计本身无根本性障碍，主要风险集中在 **Oracle 11g 驱动验证进度** 和 **SQL 执行边界定义**，建议以此作为项目启动前的 P0 确认项。

---

## 二、软件兼容性评审

### 2.1 Python 3.11.9 基线

Python 3.11.9 作为统一基线合理——3.11 是当前 LTS 区间内的成熟版本，3.11.9（2024年4月）在安全性和驱动兼容性上均有良好积累。锁定小版本是正确决策，可避免开发与生产环境差异。

### 2.2 Oracle 11g 兼容性

| 检查项 | 状态 | 说明 |
|---|---|---|
| oracledb 2.4.1 thin 模式 | ⚠️ 待验证 | 文档已识别此项，建议专项验证后固化 |
| oracledb thick 模式 fallback | ✅ 可行 | 如 thin 不支持，thick 模式有 Oracle Client 兜底 |
| 基本 SELECT/DML | ⚠️ 待验证 | 需实际环境联调确认 |
| 存储过程调用 | ⚠️ 待验证 | Oracle 11g 存储过程差异较大，需重点测 |
| 中文字符集 | ⚠️ 待验证 | AL32UTF8/ZHS16GBK 兼容性需实测 |
| 日期时间字段 | ⚠️ 待验证 | Oracle DATE 类型精度与 Python datetime 映射需确认 |

**结论**：Oracle 11g 兼容性尚无定论，需实际联调验证。建议将"Oracle 11g 驱动验证通过"列为项目启动门槛。

### 2.3 MySQL 5.6 兼容性

| 检查项 | 状态 | 说明 |
|---|---|---|
| PyMySQL 1.1.1 基础连接 | ✅ 基本可行 | 纯 Python 实现，部署简单，但需实测 |
| mysqlclient 2.2.4 fallback | ✅ 可行 | C 驱动更稳定，性能更好 |
| 旧版认证协议（mysql_native_password） | ⚠️ 需关注 | MySQL 5.6 默认认证协议需在连接参数中显式配置 |
| 字符集（utf8mb4） | ⚠️ 需配置 | 5.6 对 utf8mb4 支持弱于 8.x，需确认连接串配置 |
| 多语句执行 | ✅ 基本可行 | MySQL 5.6 支持，但需在 SQL 拆分层正确处理 |
| 时区参数 | ⚠️ 需配置 | `serverTimezone` 连接参数需显式指定 |

**结论**：MySQL 5.6 兼容性优于 Oracle 11g，PyMySQL 作为主力驱动可行，但旧认证协议和时区参数需在实施阶段显式配置。

### 2.4 系统库兼容性

- **PostgreSQL 16.4**：成熟稳定，`psycopg 3.2.1` 驱动支持良好，无特殊风险
- **前端 Node.js 20.15.1 LTS**：长期支持版本，选型合理
- **Vue 3.4.38 / Element Plus 2.8.1**：成熟版本，技术风险低

### 2.5 兼容性汇总

| 组件 | 兼容性结论 | 行动项 |
|---|---|---|
| Python 3.11.9 | ✅ 无风险 | 统一版本即可 |
| Oracle 11g + oracledb | ⚠️ 高风险待验证 | 启动前完成专项验证 |
| MySQL 5.6 + PyMySQL | ⚠️ 中风险可管控 | 实施阶段关注认证协议和时区配置 |
| PostgreSQL 16.4 | ✅ 无风险 | 系统库选型合理 |
| Vue 3 + Element Plus | ✅ 无风险 | 成熟技术栈 |

---

## 三、二期扩展性评审

### 3.1 架构扩展性基础：优秀

MCP 层采用"统一入口 + Skill 插件式扩展"设计，二期扩展性基础扎实：

- **Skill 统一接口**（`skill_name / list_tools / validate / execute / support`）在文档中已明确定义，这是扩展性的核心保障
- **Skill Registry** 机制（`app/skill_registry`）提供了新增 Skill 的注册-发现-路由能力，新增 Skill 无需修改 MCP Core
- **统一上下文结构**（trace_id、request_id、operator、skill_name、tool_name...）为多 Skill 共用审计和监控打好了数据基础
- **Monitor 和 Audit 模块**设计为多 Skill 共用，第一期完成后可无缝支持新增 Skill 的状态归集

### 3.2 二期扩展路径评估

#### 路径一：新增 Database 相关 Skill（如 SQL 优化建议 Skill）
- 扩展成本：低
- 理由：`skills/database/` 可继承现有 sql_executor 和 risk_engine，新增 Skill 如 `sql_advice` 只需注册新 Tool，无需改动核心

#### 路径二：File / Log / Config Skill（文档已预留）
- 扩展成本：中
- 理由：需新增 `app/skills/file/`、`app/skills/log/` 等模块，Monitor/Audit 层已有通用设计，只需扩展数据模型
- 建议：提前在 `app/common/` 中预留跨 Skill 共用的响应模型，避免后续补丁

#### 路径三：Multi-Skill 编排（跨 Skill 调用链）
- 扩展成本：高（当前未规划）
- 理由：现有架构中 Skill 间调用链路无统一编排机制，如二期需要"file skill 读取 SQL → database skill 执行"的编排能力，需在 `app/skill_registry` 中新增编排层
- 建议：此项作为架构预留，如二期有此需求，提前在架构评审时确认，当前一期设计无需覆盖

### 3.3 二期扩展性风险

#### 风险：Skill 接口标准需严格执行
文档定义了 Skill 统一接口，但如新开发人员未严格遵循（如 execute 签名不一致），Registry 路由层需做兼容处理。

- 建议：在一期即将 Skill 接口标准固化到代码骨架中，并配合单元测试保证新 Skill 实现符合接口契约

#### 风险：Audit 日志 Schema 随 Skill 扩展可能需演进
当前审计日志以 MCP 调用为核心字段，新增 Skill（如 file/log）可能需要扩展字段（如文件名、操作路径等）。

- 建议：`sys_audit_log` 表设计时预留 `extra_data JSONB` 字段，为后续扩展提供灵活性，避免 Schema 变更成本

### 3.4 二期扩展性结论

架构设计为二期扩展留有良好基础，Skill 插件化思路清晰。主要扩展性风险在于 **Audit 日志 Schema 预留** 和 **Skill 接口契约执行**，建议在一期实施时通过代码骨架和单元测试固化接口标准。

---

## 四、综合建议

### 4.1 一期启动前必须确认项（按优先级）

| 优先级 | 确认项 | 负责 |
|---|---|---|
| P0 | Oracle 11g thin 模式验证报告 | 数据库团队 |
| P0 | MySQL 5.6 认证协议和时区配置方案 | 后端开发 |
| P1 | Session vs JWT 最终方案确认 | 架构师 |
| P1 | SQL 多语句拆分第一版明确不支持场景 | 后端开发 |
| P2 | `sys_audit_log.extra_data` JSONB 字段预留 | 后端开发 |

### 4.2 总体评价

Platform_MCP 架构设计合理，Python 单体模块化路线适合项目定位，技术选型成熟度整体较高。一期最大风险来自 Oracle 11g 驱动兼容性验证未闭环，其余技术决策均有充分依据。二期扩展性设计预留充分，Skill 插件化思路清晰。

建议在完成上述 P0/P1 确认项后正式启动项目实施。

---

## 五、参考文件

- `Python：# Platform_MCP 技术架构说明文档 - GPT.md`（技术架构层）
- `Python：# Platform_MCP 架构说明（正式版）- GPT.md`（架构概述层）
