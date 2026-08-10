# Platform-MCP 测试规范文档

> **文档名称**：Platform-MCP 测试规范文档
> **基于文档**：《Platform-MCP 技术架构说明文档》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | v20260603090000 | 2026-06-03 09:00:00 | 初始创建 | 基于技术架构文档，建立项目测试规范体系 | castle.zhang |
>
> **适用对象**：后端开发、前端开发、测试工程师
> **文档用途**：规范 Platform-MCP 项目全阶段测试策略、覆盖率要求与质量门禁标准

---

## 一、总则

### 1.1 测试目标与原则

| 原则 | 含义 |
|------|------|
| 测试先行 | 核心业务逻辑先编写测试用例，再实现功能代码 |
| 自动化优先 | 所有测试必须可自动化执行，禁止仅依赖手工验证 |
| 快速反馈 | 单元测试单次执行不超过 5 秒，全量测试不超过 3 分钟 |
| 隔离性 | 测试之间互不依赖，可任意顺序执行 |
| 可重复性 | 同一测试在任何环境执行结果一致 |

### 1.2 测试覆盖率要求

| 模块 | 最低覆盖率 | 推荐覆盖率 | 说明 |
|------|-----------|-----------|------|
| skills.database | 90% | 95% | 核心业务逻辑（SQL 执行、风险识别） |
| mcp_server | 90% | 95% | MCP 协议接入与 Skill 路由 |
| auth | 90% | 95% | 认证鉴权 |
| common | 90% | 95% | 工具类与公共组件 |
| datasource | 80% | 90% | 数据源管理（含加解密） |
| api | 80% | 90% | REST 接口层 |
| audit | 80% | 90% | 审计日志 |
| 前端（Store/工具） | 80% | 90% | 核心 Store 与工具函数 |

- 覆盖率统计以**行覆盖率（Line Coverage）** 为准
- 纯 Pydantic Model（请求/响应）可豁免单元测试

### 1.3 测试范围界定

| 测试类型 | 范围 | 负责方 |
|---------|------|--------|
| 单元测试 | 单个函数/方法级逻辑验证 | 开发人员 |
| 集成测试 | 跨模块交互（Service + DB / API + Service） | 开发人员 |
| MCP Tool 测试 | MCP 协议端到端调用验证 | 开发人员 |
| 安全测试 | 认证授权、注入防护、路径穿越 | 开发人员 + 测试工程师 |
| E2E 测试 | 完整业务流程（前端到后端链路） | 测试工程师 |

### 1.4 测试代码质量原则（强制）

> 当覆盖率门禁与下列原则冲突时，**原则优先**。覆盖率不达标应通过补充真实业务用例解决，不得通过构造无意义测试凑数。

| 原则 | 含义 |
|------|------|
| 不为覆盖率硬凑 | 测试必须验证真实业务行为；分支/行覆盖是测试设计正确的**结果**，不是测试设计的目的 |
| 实现方式符合原有设计 | Mock、Stub、Fixture 必须尊重被测代码的真实依赖结构；**测试适配代码，不是代码迁就测试** |
| 不脱离原有业务场景 | 测试输入、调用路径、断言点必须可追溯到需求文档、API 契约或实际调用方 |

#### 反模式与正确做法

| 反模式（禁止） | 正确做法 |
|---------------|---------|
| 为命中某条 `if` 分支，构造生产代码中永远不会出现的入参（如把 `db_type` 填成不存在的 `"foo"`） | 围绕真实业务用例（DEV Oracle / TEST MySQL / PROD Oracle）设计输入 |
| 为让 Mock 容易写，反向修改生产代码（如把 `from X import Y` 改成 `import X`，或新增仅为测试存在的 getter 函数） | 调整测试的 Mock 路径去适配生产代码的导入语义 |
| 为某 service 方法构造生产调用方从未使用过的入参组合，只为覆盖参数解析分支 | 删除该分支（若确属死代码），或补充真实调用方缺失的入参用例 |
| 在测试中关闭校验、跳过异常路径，只为让流程跑通拿到 `success` 断言 | 真实触发异常路径并断言异常类型、错误码、消息 |
| 为凑覆盖率新增"测试通过即可"的占位测试（如 `test_dummy()`） | 拒绝占位测试；覆盖率不足时回归业务用例查漏补缺 |

#### 适用判定流程

编写新测试前，依次回答：

1. **业务追溯**：本测试验证的业务行为，在需求文档 / API 契约 / Skill 工具签名中能找到对应吗？
   - 能 → 继续；不能 → 停下，先核对需求
2. **路径真实**：Mock 后的调用链是否与生产代码的实际依赖一致？
   - 一致 → 继续；不一致 → 调整 Mock，不改生产代码
3. **断言有效**：断言点是否对业务结果有意义（而非"函数被调用过"）？
   - 是 → 继续；否 → 重写断言或删除测试

任一回答为"否"且无法修复时，**该测试不得提交**。

---

## 二、测试架构（Test Architecture）

### 2.1 测试目录结构

```
tests/
├── unit/           # 单元测试（隔离，mock）
├── integration/    # 集成测试（跨模块，httpx AsyncClient）
├── security/       # 安全测试（认证、注入、路径穿越）
├── performance/    # 性能测试（P95 延迟）
├── mcp/            # MCP Tool 调度测试
├── compatibility/  # 兼容性测试（Oracle/MySQL 驱动、故障隔离）
└── conftest.py     # 全局 fixture 配置
```

### 2.2 Key Fixtures 说明

| Fixture | 位置 | 作用 |
|---------|------|------|
| `mock_db_session` | tests/unit/conftest.py | AsyncMock DB 会话，用于单元测试 |
| `mock_request` | tests/unit/conftest.py | Mock FastAPI Request 对象 |
| `crypto` | tests/unit/conftest.py | 提供测试用 AES 密钥 |
| `test_key` | tests/unit/conftest.py | 提供 API Key 测试值 |
| `session_manager` | tests/unit/conftest.py | Mock SessionManager |
| `admin_client` | tests/integration/conftest.py | httpx AsyncClient，override admin 权限 |
| `dev_client` | tests/integration/conftest.py | httpx AsyncClient，override developer 权限 |
| `mock_db` | tests/integration/conftest.py | 默认返回空结果的 AsyncMock session |

### 2.3 Integration Test Pattern

集成测试使用 `httpx.AsyncClient` 覆盖 FastAPI `Depends`：

```python
# tests/integration/conftest.py
@pytest.fixture
async def admin_client():
    async def override_get_db():
        return mock_db_session  # AsyncMock

    async def override_get_current_user():
        return admin_user  # Mock admin user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
```

### 2.4 Unit Test Mock Target Rules

Mock 目标选择遵循以下规则（避免 patch 错误路径）：

| 规则 | 说明 | 示例 |
|------|------|------|
| 1 | `from X import Y` 在模块顶层 → patch `importing_module.Y` | `from platform_mcp.config import get_settings` → patch `platform_mcp.mcp_server.get_settings` |
| 2 | `from X import Y` 在函数内 → patch `X.Y`（源模块） | 函数内 `from auth.service import validate_api_key` → patch `platform_mcp.auth.service.validate_api_key` |
| 3 | `import oracledb` 在函数内 → 使用 `patch.dict(sys.modules, {"oracledb": mock})` | 封装 Oracle 驱动导入 |
| 4 | Oracle 测试中的 `asyncio.run_in_executor` → 使用 `async def run_sync(_, fn): return fn()` 同步执行闭包以覆盖代码 | |

**反模式**：一律 patch `platform_mcp.config.get_settings`，不管目标模块实际如何导入。

---

## 三、后端测试规范（Python / FastAPI）

### 2.1 测试框架选型

| 框架 | 版本 | 用途 |
|------|------|------|
| pytest | 8.3.2 | 测试引擎 |
| pytest-asyncio | 0.23.8 | 异步测试支持 |
| httpx | 0.27.2 | FastAPI TestClient（异步） |
| pytest-cov | 5.0.0 | 覆盖率报告 |

安装依赖：

```bash
pip install pytest pytest-asyncio httpx pytest-cov
```

pytest 配置（`pyproject.toml`）：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--cov=platform_mcp --cov-report=term-missing --cov-report=html"
```

### 2.2 单元测试规范

#### 命名规则

测试方法命名格式：`test_方法名_场景_预期结果`

```python
# 正确
async def test_execute_sql_high_risk_returns_confirmation():
    ...

async def test_validate_sql_drop_statement_returns_critical():
    ...

# 禁止
def test_1():
    ...
```

#### 断言规范

```python
# 正确
result = await risk_engine.assess("DROP TABLE users;")
assert result.level == "CRITICAL", "DROP 操作应标记为 CRITICAL 风险"
assert result.requires_confirm is True

# 禁止：无断言的测试
async def test_something():
    await service.do_something()  # 缺少断言
```

#### Mock 规范

- 仅 Mock **直接依赖**，禁止跨层 Mock
- 使用 `unittest.mock.AsyncMock` 异步 Mock

```python
from unittest.mock import AsyncMock, patch

async def test_execute_sql_calls_datasource():
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = [{"id": 1}]

    with patch("platform_mcp.datasource.manager.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await sql_executor.execute("SELECT 1", "test_ds", "DEV")

        mock_conn.execute.assert_called_once_with("SELECT 1")
        assert len(result.rows) == 1
```

### 2.3 集成测试规范

```python
import pytest
from httpx import AsyncClient, ASGITransport
from platform_mcp.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

async def test_login_success(client):
    response = await client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin123",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
```

#### 数据库测试策略

| 场景 | 方案 | 说明 |
|------|------|------|
| 系统 DB 测试 | PostgreSQL 测试实例 + Alembic 迁移 | 验证真实 SQL 行为 |
| 目标 DB（Oracle） | Mock 连接 | 不依赖实际 Oracle 实例 |
| 目标 DB（MySQL） | Mock 连接 | 不依赖实际 MySQL 实例 |

### 2.4 MCP Tool 测试

验证 MCP 协议端到端调用：

```python
from mcp import ClientSession
from platform_mcp.mcp_server import mcp_server

async def test_mcp_tool_execute_sql_text():
    """验证 MCP Tool execute_sql_text 端到端调用"""
    async with ClientSession() as session:
        result = await session.call_tool("execute_sql_text", {
            "sql_text": "SELECT 1 FROM DUAL",
            "datasource_code": "test_oracle",
            "env_code": "DEV",
        })
        assert result.isError is False
```

---

## 三、前端测试规范（Vue 3 / TypeScript）

### 3.1 测试框架选型

| 框架 | 版本 | 用途 |
|------|------|------|
| Vitest | 2.1.9 | 测试引擎 |
| @vitest/coverage-v8 | 2.1.9 | 覆盖率 |
| @vue/test-utils | 2.4.6 | Vue 组件挂载 |
| happy-dom | 17.4.4 | DOM 环境 |
| @vue/test-utils | 2.x | Vue 组件挂载 |
| happy-dom | 17.x | 轻量 DOM 环境 |

### 3.2 组件测试规范

```typescript
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DatasourceList from './DatasourceList.vue'

describe('DatasourceList', () => {
  it('renders_datasource_names_whenDataLoaded', () => {
    const datasources = [
      { id: 1, name: 'DEV Oracle', db_type: 'oracle', env_code: 'DEV' },
      { id: 2, name: 'TEST MySQL', db_type: 'mysql', env_code: 'TEST' },
    ]
    const wrapper = mount(DatasourceList, {
      props: { datasources, loading: false },
    })
    expect(wrapper.text()).toContain('DEV Oracle')
    expect(wrapper.text()).toContain('TEST MySQL')
  })

  it('renders_empty_state_whenNoData', () => {
    const wrapper = mount(DatasourceList, {
      props: { datasources: [], loading: false },
    })
    expect(wrapper.text()).toContain('暂无数据')
  })
})
```

### 3.3 Store（Pinia）测试规范

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '../user'

describe('useUserStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('logout_clearsUser', () => {
    const store = useUserStore()
    store.$patch({ user: { id: 1, username: 'admin', role: 'admin' } })
    store.logout()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
  })
})
```

---

## 四、测试数据管理

### 4.1 测试数据准备策略

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| 代码内构建 | 少量数据 | 直接构造对象 |
| Fixture 文件 | 复杂数据 | JSON/YAML 文件 |
| Factory 函数 | 灵活组合 | Builder 工厂函数 |
| Alembic seed | 数据库测试 | 初始化默认数据 |

### 4.2 数据清理策略

- **后端**：集成测试使用事务回滚或独立测试数据库
- **前端**：每个测试前重置 Pinia Store 和 Mock 状态
- **禁止**测试数据残留

---

## 五、安全测试要求

### 5.1 SQL 注入防护验证

```python
async def test_sql_injection_is_blocked():
    malicious = "'; DROP TABLE users; --"
    result = await risk_engine.assess(malicious)
    assert result.level in ("HIGH", "CRITICAL")
```

### 5.2 路径穿越防护验证

```python
async def test_file_path_traversal_is_blocked():
    with pytest.raises(PathSecurityError):
        await file_validator.validate("../../etc/passwd")
```

### 5.3 权限校验测试（双角色）

| 角色 | 必测场景 |
|------|---------|
| admin | 访问所有接口成功、PROD 数据源可调用 |
| developer | Skill 新增进入"待审核"、PROD 数据源返回权限不足、密码加密页不可见 |

### 5.4 风险等级验证

| 风险等级 | 必测 SQL | 预期行为 |
|---------|---------|---------|
| LOW | `SELECT * FROM users` | 正常执行 |
| MEDIUM | `INSERT INTO users VALUES (...)` | 正常执行 |
| HIGH | `DELETE FROM users` (无 WHERE) | 要求二次确认 |
| CRITICAL | `DROP TABLE users` | 强制二次确认 |

### 5.5 加密验证

- 数据源密码写入数据库为密文（AES: 前缀）
- 正确密钥可解密还原
- 审计日志中不包含明文密码

---

## 六、测试执行与质量门禁

### 6.1 覆盖率验证

```bash
# 后端
pytest --cov=platform_mcp --cov-report=html --cov-report=term-missing

# 前端
cd ui && npm run test:coverage
```

### 6.2 质量门禁标准

| 检查项 | 标准 | 阻断级别 |
|--------|------|---------|
| 全部测试通过 | 0 Failure, 0 Error | 阻断 |
| skills.database 覆盖率 | >= 90% | 阻断 |
| mcp_server 覆盖率 | >= 90% | 阻断 |
| auth 覆盖率 | >= 90% | 阻断 |
| common 覆盖率 | >= 90% | 阻断 |
| 其他模块覆盖率 | >= 80% | 警告 |

---

## 七、测试命名与文件组织

### 7.1 测试目录结构

```
tests/
├── unit/                    # 单元测试
│   ├── test_risk_engine.py
│   ├── test_sql_executor.py
│   └── test_crypto.py
├── integration/             # 集成测试
│   ├── test_api_auth.py
│   └── test_api_datasource.py
├── mcp/                     # MCP Tool 测试
│   └── test_mcp_tools.py
└── conftest.py              # 全局 fixtures
```

---

## 八、性能测试要求

### 性能指标基线

| 指标 | 目标值 | 说明 |
|------|--------|------|
| API 响应时间 P95 | < 500ms | 非 SQL 执行接口 |
| SQL 执行响应时间 P95 | < 3s | 含目标库查询 |
| MCP Tool 调用 P95 | < 2s | 含风险识别 |
| 错误率 | < 0.1% | 正常负载 |

### 测试场景

1. 登录接口并发测试（50 并发，30s）
2. 数据源列表查询（20 并发，含分页）
3. SQL 执行并发（10 并发，含风险确认）
4. 审计日志查询（20 并发，时间范围筛选）
