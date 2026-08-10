# Platform-MCP 代码规范

> **文档名称**：Platform-MCP 代码规范
> **基于文档**：《Platform-MCP 技术架构说明文档》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | v20260603090000 | 2026-06-03 09:00:00 | 初始创建 | 基于技术架构文档，建立项目级代码规范 | castle.zhang |
>
> **适用范围**：Platform-MCP 项目全栈开发（Python / SQL / Vue / TypeScript）

---

## 一、通用原则

### 1.1 核心理念

| 原则 | 含义 |
|------|------|
| KISS | 最简方案优先，不过度工程化 |
| DRY | 重复逻辑提取为公共方法/组件，禁止复制粘贴 |
| YAGNI | 不做未需要的功能，不做投机性抽象 |
| 不可变性 | 优先创建新对象而非修改已有对象，避免隐式副作用 |

### 1.2 文件组织

- 单文件 200-400 行为常规，**800 行为硬上限**
- 高内聚低耦合，按功能/领域组织，而非按类型
- 一起变更的文件应放在一起
- 多个小文件优于少数大文件

### 1.3 命名规范（跨语言）

| 类型 | 规则 | Python 示例 | TypeScript 示例 |
|------|------|-------------|-----------------|
| 包/模块 | 全小写，点分隔 | `platform_mcp.common` | — |
| 类/接口 | PascalCase | `SkillRegistry` | `UserService` |
| 方法/函数 | snake_case / camelCase | `find_by_username` | `findByUsername` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT` | `MAX_RETRY_COUNT` |
| 变量 | snake_case / camelCase | `user_list` | `userList` |
| 布尔变量 | is/has/can 前缀 | `is_active` | `isActive` |

### 1.4 注释规范

- 解释 **WHY**（为什么），而非 WHAT（做什么）
- 自文档化代码优先，仅在逻辑不自明时加注释
- 公共 API 使用 docstring

---

## 二、Python 规范

### 2.1 风格

- 遵循 **PEP 8**
- 类型注解：所有函数签名必须标注参数和返回类型
- 格式化：`black`，导入排序：`isort`，检查：`ruff`

```python
async def execute_sql(
    sql_text: str,
    datasource_code: str,
    env_code: str = "DEV",
    confirm_token: str | None = None,
) -> ExecutionResult:
    ...
```

### 2.2 项目结构

```
platform_mcp/
├── api/             # FastAPI REST 接口
│   ├── routes/
│   └── dependencies/
├── auth/            # 认证鉴权
├── datasource/      # 数据源管理与加解密
├── mcp_server/      # MCP 协议接入、Skill 路由
├── skills/
│   └── database/    # 数据库 Skill（SQL 执行、风险识别）
├── audit/           # 审计日志、调用统计
└── common/          # 异常、响应模型、枚举、工具类
```

**依赖方向**：`api → auth / datasource / skills → audit → common`，禁止反向依赖。

### 2.3 FastAPI 模式

```python
# 路由
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/v1/datasources", tags=["datasource"])

@router.get("", response_model=PageResult[DatasourceVO])
async def list_datasources(
    env_code: str | None = None,
    page: int = 1,
    size: int = 20,
    service: DatasourceService = Depends(get_datasource_service),
):
    return await service.list_datasources(env_code, page, size)
```

- 路径操作使用类型注解和 Pydantic 校验
- 异步 I/O 操作使用 `async/await`
- 并发控制使用 `asyncio.Semaphore`
- 权限控制使用 `Depends()` 注入角色校验：

```python
# 权限中间件模式
from fastapi import Depends, HTTPException
from functools import wraps

async def require_role(*roles: str):
    """角色校验依赖注入"""
    async def _check(session: dict = Depends(get_session)):
        if session.get("role") not in roles:
            raise HTTPException(status_code=403, detail="无权限")
        return session
    return _check

# 使用示例
@router.get("/users", dependencies=[Depends(require_role("admin"))])
async def list_users(...): ...
```

### 2.4 数据模型

```python
# API 请求/响应 — Pydantic v2
from pydantic import BaseModel, field_validator

class DatasourceCreateRequest(BaseModel):
    name: str
    db_type: str  # oracle / mysql
    host: str
    port: int
    env_code: str  # DEV / TEST / PROD

    @field_validator("db_type")
    @classmethod
    def validate_db_type(cls, v: str) -> str:
        if v not in ("oracle", "mysql"):
            raise ValueError("db_type must be oracle or mysql")
        return v

# 内部 DTO — dataclass
from dataclasses import dataclass

@dataclass(frozen=True)
class RiskAssessment:
    level: str       # LOW / MEDIUM / HIGH / CRITICAL
    reasons: list[str]
    requires_confirm: bool
```

### 2.5 SQLAlchemy 2.0 约定

> **架构背景**：SQLAlchemy 2.0 选型理由与异步引擎初始化策略参见 [技术架构说明文档](Python：# Platform-MCP 技术架构说明文档.md) §SQLAlchemy 2.0。本节仅给出代码规范。

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 正确 — 2.0 style
async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

# 禁止 — 1.x style
# db.query(User).filter_by(username=username).first()
```

- 使用 `select()` 而非 `session.query()`
- `AsyncSession` only，禁止同步 Session
- 显式 join，避免隐式加载
- 使用 `Mapped` 类型注解

### 2.6 异步编程规范

```python
import asyncio
from contextlib import asynccontextmanager

# Oracle thick mode — 同步驱动包装为异步
async def execute_oracle_query(conn, sql: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _sync_execute(conn, sql))

# 目标数据库连接 — ephemeral，不长期持有
@asynccontextmanager
async def get_target_connection(datasource: DatasourceConfig):
    conn = await create_connection(datasource)
    try:
        yield conn
    finally:
        await conn.close()

# 并发控制
_semaphore: dict[str, asyncio.Semaphore] = {}

async def get_semaphore(datasource_code: str, max_concurrent: int = 5) -> asyncio.Semaphore:
    if datasource_code not in _semaphore:
        _semaphore[datasource_code] = asyncio.Semaphore(max_concurrent)
    return _semaphore[datasource_code]
```

### 2.7 资源管理

- 文件、连接等资源使用 `async with` 上下文管理器
- 目标数据库连接按需创建，不长期持有连接池
- 系统库使用 SQLAlchemy AsyncSession 连接池

### 2.8 MCP Server 约定

**关键约束**：Database Skill 相关逻辑不得侵入 `mcp_server` 模块。`mcp_server` 仅处理：

- MCP 协议接入（stdio 模式）
- Tool 参数标准化
- 上下文封装
- 响应封装

```python
# mcp_server.py — 仅处理协议
@mcp_server.tool()
async def execute_sql_text(
    sql_text: str,
    datasource_code: str,
    env_code: str,
    confirm_token: str | None = None,
) -> dict:
    """执行 SQL 文本"""
    # 委托给 skills.database 处理
    return await skill_registry.execute(
        "database", "execute_sql_text",
        sql_text=sql_text, datasource_code=datasource_code,
        env_code=env_code, confirm_token=confirm_token,
    )
```

---

## 三、SQL 规范

### 3.1 命名

| 对象 | 规则 | 示例 |
|------|------|------|
| 系统表 | `pmcp_名称` | `pmcp_user`, `pmcp_datasource` |
| 关联表 | `pmcp_实体1_实体2` | `pmcp_user_role`, `pmcp_role_permission` |
| 字段 | snake_case | `user_name`, `inserted_at` |
| 主键 | `id` | `pmcp_user.id` (BIGSERIAL) |
| 唯一索引 | `un_表名_字段名` | `un_pmcp_user_username` |
| 普通索引 | `idx_表名_字段名` | `idx_pmcp_audit_log_inserted_at` |

### 3.2 字段类型选择（PostgreSQL）

| 场景 | 类型 | 说明 |
|------|------|------|
| 主键 | `BIGSERIAL` | 自增主键 |
| 短文本 | `VARCHAR(N)` | 按实际长度定义 |
| 长文本 | `TEXT` | 备注、描述 |
| 精确数值 | `NUMERIC(M,N)` | 金额类，禁止 FLOAT |
| 布尔 | `BOOLEAN` | true/false |
| 时间 | `TIMESTAMP WITH TIME ZONE` | 统一时区 |
| 状态/枚举 | `SMALLINT` | 配合注释说明 |
| JSON 扩展 | `JSONB` | 预留扩展字段 |

### 3.3 Alembic 迁移规范

- 使用 `alembic revision --autogenerate -m "描述"` 自动生成迁移
- **不可修改已执行的迁移文件**
- 新增变更仅创建新迁移文件
- `upgrade()` 和 `downgrade()` 必须成对编写
- 自动生成的迁移需人工审核后提交

```bash
# 生成迁移
alembic revision --autogenerate -m "add pmcp_skill table"

# 执行迁移
alembic upgrade head

# 回退一步
alembic downgrade -1
```

### 3.4 查询规范

- **禁止** `SELECT *`，明确列出字段
- 大表查询必须有索引覆盖或 `LIMIT`
- 分页查询使用 `OFFSET / LIMIT`
- 禁止在 WHERE 条件中对索引列使用函数
- 使用 SQLAlchemy 2.0 `select()` 语法

---

## 四、Vue / TypeScript 规范

### 4.1 组件结构

```vue
<script setup lang="ts">
// 1. 类型导入
import type { Datasource } from '@/types'
// 2. 组件导入
import DatasourceForm from './DatasourceForm.vue'
// 3. API/Store 导入
import { useUserStore } from '@/stores/user'
// 4. Props & Emits
const props = defineProps<{ datasourceId: number }>()
const emit = defineEmits<{ refresh: [] }>()
// 5. 响应式状态
const loading = ref(false)
// 6. 计算属性
const fullName = computed(() => ...)
// 7. 方法
async function fetchDatasource() { ... }
// 8. 生命周期
onMounted(() => fetchDatasource())
</script>

<template>
  ...
</template>

<style scoped>
/* 仅组件级样式 */
</style>
```

### 4.2 组合式 API

- 使用 `<script setup lang="ts">` 语法
- 禁止使用 Options API
- 复用逻辑提取为 Composable（`use*.ts`）

### 4.3 状态管理（Pinia）

```typescript
// stores/user.ts
export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function login(username: string, password: string) { ... }
  function logout() { ... }

  return { user, isLoggedIn, isAdmin, login, logout }
})
```

### 4.4 路由

- 静态路由：登录页、404 等公开页面
- 动态路由：根据用户角色（admin/developer）控制菜单显隐
- 路由守卫：`beforeEach` 校验 Session 和权限

### 4.5 HTTP 请求（Axios）

```typescript
// utils/request.ts
const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: true,  // Session 模式
})

// 响应拦截：统一错误处理
request.interceptors.response.use(
  res => res.data,
  error => {
    if (error.response?.status === 401) {
      router.push('/login')
    }
    return Promise.reject(error)
  }
)
```

### 4.6 不可变性

```typescript
// 正确：使用展开运算符
const updatedUser = { ...user, name: 'New Name' }
const newList = [...items, newItem]

// 禁止：直接修改
user.name = 'New Name'  // BAD
items.push(newItem)      // BAD
```

### 4.7 TypeScript 类型

- 禁止使用 `any`，至少使用 `unknown` 并做类型收窄
- API 响应定义完整类型接口
- 使用 `type` 定义联合类型，`interface` 定义对象结构

---

## 五、安全规范

### 5.1 必要安全检查

| 检查项 | 说明 |
|--------|------|
| SQL 注入 | 目标库使用参数化查询，禁止拼接 SQL |
| XSS | 前端输出转义，后端输入过滤 |
| 路径穿越 | SQL 文件执行校验绝对路径在白名单内，禁止符号链接跟随 |
| 密钥泄露 | 禁止硬编码密钥，使用独立 secret 文件 |
| 输入校验 | 所有外部输入使用 Pydantic 校验 |
| 审计日志 | 关键操作记录操作人、时间、IP、内容 |

### 5.2 密钥管理

- **禁止**在源码中写入密码、API Key、Token
- 生产环境使用独立 secret 文件（权限 0600）
- 开发环境配置放 `settings-dev.yml`（已加入 `.gitignore`）
- 加解密方案详见《Platform-MCP 加解密方案说明》

---

## 六、Git 提交规范

格式：`<type>: <description in Chinese> yyyymmdd by castle`

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变行为） |
| `docs` | 文档变更 |
| `test` | 测试相关 |
| `chore` | 构建/配置/工具 |

---

## 七、IDE 配置

- **IntelliJ IDEA**：Python 插件、Claude Code 插件
- **代码格式化**：`black` + `isort`（Python），Prettier（Vue/TS）
- **类型检查**：`mypy`（Python），`tsc --noEmit`（TypeScript）

---

## 八、日志记录规范

### 8.1 日志级别

| 级别 | 用途 |
|------|------|
| ERROR | 系统错误，需要立即关注 |
| WARNING | 业务异常，可恢复的异常情况 |
| INFO | 关键操作记录（登录、数据变更、SQL 执行等） |
| DEBUG | 调试信息，仅开发环境启用 |
| TRACE | 详细追踪，仅问题排查时临时启用 |

### 8.2 日志框架

- **loguru**（主日志库）
- 禁止使用 `print()`，统一使用 `logger`

### 8.3 日志格式

```python
from loguru import logger

# 配置 JSON 结构化输出（生产环境）
logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    serialize=True,  # JSON 格式
)
```

### 8.4 敏感信息过滤

- 密码、Token、Secret Key 不得出现在日志中（使用 `***` 脱敏）
- 禁止使用 `print()`，统一使用 `logger`

### 8.5 异常日志

```python
# 正确 — 包含完整堆栈
logger.error("SQL 执行失败: datasource={}, sql={}", datasource_code, sql_text[:100], exc=e)

# 禁止 — 仅打印消息丢失堆栈
# logger.error(str(e))
```

---

## 九、REST API 设计规范

### 9.1 URL 命名

- 小写、连字符分隔、RESTful 风格
- 格式：`/api/v1/resources`
- 资源名使用名词复数形式

### 9.2 HTTP 方法

| 方法 | 用途 |
|------|------|
| GET | 查询资源 |
| POST | 创建资源 |
| PUT | 全量更新资源 |
| PATCH | 部分更新资源 |
| DELETE | 删除资源 |

### 9.3 统一响应格式

```python
# common/response.py
class ResponseBase(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None
    trace_id: str | None = None
    timestamp: int | None = None  # Unix 毫秒时间戳

class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
```

- code=0 表示成功，非 0 为业务错误码
- 错误码由枚举统一管理

### 9.4 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

### 9.5 分页参数

- `page`（从 1 开始）、`size`（默认 20）
- 响应含 `total`（总记录数）/ `pages`（总页数）

### 9.6 排序参数

- `sort` 格式：`字段名,asc` 或 `字段名,desc`

---

## 十、错误处理规范

### 10.1 业务异常

```python
# common/exceptions.py
class BaseError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message

class BusinessError(BaseError):
    """业务逻辑异常（用户可见）"""
    pass

class AuthError(BaseError):
    """认证/授权异常"""
    pass

class DataSourceError(BaseError):
    """数据源操作异常"""
    pass

class SkillError(BaseError):
    """Skill 执行异常"""
    pass

class PathSecurityError(BaseError):
    """路径安全异常（文件路径穿越等）"""
    pass
```

- 全局异常处理器：FastAPI `@app.exception_handler()`
- 异常码枚举 `ErrorCode` 统一管理错误码

### 10.2 参数校验

- 使用 Pydantic `@field_validator` + FastAPI `Depends()`
- `RequestValidationError` 处理返回 HTTP 400

### 10.3 异常消息格式

- 中文，面向开发人员
- 包含足够上下文定位问题（如：操作类型、数据源编码、失败原因）

### 10.4 禁止行为

- 禁止 `except:` 后静默忽略，至少记录 WARNING 日志
- 外部调用失败必须记录请求和响应摘要

---

## 十一、技术栈版本要求

| 技术 | 版本 | 说明 |
|------|------|------|
| Python | 3.11.9 | 全环境统一锁定 |
| FastAPI | 0.115.0 | Web 框架 |
| Pydantic | 2.8.2 | 数据校验 |
| SQLAlchemy | 2.0.35 | ORM（AsyncSession） |
| Alembic | 1.13.2 | 数据库迁移 |
| oracledb | 2.4.1 | Oracle 驱动（thick 模式） |
| aiomysql | 0.2.0 | MySQL 异步驱动 |
| cryptography | 43.0.1 | 加解密 |
| mcp SDK | 1.9.4 | MCP 协议 |
| loguru | 0.7.2 | 日志 |
| httpx | 0.27.2 | HTTP 客户端 |
| tenacity | 9.0.0 | 重试/容错 |
| PyYAML | 6.0.2 | YAML 配置解析 |
| Gunicorn | 23.0.0 | WSGI 服务器 |
| Uvicorn | 0.30.6 | ASGI 服务器 |
| Vue 3 | 3.5.34 | 前端框架 |
| TypeScript | 6.0.2 | 前端类型系统 |
| Vite | 8.0.12 | 前端构建工具 |
| Element Plus | 2.8.1 | UI 组件库 |
| Pinia | 2.2.2 | 状态管理 |
| Axios | 1.7.4 | HTTP 客户端 |
| PostgreSQL | 16.4 | 系统数据库 |
