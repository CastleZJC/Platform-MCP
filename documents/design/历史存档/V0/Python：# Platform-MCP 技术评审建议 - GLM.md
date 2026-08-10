# Platform_MCP 技术评审建议 - Glm2

- **评审依据**：《Platform_MCP 架构说明（正式版）- GPT2》+《Platform_MCP 技术架构说明文档 - GPT2》
- **评审范围**：一期功能实现、版本兼容性、二期扩展能力
- **评审立场**：基于 Python 技术路线的工程落地可行性，从风险识别与架构改进角度出发
- **评审时间**：2026-05-27
- **评审人**：Glm2（AI 辅助评审）

---

# 1. 评审概述

## 1.1 两份文档的关系与定位

| 文档 | 定位 | 覆盖内容 | 受众 |
|---|---|---|---|
| 架构说明（正式版）- GPT2 | 项目级顶层架构文件 | 系统定位、总体架构、模块划分、MCP 扩展原则、安全设计、部署方案、实施边界 | 项目经理、架构师 |
| 技术架构说明文档 - GPT2 | 技术级落地指导文件 | Python 技术栈版本锁定、模块职责细化、接口设计、数据表设计、测试基线、运维要求 | 架构师、开发、测试、运维 |

两份文档已从先前 Java/Spring Boot 路线全面切换至 Python 路线（Python 3.11.9 + FastAPI），这是一个关键的技术方向变更。Python 路线在 MCP SDK 生态、Skill 动态扩展、部署简化方面具有天然优势，但也引入了新的技术风险。以下评审基于 Python 路线展开。

## 1.2 评审原则

- **不推翻核心架构方向**：Python 单体模块化 + Skill 插件式扩展的总体路线合理
- **聚焦 Python 生态特有风险**：与 Java 路线的技术风险完全不同，需重新审视
- **提供可操作建议**：每条建议给出具体的行动项和 Python 生态下的实现路径
- **承认 Python 优势**：MCP Python SDK 成熟度高、Skill 扩展更灵活，是正确的技术方向

---

# 2. 一期功能实现评审

## 2.1 MCP 进程模型与部署拓扑 — 文档最大盲区

### 现状

两份文档多次提到"MCP Server 接收请求""MCP Tool 接口入口""MCP 统一入口"，但从未明确：

- MCP Server 以何种进程模式运行（stdio / SSE / Streamable HTTP）
- MCP Server 与 FastAPI Web 服务是同一进程还是独立进程
- Claude Code 如何发现和连接本系统的 MCP Server

### 评审意见

这是本系统**最核心的架构决策**，但恰恰是文档中最大的空白。

MCP 协议的运行模式决定了整个部署拓扑：

| 模式 | 说明 | 与 FastAPI 关系 |
|---|---|---|
| **stdio** | Claude Code 启动 MCP Server 为子进程，通过 stdin/stdout 通信 | 独立进程，需单独入口点 |
| **SSE（HTTP）** | MCP Server 作为 HTTP 服务运行，Claude Code 通过 HTTP 连接 | 可与 FastAPI 共存或独立 |
| **Streamable HTTP** | MCP 协议较新的传输模式，单端口 HTTP | 可与 FastAPI 共存 |

Claude Code 的 MCP Server 配置方式是在 `claude_desktop_config.json` 或 `.claude/settings.json` 中声明：

```json
{
  "mcpServers": {
    "Platform-MCP": {
      "command": "python",
      "args": ["-m", "platform_mcp.mcp_server"],
      "env": { ... }
    }
  }
}
```

或 HTTP 模式：

```json
{
  "mcpServers": {
    "Platform-MCP": {
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

**关键矛盾**：文档描述的部署方案是 `Gunicorn + Uvicorn Worker + systemd + Nginx`，这是标准的 FastAPI Web 部署方式。但 MCP stdio 模式要求 MCP Server 作为 Claude Code 的子进程运行。两者**无法用同一进程同时服务**。

### 建议

1. **推荐采用双入口架构：**

```
platform_mcp/
├── main.py                 # FastAPI Web 入口（Gunicorn + systemd）
├── mcp_server.py           # MCP Server 入口（stdio，由 Claude Code 启动）
├── core/                   # 共享业务逻辑（两个入口共用）
│   ├── skill_registry.py
│   ├── skills/
│   ├── sql_executor.py
│   ├── audit.py
│   └── ...
```

- `main.py`：FastAPI 应用，负责 Web 管理接口，由 systemd 托管
- `mcp_server.py`：MCP Server，使用官方 `mcp` Python SDK，由 Claude Code 以 stdio 模式启动
- `core/`：两个入口共享的业务逻辑层，不依赖任何传输协议

2. **项目启动前必须完成 MCP 集成 PoC：**
   - 使用 `mcp` Python SDK 创建最简 MCP Server
   - 配置 Claude Code 连接并调用一个 Tool
   - 验证 stdio 通信链路完整可用
   - 预计耗时：1-2 天

3. **备选方案**：若团队倾向于单进程部署，可评估 MCP SSE/Streamable HTTP 模式，将 MCP 端点集成到 FastAPI 中。但需验证 Claude Code 对 HTTP 模式 MCP Server 的支持成熟度。

---

## 2.2 MCP 认证断层 — 权限模型的核心矛盾

### 现状

技术架构文档明确要求 MCP 层进行"权限校验"，权限控制维度覆盖"用户、角色、Skill、Tool、环境、数据源"。正式版文档在调用上下文中包含 `operator` 字段。

### 评审意见

**MCP 协议本身不传递用户身份信息。** Claude Code 调用 MCP Tool 时，请求中不包含用户名、Token 或任何身份标识。这意味着：

- MCP Server 无法知道"谁在调用"
- "按用户做权限校验"在 MCP 层无法实现
- `operator` 字段无数据来源

这是 MCP 架构与"按用户权限管控"之间的**根本性矛盾**。

### 建议

针对这个矛盾，有以下几种策略，建议在启动前选定一种：

**方案 A：MCP 调用不做用户级鉴权（推荐，适合首期）**

- MCP 层信任 Claude Code 的调用者身份，不做用户级权限判断
- 通过配置控制 MCP Server 可访问的数据源范围（白名单机制）
- 审计日志中的 `operator` 记录为 MCP 系统级标识（如 `mcp://claude-code`）
- 用户级权限控制仅在 Web 管理端实施

**方案 B：通过 Claude Code 侧传入操作者标识**

- 在 MCP Tool 参数中增加 `operator` 字段，由调用方传入
- MCP Server 记录但不验证该字段（不可信来源）
- 适用于审计追踪，不适用于权限控制

**方案 C：MCP Server 绑定 Token 机制（复杂，首期不推荐）**

- Claude Code 配置中传入预共享 Token
- MCP Server 验证 Token 并映射到系统用户
- 实现复杂，且 Claude Code 配置文件可能泄露 Token

**一期建议采用方案 A**，将权限控制从 MCP 层下沉到数据源配置层（哪些数据源允许 MCP 访问），而非用户层。在文档中明确修正"MCP 层按用户鉴权"的描述。

---

## 2.3 模块粒度 — 13 模块偏细，建议一期精简

### 现状

技术架构文档规划了 13 个模块：`api`、`auth`、`datasource`、`crypto`、`mcp_core`、`skill_api`、`skill_registry`、`skills/database`、`sql_executor`、`risk_engine`、`audit`、`monitor`、`common`。

### 评审意见

一期仅落地一个 Skill（database），13 个模块拆分过细。且模块设计带有明显的 Java/Spring 风格（接口层 + 注册中心 + 实现层三层分离），在 Python 中有更简洁的实现方式：

- `skill_api`：Python 中用 `typing.Protocol` 或 `abc.ABC` 即可定义接口，不需要独立模块
- `skill_registry`：Python 中用装饰器 + 字典即可实现注册，不需要独立模块
- `mcp_core`：MCP Python SDK 已提供请求接收和 Tool 分发能力，无需自建路由层
- `risk_engine`：一期只有关键词 + 正则匹配，作为 `skills/database` 的内部函数即可
- `monitor`：与 `audit` 职责重叠（MCP 调用状态统计 vs MCP 调用日志记录）

### 建议

**一期建议精简为 6-7 个包：**

| 合并后包 | 包含原模块 | 说明 |
|---|---|---|
| `platform_mcp.api` | api | FastAPI Web 管理接口 |
| `platform_mcp.auth` | auth | 认证鉴权 |
| `platform_mcp.datasource` | datasource + crypto | 数据源管理与密码加解密天然耦合 |
| `platform_mcp.mcp_server` | mcp_core + skill_api + skill_registry | MCP SDK 集成 + Skill 基类定义 + 装饰器注册 |
| `platform_mcp.skills.database` | skills/database + sql_executor + risk_engine | 数据库 Skill 内聚，执行器和风控是其内部组件 |
| `platform_mcp.audit` | audit + monitor | 审计日志与状态统计统一管理 |
| `platform_mcp.common` | common | 通用工具 |

**Python 惯用的 Skill 注册方式：**

```python
# platform_mcp/mcp_server/registry.py
_SKILLS: dict[str, SkillProtocol] = {}

def register_skill(name: str):
    """装饰器：注册 Skill"""
    def wrapper(cls):
        _SKILLS[name] = cls()
        return cls
    return wrapper

# platform_mcp/skills/database/__init__.py
from platform_mcp.mcp_server.registry import register_skill

@register_skill("database")
class DatabaseSkill:
    def list_tools(self) -> list[ToolDef]: ...
    async def execute(self, tool: str, params: dict, ctx: Context) -> Result: ...
```

当二期扩展时，从 `mcp_server` 包中拆分 `skill_api` 和 `skill_registry` 为独立子包，有真实多 Skill 场景校验接口设计。

---

## 2.4 实施优先级 — 审计应贯穿，非独立阶段

### 现状

技术架构文档将实施分为三阶段：

- 第一阶段：框架 + 认证 + 数据源 + 加密 + 系统库
- 第二阶段：MCP Core + Database Skill + SQL 执行器 + 审计日志
- 第三阶段：状态页 + 风险增强 + 兼容联调 + 运维

### 评审意见

审计被放在第二阶段，意味着第一阶段的认证、数据源管理、加密操作在开发期间**没有审计能力支撑**。两份文档均强调"审计优先"，但实施计划与原则矛盾。

### 建议

**审计写入能力应从第一阶段开始同步建设：**

| 阶段 | 内容 | 审计覆盖 |
|---|---|---|
| **第一阶段** | 框架 + 认证 + 数据源 + 加密 + 系统库 + **审计基础设施** | 登录日志、数据源变更、加密操作 |
| **第二阶段** | MCP Server + Database Skill + SQL 执行器 + 风控 | MCP 调用日志、SQL 执行日志、风险记录 |
| **第三阶段** | 状态页 + 兼容联调 + 运维 | 调用量统计、运行状态 |

一期审计模块只需提供：
- 统一的 `AuditLogger` 类（写入 `sys_audit_log` 表）
- 各模块通过 `await audit_logger.log(action, detail)` 写入审计记录
- 不需要完整的审计查询页面（可放第三阶段），但写入能力必须提前

---

## 2.5 异步策略 — FastAPI 异步与同步 DB 驱动的矛盾

### 现状

技术架构文档选择 FastAPI（异步框架）+ PyMySQL（同步驱动）+ oracledb（支持异步）+ SQLAlchemy 2.0（支持异步）。未明确异步策略。

### 评审意见

FastAPI 的核心优势是 async/await 异步处理，但：

- **PyMySQL 是纯同步驱动**，在 async 函数中直接调用会阻塞事件循环
- **oracledb 支持 async 模式**（`oracledb.connect` vs `oracledb.connect_async`）
- **SQLAlchemy 2.0 支持 `AsyncSession`**，但需要异步驱动配合（如 `asyncpg` for PostgreSQL）

如果混合使用同步和异步数据库访问，会导致：
- 同步驱动阻塞 FastAPI 的事件循环，影响并发性能
- 部分路由异步、部分路由同步，代码风格不统一

### 建议

**推荐统一异步策略：**

| 访问目标 | 推荐方案 | 说明 |
|---|---|---|
| PostgreSQL 系统库 | `SQLAlchemy AsyncSession` + `asyncpg` | 系统库访问量可控，异步足够 |
| Oracle 11g | `oracledb` async 模式 | 官方支持异步，需验证 11g 兼容性 |
| MySQL 5.6 | `aiomysql` 或 `run_in_executor` | PyMySQL 无异步版本，需替代方案 |

**对 MySQL 5.6 的两种处理方式：**

- **方案 A（推荐）**：使用 `aiomysql`（PyMySQL 的异步 fork），API 兼容，可无缝替代
- **方案 B**：保持 PyMySQL，通过 FastAPI 的 `run_in_executor` 将同步调用包装为异步

若选方案 A，技术架构文档中的 MySQL 驱动应将 `aiomysql` 列为优先选择，`PyMySQL` 降为备选。

---

## 2.6 SQL 文件执行安全 — 路径校验缺失

### 现状

`execute_sql_file` Tool 接收文件路径，读取本地 `.sql` 文件执行。两份文档均未提及路径安全约束。

### 评审意见

接受外部传入的文件路径读取本地文件，存在以下安全风险：

- **路径穿越**：传入 `../../etc/passwd` 或类似路径读取非预期文件
- **符号链接攻击**：通过符号链接指向敏感文件
- **任意文件读取**：MCP 调用方可能利用此能力读取服务器任意文件

### 建议

```python
import pathlib

ALLOWED_SQL_DIRS = ["/opt/Platform-MCP/sql-scripts/", "/tmp/Platform-MCP/"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def validate_sql_path(file_path: str) -> pathlib.Path:
    path = pathlib.Path(file_path).resolve()

    # 校验白名单目录
    if not any(str(path).startswith(d) for d in ALLOWED_SQL_DIRS):
        raise ValueError(f"路径超出允许范围: {file_path}")

    # 校验扩展名
    if path.suffix.lower() != ".sql":
        raise ValueError(f"仅允许 .sql 文件: {file_path}")

    # 校验文件大小
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"文件超过大小限制: {file_path}")

    return path
```

1. 配置允许读取的根目录白名单
2. 使用 `Path.resolve()` 解析真实路径，防止符号链接攻击
3. 校验解析后的绝对路径是否在白名单目录内
4. 限制文件扩展名为 `.sql`
5. 限制文件大小（建议默认 10MB）

---

## 2.7 风险引擎范围控制 — 一期不应过度投入

### 现状

风险引擎规划了：语句类型识别、DDL/DML 判断、WHERE 缺失检测、全表操作检测、DROP/TRUNCATE 高危标记、解析失败记录。

### 评审意见

对一期而言，功能范围合理，但实现深度需控制：

- Python 生态中的 SQL 解析库（如 `sqlparse`、`python-sqloxide`）对 Oracle PL/SQL、存储过程支持有限
- 正则 + 关键词匹配对常见场景够用，但需承认局限性
- 风险等级判定（LOW/MEDIUM/HIGH/CRITICAL）的阈值需与业务方对齐

### 建议

1. **一期采用 `sqlparse` + 正则 + 关键词匹配**，不引入重量级 AST 解析器
2. **明确标注风险引擎的局限性**：返回结果中标注 `confidence: "low" | "medium" | "high"`，告知调用方风险识别为辅助参考
3. **高危操作默认阻断**：DROP、TRUNCATE、DELETE WITHOUT WHERE 需要在 MCP Tool 参数中显式传入 `confirm_risk=True` 才允许执行
4. **解析失败的 SQL 统一标记为 HIGH 风险**，保守处理
5. **风险规则可配置化**：通过 `sys_system_config` 表管理规则开关，无需改代码即可调整

---

## 2.8 Web 管理端页面优先级

### 现状

首期规划 9 个页面：登录页、概览页、数据源管理、密码加解密、用户管理、角色权限管理、审计日志、MCP 调用状态、系统配置。

### 评审意见

一期同时建设 9 个页面工作量较大。且项目定位明确"Web 端以管理为主"，部分页面可简化或延后。

### 建议

**一期必须交付（5 个核心页面）：**

| 页面 | 优先级 | 理由 |
|---|---|---|
| 登录页 | P0 | 无认证则无法使用 |
| 数据源管理页 | P0 | MCP 调用的前置依赖 |
| 密码加解密页 | P0 | 数据源配置的配套能力 |
| 审计日志页 | P0 | 合规与可追溯性要求 |
| 用户管理页 | P1 | 基本的账号管理 |

**一期可简化或延后（4 个页面）：**

| 页面 | 建议 | 理由 |
|---|---|---|
| 系统概览页 | 延后至三期 | 首期数据量少，概览价值有限 |
| 角色权限管理页 | 简化为一期仅支持预置角色 | 完整 RBAC 在首期不需要 |
| MCP 调用状态页 | 延后至三期 | 审计日志页可暂时替代查看调用记录 |
| 系统配置页 | 延后至三期 | 初期配置项少，可通过配置文件管理 |

---

# 3. 版本兼容评审

## 3.1 Python 3.11.9 — 正确的基线选择

### 现状

技术架构文档明确锁定 Python 3.11.9，要求开发、测试、生产统一。

### 评审意见

Python 3.11 是当前最稳妥的选择：

- 性能：3.11 比 3.10 快 10-60%（Faster CPython 项目成果）
- 稳定：3.11 已有充足的社区验证期
- 避坑：3.12 有若干 breaking changes（如 `datetime.datetime.utcnow()` 弃用、`importlib` 行为变更），3.11 不涉及
- 生态：所有选用的库均兼容 3.11

### 建议

1. 锁定 3.11.9 不变
2. 在 `pyproject.toml` 中声明 `requires-python = ">=3.11.9,<3.12"`
3. 使用 `uv` 或 `pip` + `requirements.txt` 锁定依赖
4. 不允许任何环境使用 3.12+，避免隐蔽的兼容问题

---

## 3.2 oracledb 2.4.1 + Oracle 11g — 最大兼容风险

### 现状

技术架构文档推荐 `oracledb 2.4.1`，使用 thin 模式连接 Oracle 11g，并提到"若 thin 模式存在限制，评估切换 thick 模式"。

### 评审意见

`python-oracledb`（即 `oracledb` 包）是 Oracle 官方新一代 Python 驱动，替代了老旧的 `cx_Oracle`。它有两种模式：

| 模式 | 说明 | Oracle 11g 兼容性 |
|---|---|---|
| **Thin（默认）** | 纯 Python 实现，无需 Oracle Client | 对 Oracle 11g 的支持有限，部分高级特性不支持 |
| **Thick** | 需要 Oracle Instant Client 库 | 兼容性好，但引入系统级依赖 |

**核心风险**：oracledb thin 模式对 Oracle 11g 的兼容性并非完整覆盖。根据 oracledb 官方文档，thin 模式支持 Oracle 12.1 及以上服务器。**Oracle 11g 不在 thin 模式的官方支持矩阵中。**

这意味着：
- 基本连接可能成功（Oracle 网络协议向下兼容）
- 但高级特性（如高级安全选项、连接池、特定数据类型）可能失败
- 行为可能在不同 patch level 的 Oracle 11g 之间不一致

### 建议

1. **启动前必须完成 Oracle 11g 兼容性 PoC（最高优先级）：**

| 验证项 | 验证内容 | 通过标准 |
|---|---|---|
| 连接建立 | thin 模式连接 Oracle 11g | 连接成功 |
| SELECT 查询 | 常规查询含中文 | 结果正确，无乱码 |
| DML 执行 | INSERT/UPDATE/DELETE | 影响行数正确 |
| 事务控制 | commit/rollback | 行为正确 |
| 存储过程 | IN/OUT/REF CURSOR | 参数传递和结果返回正确 |
| 日期时间 | DATE/TIMESTAMP 类型 | 读写正确，时区处理正确 |
| CLOB/BLOB | 大字段读写 | 内容完整 |
| 字符集 | AL32UTF8 / ZHS16GBK | 无乱码 |

2. **若 thin 模式连接 Oracle 11g 失败或存在功能缺失：**
   - 切换为 thick 模式，服务器需安装 Oracle Instant Client 11.2+
   - 在部署方案中增加 Oracle Instant Client 安装步骤
   - 在 `oracledb.init_oracle_client()` 中配置 lib_dir 路径

3. **在 `sql_executor` 中设计数据库类型适配层：**

```python
class DatabaseDialect(Protocol):
    def wrap_pagination(self, sql: str, offset: int, limit: int) -> str: ...
    def call_procedure(self, conn, name: str, params: list) -> Any: ...

class OracleDialect(DatabaseDialect): ...
class MySQLDialect(DatabaseDialect): ...
```

将 Oracle 特有逻辑（分页、存储过程调用、日期函数等）隔离在策略类中，避免散落在业务代码里。

---

## 3.3 PyMySQL 1.1.1 + MySQL 5.6 — 合理但需调整异步策略

### 现状

技术架构文档推荐 `PyMySQL 1.1.1`（优先）和 `mysqlclient 2.2.4`（备选）。

### 评审意见

PyMySQL 是纯 Python 实现，部署简单，对 MySQL 5.6 兼容性良好。但：

- PyMySQL 是**同步驱动**，与 FastAPI 异步模型冲突（见 2.5 节）
- MySQL 5.6 使用 `mysql_native_password` 认证协议，PyMySQL 1.1.1 支持
- `mysqlclient` 需要 C 编译环境，部署复杂度高，不建议作为首选

### 建议

1. **将 MySQL 驱动调整为 `aiomysql`（优先）+ `PyMySQL`（备选）**
   - `aiomysql` 是 PyMySQL 的异步 fork，API 几乎一致
   - 在 FastAPI 中直接使用 async/await，无需 `run_in_executor`
2. **启动前验证 `aiomysql` + MySQL 5.6 的兼容性**，重点测试：
   - 认证协议（mysql_native_password）
   - 时区参数
   - 字符集处理（utf8/utf8mb4）
   - 多语句执行支持
3. **在数据源配置中记录驱动类型**，便于后续支持 MySQL 8.x 时区分 `caching_sha2_password` 认证

---

## 3.4 SQLAlchemy 2.0 — 范式迁移风险

### 现状

技术架构文档选择 SQLAlchemy 2.0.35 作为 PostgreSQL 系统库 ORM。

### 评审意见

SQLAlchemy 2.0 是一次**重大范式变更**：

- 查询 API 从 `session.query(User).filter(...)` 变为 `session.execute(select(User).where(...))`
- 新增 `AsyncSession` 和 `asyncio` 扩展
- `declarative_base()` 移至 `orm` 模块
- `sessionmaker` 推荐使用 `sessionmaker(class_=AsyncSession)`

如果团队成员之前使用的是 SQLAlchemy 1.x，需要学习成本。

### 建议

1. **一期统一使用 SQLAlchemy 2.0 新 API**，不混用 1.x 风格
2. 在项目 README 或开发规范中附 SQLAlchemy 2.0 迁移速查表
3. 代码审查中重点关注旧 API 的使用
4. 系统库使用 `AsyncSession` + `asyncpg`，与 FastAPI 异步模型统一

---

## 3.5 Pydantic v2 — 团队认知对齐

### 现状

技术架构文档选择 Pydantic 2.8.2 + pydantic-settings 2.4.0。

### 评审意见

Pydantic v2 用 Rust 重写了核心，性能大幅提升，但 API 有 breaking changes：

- `@validator` → `@field_validator`
- `class Config` → `model_config = ConfigDict(...)`
- `.dict()` → `.model_dump()`
- `.parse_obj()` → `.model_validate()`
- 自定义类型需要不同的注册方式

FastAPI 0.115+ 已完全适配 Pydantic v2，组合无兼容问题。

### 建议

1. 一期统一使用 Pydantic v2 API，禁止使用 v1 兼容层
2. 利用 `pydantic-settings` 管理配置，替代手动解析 YAML：

```python
from pydantic_settings import BaseSettings

class AppSettings(BaseSettings):
    app_name: str = "Platform-MCP"
    debug: bool = False
    database_url: str
    secret_key_path: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
```

3. 使用 Pydantic 模型定义 MCP Tool 的输入输出，与 FastAPI 的请求/响应模型保持一致的风格

---

## 3.6 前端技术栈 — 整体合理，建议锁定版本

### 现状

Vue 3.4.38 + Vite 5.4.2 + Element Plus 2.8.1 + TypeScript 5.5.4。

### 评审意见

前端技术栈选型合理，版本组合稳定。需注意：

- Element Plus 版本迭代较快，小版本升级可能有组件行为变化
- Vue 3.4 → 3.5+ 的 `defineModel` 等 API 变化
- Vite 5 → 6 可能在项目期间发布

### 建议

1. 一期**锁定当前版本组合**，在 `package.json` 中使用精确版本号（不用 `^` 前缀）
2. 在一期交付后统一评估升级
3. 前端构建产物由 Nginx 托管，不依赖 Node.js 运行时，版本锁定对运维无影响

---

## 3.7 PostgreSQL 16.4 + psycopg 3.2.1 — 建议切换为 asyncpg

### 现状

技术架构文档推荐 psycopg 3.2.1 作为 PostgreSQL 驱动。

### 评审意见

`psycopg`（即 psycopg3）是 PostgreSQL 官方 Python 驱动，成熟可靠。但：

- 若采用统一异步策略（见 2.5 节），SQLAlchemy AsyncSession 推荐使用 `asyncpg` 作为驱动
- `asyncpg` 性能优于 psycopg3 的异步模式（纯异步设计，无兼容性包袱）
- SQLAlchemy 2.0 官方文档推荐 `asyncpg` 作为异步 PostgreSQL 驱动

### 建议

1. **系统库驱动调整为 `asyncpg`**（配合 SQLAlchemy AsyncSession）
2. `psycopg3` 保留为可选的同步场景备选
3. 连接字符串从 `postgresql://` 切换为 `postgresql+asyncpg://`

---

# 4. 二期扩展评审

## 4.1 Skill 插件机制 — 一期固化接口，二期增强发现能力

### 现状

Skill 通过 `skill_api` 定义接口、`skill_registry` 负责注册。扩展方式为"新增 Skill 模块 + 注册到 Registry"。

### 评审意见

一期静态注册完全够用。Python 的动态特性使 Skill 扩展比 Java 更简单，但需要为二期设计合理的插件发现机制。

### 建议

1. **一期即固化 Skill 基类接口（Protocol 或 ABC）：**

```python
from typing import Protocol

class SkillProtocol(Protocol):
    @property
    def name(self) -> str: ...

    def list_tools(self) -> list[ToolDef]: ...
    async def execute(self, tool: str, params: dict, ctx: Context) -> Result: ...
    async def initialize(self) -> None: ...     # 预留：Skill 初始化
    async def shutdown(self) -> None: ...       # 预留：Skill 清理
```

2. **二期增强方向：**
   - 支持通过配置文件/数据库控制 Skill 启用禁用
   - 支持从独立 Python 包中自动发现 Skill（entry_points 或 importlib）
   - Skill 配置元数据（版本、描述、依赖、所需权限）存储在数据库中
   - 每个 Skill 独立的异常隔离（一个 Skill 报错不影响其他 Skill）

---

## 4.2 长耗时 SQL 执行 — 缺少异步执行模型

### 现状

两份文档均未提及长时间 SQL 执行的响应策略。

### 评审意见

部分 SQL 执行（大表 DDL、批量数据处理、复杂报表查询）可能耗时数分钟甚至更久。MCP 协议层面同步等待完整结果会导致：

- Claude Code 侧超时断开
- 用户无法感知执行进度
- MCP Server 进程资源被占用

### 建议

1. **一期实现基础超时控制：**
   - SQL 执行设置超时上限（默认 300 秒），超时自动终止
   - 全局 `query_timeout` 和 `connection_timeout` 可通过 `sys_system_config` 配置

2. **一期实现异步执行模式：**
   - `execute_sql_file/text` 支持参数 `async_mode=True`
   - 异步模式下立即返回 `execution_id`
   - 结果通过 `get_execution_status(execution_id)` 查询
   - 执行状态存储在 PostgreSQL 中（`execution_status` 字段：PENDING / RUNNING / SUCCESS / FAILED / TIMEOUT）

3. **二期评估：**
   - MCP 协议的流式返回能力（如果支持）
   - Web 端实时展示执行进度（WebSocket / SSE）

---

## 4.3 限流与熔断 — 防止 MCP 调用压垮目标数据库

### 现状

两份文档均未提及限流和熔断机制。

### 评审意见

MCP 调用方（Claude Code）的调用频率和并发度不受本系统控制。Claude Code 可能：

- 并发发起多个 SQL 执行请求
- 循环调用 `execute_sql_text` 执行批量操作
- 对同一生产库的并发查询导致锁竞争或性能下降

Python 生态中，`asyncio.Semaphore` 即可实现轻量级并发控制，无需引入外部框架。

### 建议

1. **一期实现基础限流（纯 Python 标准库即可）：**

```python
import asyncio

# 全局并发控制
_global_semaphore = asyncio.Semaphore(10)

# 按数据源并发控制
_datasource_semaphores: dict[str, asyncio.Semaphore] = {}

async def execute_with_limit(datasource: str, coro):
    async with _global_semaphore:
        sem = _datasource_semaphores.setdefault(
            datasource, asyncio.Semaphore(3)
        )
        async with sem:
            return await coro
```

2. **限流参数存储在 `sys_system_config` 表中，支持动态调整**

3. **二期评估更精细的控制：**
   - 按调用方的速率限制
   - 按数据源的熔断（连续失败 N 次后暂停该数据源连接）
   - 集成 `circuitbreaker` Python 库或自实现简单熔断

---

## 4.4 目标数据库连接池生命周期

### 现状

技术架构文档明确提出"根据执行请求按需建立连接，不长期持有连接池"。

### 评审意见

按需连接策略对一期合理，避免长期持有大量老库连接。但需补充：

- **连接超时控制**：目标数据库连接建立超时、SQL 执行超时
- **连接泄漏检测**：按需建立的连接如果异常未关闭，需兜底回收
- **并发连接控制**：对同一目标数据库的同时连接数上限

### 建议

1. **一期使用 `contextlib.asynccontextmanager` 确保连接生命周期安全：**

```python
@asynccontextmanager
async def get_target_connection(datasource_config):
    conn = None
    try:
        conn = await create_connection(datasource_config, timeout=30)
        yield conn
    finally:
        if conn:
            await conn.close()
```

2. **二期按数据源引入轻量连接池：**
   - 使用 SQLAlchemy 的 `create_async_engine` 为高频数据源创建独立连接池
   - 池化参数按数据源独立配置（pool_size、max_overflow、pool_timeout）
   - 空闲超时自动回收
   - 低频数据源保持按需连接

---

## 4.5 多环境隔离策略

### 现状

通过 `env_code`（如 DEV/TEST/PROD）标识数据源环境。权限控制按 Skill + Tool + 数据源 + 环境维度。

### 评审意见

逻辑隔离（env_code）对一期够用，但存在以下风险：

- **误操作生产库**：env_code 仅是标签，不阻止代码层面的错误
- **配置错误**：开发环境数据源配置错误指向生产库 IP，权限校验仍通过
- **缺少操作水位分离**：高危操作（DROP/TRUNCATE）在测试环境可执行，在生产环境需额外管控

### 建议

1. **一期：**
   - 生产库（`env_code=PROD`）的数据源默认标记为 `protected=True`
   - 受保护数据源的所有 DDL 和 DELETE WITHOUT WHERE 操作强制标记为 CRITICAL 风险
   - 受保护数据源的高危操作需要 MCP Tool 参数中显式传入 `confirm_risk=True`
   - 在 MCP Server 配置中可设置 `protected_datasource_write_enabled=False` 全局阻断生产库写入

2. **二期：**
   - 引入 Web 端二次确认机制：生产库高危操作需在 Web 管理端确认后放行
   - 操作窗口控制：限制高危操作只能在指定时间段执行

---

## 4.6 MCP 协议版本演进 — SDK 迭代风险

### 现状

文档未提及 MCP SDK 版本管理和协议演进策略。

### 评审意见

MCP（Model Context Protocol）是一个快速演进中的协议，Python SDK (`mcp` 包) 处于活跃开发期。需关注：

- SDK 大版本更新可能有 breaking changes
- 协议层面可能新增传输模式、Tool 能力
- Claude Code 对 MCP 协议的支持版本需保持同步

### 建议

1. **一期锁定 MCP SDK 具体版本**，在 `pyproject.toml` 或 `requirements.txt` 中使用精确版本
2. **将 MCP SDK 升级评估纳入每个迭代周期**
3. **业务逻辑与 MCP 协议层严格解耦**（这是 2.1 节建议双入口 + 共享 core 层的核心原因）
4. 当 MCP SDK 升级时，只需修改 `mcp_server.py` 入口，不影响 `core/` 层的业务逻辑

---

# 5. 综合建议清单

## 5.1 按优先级分级的关键建议

### P0 — 启动前必须完成

| # | 建议 | 理由 | 负责角色 |
|---|---|---|---|
| 1 | 完成 Claude Code + MCP Python SDK 集成 PoC（一个 Tool 全链路跑通） | 验证核心调用链可行性，决定双入口架构 | 架构师/后端 |
| 2 | 完成 oracledb thin 模式 + Oracle 11g 兼容性 PoC | Oracle 11g 不在 thin 模式官方支持矩阵中 | 后端 |
| 3 | 完成 aiomysql + MySQL 5.6 兼容性 PoC | 验证异步驱动对老版本 MySQL 的支持 | 后端 |
| 4 | 确定 MCP 认证策略（推荐方案 A：MCP 层不做用户级鉴权） | 解决 MCP 协议无用户上下文与文档要求权限校验的矛盾 | 架构师 |

### P1 — 一期开发中必须落实

| # | 建议 | 理由 | 负责角色 |
|---|---|---|---|
| 5 | 将 13 模块精简为 6-7 个，采用 Python 惯用模式 | 降低一期复杂度，避免 Java 风格过度设计 | 架构师 |
| 6 | 审计写入能力从第一阶段开始建设 | 落实"审计优先"原则 | 后端 |
| 7 | `execute_sql_file` 增加路径白名单校验 | 防止路径穿越和任意文件读取 | 后端 |
| 8 | 统一异步策略：asyncpg + aiomysql + oracledb async | 避免 FastAPI 异步 + 同步驱动的矛盾 | 架构师/后端 |
| 9 | 风险引擎一期用 sqlparse + 正则，不引入 AST | 控制实现复杂度 | 后端 |
| 10 | SQL 执行增加超时控制和异步执行模式 | 防止长时间阻塞 MCP Server | 后端 |
| 11 | 实现基础并发限流（asyncio.Semaphore） | 防止 MCP 调用压垮目标数据库 | 后端 |
| 12 | Web 页面精简为 5 个核心页面 | 控制前端工作量 | 前端 |
| 13 | 生产库数据源标记为受保护并增加高危操作阻断 | 防止误操作 | 后端 |

### P2 — 一期交付前建议完成

| # | 建议 | 理由 | 负责角色 |
|---|---|---|---|
| 14 | 统一 Skill 基类接口并固化（含 initialize/shutdown 生命周期） | 为二期扩展打基础 | 架构师 |
| 15 | 锁定前端版本组合（精确版本号，不用 ^ 前缀） | 避免开发期间版本漂移 | 前端 |
| 16 | 审计日志表设计时间分区 | 应对数据量增长 | 后端/DBA |
| 17 | 锁定 MCP SDK 精确版本 | 防止 SDK 迭代引入 breaking changes | 后端 |
| 18 | 完成 systemd + Nginx + 双入口部署文档 | 保障交付质量 | 运维 |

---

## 5.2 启动前验证清单

以下为项目正式启动前**必须全部通过**的验证项：

| # | 验证项 | 验证方法 | 通过标准 | 预计耗时 |
|---|---|---|---|---|
| V1 | Python 3.11.9 虚拟环境 + FastAPI 空项目启动 | 创建 FastAPI 项目并启动 | 无报错，`/docs` 页面可访问 | 0.5 天 |
| V2 | Claude Code + MCP Python SDK + stdio 模式 | 编写最简 MCP Server，Claude Code 配置并调用一个 Tool | Claude Code 成功调用并显示结果 | 1 天 |
| V3 | oracledb thin + Oracle 11g 连接 | 编写测试连接 Oracle 11g 执行 `SELECT 1 FROM DUAL` | 连接成功，结果正确 | 1 天 |
| V4 | oracledb thin + Oracle 11g 存储过程 | 编写测试调用带 IN/OUT 参数的存储过程 | 参数传递正确，结果返回 | 0.5 天 |
| V5 | aiomysql + MySQL 5.6 连接 | 编写测试连接 MySQL 5.6 执行 `SELECT 1` | 连接成功，结果正确 | 0.5 天 |
| V6 | aiomysql + MySQL 5.6 多语句 | 编写测试执行 `SELECT 1; SELECT 2;` | 两条语句均执行成功 | 0.5 天 |
| V7 | SQLAlchemy AsyncSession + asyncpg + PostgreSQL 16.4 | 创建系统库表并执行基本 CRUD | 增删改查均正常 | 0.5 天 |
| V8 | cryptography AES-256-GCM 加解密 | 编写加解密测试用例 | 加密后可正确解密 | 0.5 天 |

**预计总验证耗时：5-6 个工作日**

若 V3（oracledb thin + Oracle 11g）验证失败，需额外 1-2 天切换为 thick 模式验证。

---

# 6. 总结

Platform_MCP 从 Java 路线切换至 Python 路线是一个**正确的决策**。Python 在 MCP SDK 生态、Skill 动态扩展、部署简化方面具有明显优势。两份 GPT2 架构文档在系统定位、模块职责、技术选型、安全设计等方面覆盖全面，核心架构方向（Python 单体模块化 + MCP 统一入口 + Skill 插件式扩展）是合理的。

本次评审识别的主要改进方向：

### 一期落地层面
1. **MCP 进程模型**：文档最大盲区，需明确 MCP Server（stdio）与 FastAPI（HTTP）双入口共存架构
2. **MCP 认证断层**：MCP 协议无用户上下文与文档要求权限校验存在根本矛盾，需调整权限模型
3. **模块精简**：一期 13 模块过细，建议 6-7 个，采用 Python 惯用模式（装饰器注册 + Protocol）
4. **审计贯穿**：审计写入能力从第一阶段开始建设
5. **异步统一**：asyncpg（PostgreSQL）+ aiomysql（MySQL）+ oracledb async（Oracle）

### 版本兼容层面
6. **Oracle 11g + oracledb thin**：最大兼容风险，thin 模式对 11g 非官方支持，启动前必须 PoC
7. **SQLAlchemy 2.0 + Pydantic v2**：两个库均为重大范式变更，需团队统一认知

### 二期扩展层面
8. **长耗时 SQL + 限流**：异步执行模型和并发控制是一期必须建设的基础能力
9. **Skill 接口固化**：一期即固化含生命周期的基类接口，为二期动态发现奠定基础
10. **MCP SDK 版本管理**：MCP 协议快速迭代，业务逻辑需与协议层严格解耦

以上建议不改变项目整体方向，旨在降低一期 Python 路线落地的工程风险，为二期扩展奠定更扎实的技术基础。

---

*本文档由 Glm2 基于《Platform_MCP 架构说明（正式版）- GPT2》与《Platform_MCP 技术架构说明文档 - GPT2》进行技术评审后生成。*
