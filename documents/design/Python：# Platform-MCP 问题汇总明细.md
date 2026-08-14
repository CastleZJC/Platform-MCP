# Platform-MCP 问题汇总明细

> 本文档汇总 Platform-MCP 项目开发过程中遇到的具体问题、根因与解决方案，作为后续开发的避坑指南与 review checklist。

---

## 0. 文档说明

### 0.1 文档定位

- **不是**操作手册（操作步骤见「部署规范」）
- **不是**架构说明（系统设计见「技术架构说明文档」）
- **是**"问题清单 + 根因 + 解决方案 + 文档交叉引用"，开发前快速翻阅可避免重复踩坑

### 0.2 适用范围

- 后续迭代开发（新 Skill、新传输模式、新页面）
- 新人接手项目时的避坑指南
- 代码 review 时的 checklist
- 文档审核时的交叉校验依据

### 0.3 文档引用清单

本文件"参考"段中使用的引用简称对应以下实际路径：

| 简称 | 路径 |
|------|------|
| 架构文档 §X.Y | `documents/design/Python：# Platform-MCP 技术架构说明文档.md` |
| 部署规范 §X.Y | `documents/design/Python：# Platform-MCP 部署规范.md` |
| 加密方案 §X.Y | `documents/design/Python：# Platform-MCP 加解密方案说明.md` |
| 测试规范 §X.Y | `documents/design/Python：# Platform-MCP 测试规范文档.md` |
| UI 样式规范 §X.Y | `documents/design/Python：# Platform-MCP UI 样式规范.md` |
| 代码规范 §X.Y | `documents/design/Python：# Platform-MCP 代码规范.md` |
| 数据库脚本规范 §X.Y | `documents/design/Python：# Platform-MCP 数据库脚本规范.md` |
| UI 原型 LXXX | `documents/ui/Platform-MCP-portal.html` |
| CLAUDE.md §X | `CLAUDE.md` |
| 代码位置 | `platform_mcp/xxx/yyy.py:line` 或 `Platform-MCP-frontend/src/...` |

### 0.4 条目结构

每条问题统一按"**现象 / 根因 / 解决 / 参考**"四段式撰写，便于检索与定位。

---

## 1. DDL / 数据库

### 1.1 seed_data.sql 关键业务表初始为空

**现象**：初始化后，pmcp_skill 和 pmcp_datasource 表均为空，前端"Skill 管理"和"数据源管理"页列表为空。

**根因**：`documents/db/20260605090001_seed_data.sql` 中 `pmcp_skill` 和 `pmcp_datasource` 的 `COPY ... FROM stdin` 后直接是 `\.`（空数据）。seed 脚本仅种了 admin 用户 + 两个角色，业务数据需手动导入。

**解决**：
- 数据库初始化后，按需执行：
  - `python scripts/_seed_skill.py`（种 database skill 到 pmcp_skill 表）
  - `python scripts/_import_poc_datasources.py`（导入 Oracle APP-SAMPLE-1 + MySQL APP-SAMPLE-2）
- 部署文档中明确说明 seed_data.sql 仅含基础用户/角色，业务数据需独立脚本。

**参考**：数据库脚本规范 §3 初始数据、`documents/db/20260605090001_seed_data.sql`、`scripts/_seed_skill.py`、`scripts/_import_poc_datasources.py`。

---

### 1.2 _seed_skill.py 的 Result.scalar() 不可重复调用

**现象**：执行 `python scripts/_seed_skill.py` 抛 `This result object does not return rows` 异常。

**根因**：原代码 `r = await s.execute(text("SELECT count(*) FROM pmcp_skill")); if r.scalar() == 0: ... else: print(r.scalar())` — SQLAlchemy 的 Result 对象 `scalar()` 只能消费一次，第二次调用因结果已消费抛异常。

**解决**：将 `r.scalar()` 结果先存到局部变量：
```python
cnt = (await s.execute(text("SELECT count(*) FROM pmcp_skill"))).scalar()
if cnt == 0:
    # INSERT
else:
    print(f"SKIP: {cnt} existing")
```

**参考**：`scripts/_seed_skill.py`、SQLAlchemy 2.0 Result 文档。

---

### 1.3 SHA-256 不可逆 → API Key 需 key_encrypted 列辅助 reveal

**现象**：admin 想 reveal 用户的 API Key 明文，但 `key_hash` 字段是 SHA-256 hash，密码学上不可逆，无法恢复明文。

**根因**：API Key 校验用 `key_hash`（安全设计），但 admin reveal 必须有明文来源。原设计只有 `key_hash` 一列，明文只在生成时返回一次，之后无法查询。

**解决**：
- Alembic migration `cf0101a947f4_add_api_key_encrypted.py` 新增 `key_encrypted VARCHAR(512)` 列，存 AES-GCM 加密后的明文。
- `generate_api_key` 同时写 `key_hash`（校验）+ `key_encrypted`（reveal）。
- `get_full_key_by_user` 解密 `key_encrypted` 返回明文。
- 主密钥来自 `crypto-secret.key`（与数据源密码共用 CryptoUtils）。

**参考**：加密方案 §3 AES-256-GCM、`platform_mcp/auth/api_key_models.py:19`、`platform_mcp/auth/api_key_service.py:29`、`alembic/versions/cf0101a947f4_add_api_key_encrypted.py`。

---

### 1.4 历史 hash-only Key 无法 reveal 明文

**现象**：admin 在用户管理页点"眼睛"reveal 明文，提示"该用户当前无活跃 Key 或 Key 在新机制前生成（无法 reveal 明文），请点击重置生成新 Key"。

**根因**：`cf0101a947f4` migration 之前生成的 API Key 只有 `key_hash`，`key_encrypted` 为 NULL。`get_full_key_by_user` 检测 `key.key_encrypted` 为空时返回 None。

**解决**：
- admin 点击"重置"按钮 → 撤销旧 Key + 生成新 Key（自动写 `key_encrypted`）。
- 新 Key 即可正常 reveal。
- 用户文档需提示"历史 Key 升级后需 reset 一次才能用 reveal 功能"。

**参考**：`platform_mcp/auth/api_key_service.py:132`、`platform_mcp/api/api_keys.py:109`（`/api-keys/full/{user_id}` 端点）。

---

### 1.5 list_users N+1 查询陷阱

**现象**：用户列表接口 `GET /users` 在用户数多时变慢，每个用户都触发 2 次额外查询（role + api_key_prefix）。

**根因**：`platform_mcp/api/users.py:list_users` 对每个 user 单独执行：
```python
for u in users:
    role_res = await db.execute(select(PmcpRole...)...)
    key_result = await db.execute(select(PmcpApiKey.key_prefix)...)
```
N 个用户 → 1 + 2N 次查询。

**解决**：
- 短期：用户量 < 100 可接受。
- 长期：改 JOIN 一次查完（PmcpUser JOIN PmcpUserRole JOIN PmcpRole LEFT JOIN PmcpApiKey）。
- 监控：列表 API P95 > 200ms 时优先优化此处。

**参考**：`platform_mcp/api/users.py:42`、架构文档 §6 性能基线。

---

### 1.6 NOT NULL 挡不住空串：编码字段需三层非空校验（BUG20260814134000）

**现象**：新增服务器/数据源时编码留空可直接保存成功，`server_code = ''` 的记录入库。

**根因**：三层防御全部缺失——
1. 前端 `el-form` 未绑定 `rules`/`prop`，`handleSubmit()` 不调 `validate()`，Element Plus 校验体系未启用；
2. 后端 Pydantic 裸 `str` 类型，`""`/`"   "` 均通过（查重只挡重复不挡空）；
3. DDL 仅 `NOT NULL`，**PostgreSQL 中 `''` ≠ NULL**，空串照常入库（唯一约束还隐含"只允许一条空串"）。

**解决**：三层同时收口——
- 前端：`el-form` 绑定 `:model`/`:rules`/`ref`，必填项声明 `prop`（`required + whitespace` 规则）；`handleSubmit` **先本地非空 guard**（trim 判空 + `ElMessage.error`）再 `validate()`——EP 2.8.1 form 级 validate 的 promise 聚合在测试环境下会吞掉校验失败返回 true（详见 3.16），不能作为唯一防线；
- 后端：`Field(min_length=1)` + `field_validator` strip 后判空（`api/servers.py`、`api/datasources.py` 的 Create 请求），空/全空格返回 422；
- 数据库：新增 alembic revision 004 为编码列建 `CHECK (code <> '')` 约束（已发布的 V1.0 基线修订 001 不可回改），ORM 模型同步声明 `CheckConstraint`。

**参考**：`documents/bug/BUG20260814134000-服务器与数据源编码可为空.md`、`alembic/versions/004_code_nonempty_check_constraints.py`、数据库脚本规范 §Alembic 迁移规则。

---

## 2. 后端 Python / FastAPI

### 2.1 登录登出未记录审计日志

**现象**：审计日志页看不到 admin 的登录、登出记录，违反"全链路审计"设计。

**根因**：`platform_mcp/api/auth.py` 的 `login` / `logout` 函数完全没有调用 `platform_mcp/audit/logger.py:write_audit_log`。

**解决**：
```python
# login 成功
await write_audit_log(operator=user["username"], resource_type="auth",
    request_summary="用户登录成功", result_status="success",
    duration_ms=duration_ms, extra_data={"role_code": user["role_code"]})
# login 失败
await write_audit_log(operator=body.username, resource_type="auth",
    request_summary="用户登录失败", result_status="fail",
    error_message="用户名或密码错误", duration_ms=duration_ms)
# logout（必须在 session_manager.delete 之前拿 username）
info = session_manager.get(session_id)
operator = info.username if info else "anonymous"
session_manager.delete(session_id)
await write_audit_log(operator=operator, resource_type="auth",
    request_summary="用户退出登录", result_status="success", duration_ms=duration_ms)
```

**参考**：架构文档 §8.5 审计、`platform_mcp/api/auth.py:14`、`platform_mcp/audit/logger.py:13`。

---

### 2.1.1 审计日志缺口：18 个敏感写操作端点未记录

**现象**：第一轮独立审核发现，除 login/logout 外，还有 18 个敏感写操作端点未调用 `write_audit_log`，包括用户管理、API Key 管理、数据源管理、Skill 管理、个人设置等模块。

**根因**：开发时只关注业务逻辑，遗漏审计日志调用。审计设计要求"敏感操作必须记录"，但代码中无强制检查机制。

**解决**：已补齐以下 18 个端点的审计日志（2026-06-22 修复）：
| 模块 | 端点 | resource_type |
|------|------|---------------|
| users.py | reset_password | permission |
| users.py | create_user | permission |
| users.py | update_user | permission |
| users.py | update_user_status | permission |
| profile.py | change_password | permission |
| profile.py | update_profile | permission |
| api_keys.py | create_key | permission |
| api_keys.py | delete_key | permission |
| api_keys.py | refresh_key | permission |
| api_keys.py | admin_reset_user_key | permission |
| api_keys.py | reveal_user_key | permission |
| datasources.py | create_datasource | datasource |
| datasources.py | update_datasource | datasource |
| datasources.py | update_ds_status | datasource |
| datasources.py | test_connection | datasource |
| skills.py | create_skill | permission |
| skills.py | update_skill_status | permission |
| skills.py | review_skill | permission |

**参考**：审核报告 §4 P0 审计日志缺口、`platform_mcp/api/users.py`、`platform_mcp/api/profile.py`、`platform_mcp/api/api_keys.py`、`platform_mcp/api/datasources.py`、`platform_mcp/api/skills.py`。

---

### 2.2 @register_skill 装饰器只入待注册队列，不主动注册

**现象**：在 Web 进程（FastAPI）中调用 `registry.get_skill("database")` 返回 None，以为装饰器自动注册了。

**根因**：`platform_mcp/mcp_server/skill/decorator.py` 的 `@register_skill` 装饰器只把 Skill 类加入模块级 `_pending_skills` 列表，**不调用 `registry.register()`**。实际注册发生在 MCP Server 启动时 `_register_skills()` 消费队列（`mcp_server/__init__.py:61`）。

**解决**：
- Web 进程需要 Skill 实例时，**直接实例化**，不要依赖 registry：
  ```python
  from platform_mcp.skills.database import DatabaseSkill
  tools = DatabaseSkill().list_tools()
  ```
- 或在 Web 启动时手动消费 pending（不推荐，污染 registry）。

**参考**：`platform_mcp/mcp_server/skill/decorator.py:10`、`platform_mcp/mcp_server/__init__.py:61`、`platform_mcp/api/guide.py:_get_skill_instance`。

---

### 2.3 Web 进程 registry.get_skill() 返回 None 的陷阱

**现象**：`/guide/tools` 端点返回 `tool_count=0, tools=[]`，但 pmcp_skill 表有 database skill 记录。

**根因**：见 2.2。Web 进程不启动 MCP server，`_pending_skills` 永远不被消费，`registry._skills` 为空字典。

**解决**：guide.py 用工厂函数 `_get_skill_instance(skill_code)` 按 skill_code 直接 import + 实例化：
```python
def _get_skill_instance(skill_code: str):
    if skill_code == "database":
        from platform_mcp.skills.database import DatabaseSkill
        return DatabaseSkill()
    return None
```

**参考**：`platform_mcp/api/guide.py:14`、CLAUDE.md §Skill System Design。

---

### 2.4 axios 拦截器 unwrap 后 res.data 即业务数据

**现象**：前端代码 `res.data.items` 拿不到列表，但浏览器 Network 看 JSON 明明有 items 字段。

**根因**：`Platform-MCP-frontend/src/utils/request.ts` 响应拦截器 `return data`（直接返回 ApiResponse 对象），不是 axios 原始 response。所以：
- 错误写法：`res.data.data.items`（多一层）
- 正确写法：`res.data.items`（res = ApiResponse，res.data = PageResult，res.data.items = 数组）

**解决**：所有页面统一用 `const res = await request.get(...); items.value = res.data.items` 模式。

**参考**：`Platform-MCP-frontend/src/utils/request.ts:12`、CLAUDE.md §Shared infrastructure。

---

### 2.5 CORS 默认仅 localhost:5173，Vite 自动切端口会 CORS 失败

**现象**：5173 被占用时 Vite 自动切到 5174，前端跨域请求被 CORS 拦截。

**根因**：`platform_mcp/config.py:63` 默认 `cors_origins=["http://localhost:5173"]`，未含 5174+。

**解决**：
- 短期：开发环境 kill 5173 旧进程，确保前端跑在 5173。
- 长期：开发态 cors_origins 用正则或 `["http://localhost:5173", "http://localhost:5174", "http://localhost:5175"]` 兜底；生产用 Nginx 同源反代绕过 CORS。

**参考**：`platform_mcp/config.py:63`、部署规范 §Nginx 反代。

---

### 2.6 API Key 双存储设计（hash + encrypted）的取舍

**现象**：API Key 同时存 `key_hash`（SHA-256）和 `key_encrypted`（AES-GCM），有人疑惑是否冗余。

**根因**：
- `key_hash`：用于校验（用户提交 Key → SHA-256 → 对比 hash）。不可逆，安全。
- `key_encrypted`：用于 admin reveal 明文。可逆（需要主密钥）。
- 两者用途不同，缺一不可。

**解决**：明确文档说明两列职责，`generate_api_key` 必须同时写两列。若数据库泄露，攻击者拿到 `key_encrypted` + 主密钥（在 `crypto-secret.key`）才能解密 — 所以 `crypto-secret.key` 必须独立于 DB 保管。

**参考**：加密方案 §3、`platform_mcp/auth/api_key_models.py:17`、`platform_mcp/auth/api_key_service.py:29`。

---

### 2.7 reveal 端点权限：self-or-admin 而非 admin-only

**现象**：普通 developer 用户在"个人设置"页 reveal 自己的 API Key 明文被 403。

**根因**：原 `/api-keys/full/{user_id}` 用 `require_admin`，仅 admin 可调用。但用户查看自己的 Key 是合理需求。

**解决**：端点改为 self-or-admin 模式：
```python
@router.get("/full/{user_id}")
async def reveal_user_key(user_id: int, ..., current_user: dict = Depends(get_current_user)):
    if current_user["role_code"] != "admin" and current_user["id"] != user_id:
        raise AuthError("权限不足：只能查看自己的 API Key")
    ...
```

**参考**：`platform_mcp/api/api_keys.py:109`、架构文档 §权限矩阵。

---

### 2.8 create_user 自动生成 API Key（明文仅返回一次）

**现象**：admin 新建用户后，新用户没有 API Key，无法 MCP 接入；admin 也不知道 Key 是什么。

**根因**：用户需要 API Key 才能用 MCP，但 Key 只能在生成时返回明文一次。

**解决**：`create_user` 内自动调 `generate_api_key`，响应中返回明文 Key：
```python
api_key = await generate_api_key(db, user.id, "初始密钥")
await db.commit()
return ResponseBase(data={"user_id": user.id, "username": user.username,
    "api_key": api_key}, message="用户创建成功，请立即保存 API Key")
```
UI 上新建用户成功后弹窗展示 Key + 复制按钮。

**参考**：`platform_mcp/api/users.py:95`、`platform_mcp/auth/api_key_service.py:29`。

---

### 2.9 write_audit_log 是 async，必须 await

**现象**：审计日志没写入数据库，但代码看起来调用了 `write_audit_log(...)`。

**根因**：`write_audit_log` 是 async 函数，忘记 `await` 会被 Python 警告但不报错，且不会实际执行。

**解决**：所有调用点必须 `await write_audit_log(...)`。代码 review 重点检查 login/logout/crypto/mcp_call 等敏感操作的 await。

**参考**：`platform_mcp/audit/logger.py:13`。

---

### 2.9.1 result_status 枚举不一致：SUCCESS/ERROR vs success/error

**现象**：审计日志查询结果中，`result_status` 字段值混用大写（SUCCESS/ERROR）和小写（success/error），导致前端筛选和统计不一致。

**根因**：`mcp_server/skill/registry.py` 中 `log_mcp_call` 调用传入 `"SUCCESS"` / `"ERROR"`（大写），而 `auth.py` 等其他模块传入 `"success"` / `"error"` / `"fail"`（小写）。

**解决**：统一使用小写枚举值（2026-06-22 修复）：
- `registry.py:L69,73` 改为 `"success"` / `"error"`
- 全局规范：`result_status` 仅使用 `success` / `fail` / `error` 三种小写值

**参考**：审核报告 §4 P1 枚举不一致、`platform_mcp/mcp_server/skill/registry.py:69`、`platform_mcp/api/auth.py`。

---

### 2.9.2 审计日志字段缺失：列表接口缺 env_code/request_summary/error_code

**现象**：前端 AuditPage 组件的 `AuditLog` 接口定义包含 `env_code`、`request_summary`、`error_code` 三个字段，但后端 `query_logs` 函数返回的字典中缺这些字段，导致 TypeScript 类型不匹配。

**根因**：`audit/service.py:query_logs` 构建返回字典时遗漏了这 3 个字段，虽然 ORM 模型 `PmcpAuditLog` 有这些列。

**解决**：`query_logs` 函数返回字典补齐 3 个字段（2026-06-22 修复）：
```python
items.append({
    # ... 原有字段 ...
    "env_code": log.env_code,
    "request_summary": log.request_summary,
    "error_code": log.error_code,
    # ...
})
```

**参考**：审核报告 §4 P2 字段缺失、`platform_mcp/audit/service.py:78`、`Platform-MCP-frontend/src/types/index.ts:64`。

---

### 2.9.3 僵尸字段清理：start_time/end_time 仅在详情接口返回

**现象**：`pmcp_audit_log` 表的 `start_time`、`end_time` 列仅在 `GET /audit/logs/{id}` 详情接口返回，列表接口不返回，前端也不使用，形成僵尸字段。

**根因**：早期设计预留的字段，实际业务逻辑中并未真正使用（用 `duration_ms` 已足够）。

**解决**：
1. 删除 `api/audit.py:get_log` 函数中的 start_time/end_time 返回（2026-06-22）
2. 删除 ORM 模型中的字段定义 `audit/models.py:L27-28`（2026-06-22）
3. 创建 Alembic migration `cg0101a947f5_drop_audit_dead_columns.py` 删除 DB 列（2026-06-22）

**参考**：审核报告 §4 P3.2/P3.3 僵尸字段清理、`platform_mcp/api/audit.py:67`、`platform_mcp/audit/models.py:27`、`alembic/versions/cg0101a947f5_drop_audit_dead_columns.py`。

---

### 2.10 audit resource_type 规范化七类映射

**现象**：审计日志筛选"操作类型"下拉框选项与后端 resource_type 值对不上，筛选无效。

**根因**：`resource_type` 是自由字符串，未做枚举规范化。各处写入的值不一（如 "auth"/"login"、"datasource"/"ds"）。

**解决**：前后端统一七类映射：
| resource_type | 中文 | tag class |
|---------------|------|-----------|
| auth | 登录登出 | tag-primary |
| mcp / mcp_call / skill | MCP 调用 | tag-info |
| sql / sql_exec | SQL 执行 | tag-info |
| datasource | 数据源变更 | tag-success |
| user / role / permission | 权限变更 | tag-info |
| crypto | 加解密操作 | tag-warning |
| config / system | 系统配置 | tag-info |

前端 `AuditPage.vue:resourceTypeLabel` + `resourceTypeTagClass` 统一映射。

**参考**：`Platform-MCP-frontend/src/views/audit/AuditPage.vue`、架构文档 §8.5 审计类型。

---

### 2.11 ContextVar 在 HTTP/stdio 双模式下的身份传播

**现象**：HTTP 模式多用户并发时，身份串号（A 用户的操作被记到 B 用户名下）。

**根因**：用全局变量 `_current_identity` 存身份，HTTP 并发时不安全。

**解决**：用 `contextvars.ContextVar` 保证 async 并发隔离：
```python
_mcp_identity_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_identity", default=None)
```
- HTTP 模式：Starlette middleware 每请求 `set(identity)`，请求结束自动隔离。
- stdio 模式：进程级单用户，启动时 `set` 一次。

**参考**：`platform_mcp/mcp_server/__init__.py:18`、Python contextvars 文档。

---

### 2.12 FastMCP add_middleware 旧版不支持，try/except 兜底

**现象**：MCP SDK 旧版 `FastMCP` 无 `add_middleware` 方法，调用 AttributeError。

**根因**：FastMCP API 在不同版本间有差异。

**解决**：
```python
try:
    mcp.add_middleware(_AuthMiddleware)
except AttributeError:
    logger.warning("FastMCP 不支持 add_middleware，跳过 API Key 中间件；请确保上层 Nginx 校验")
```
生产部署用 Nginx 兜底校验 Header，不依赖 FastMCP 中间件。

**参考**：`platform_mcp/mcp_server/__init__.py:99`、部署规范 §Nginx。

---

### 2.13 MCP streamable_http 500（BaseExceptionGroup + BaseHTTPMiddleware 不兼容）

**现象**：MCP HTTP 模式运行一段时间后，日志偶发 `POST /mcp/ HTTP/1.1" 500 Internal Server Error`，traceback 关键链：

```
File ".../mcp/server/streamable_http.py", line 474, in _handle_post_request
    await writer.send(session_message)
File ".../anyio/streams/memory.py", line 218, in send_nowait
    raise ClosedResourceError
anyio.ClosedResourceError

# 上层 anyio TaskGroup 包装：
File ".../anyio/_backends/_asyncio.py", line 799, in __aexit__
    raise BaseExceptionGroup(...)
ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

# Starlette BaseHTTPMiddleware 无法处理 BaseExceptionGroup：
File ".../starlette/middleware/base.py", line 164, in call_next
    raise RuntimeError("No response returned.")
RuntimeError: No response returned.
```

**根因**：客户端（Claude Code 等）的 SSE 长连接（GET /mcp/）断开后，仍向同 session 发 POST：

1. MCP SDK `_handle_post_request` 向已关闭的 memory channel `writer.send`，抛 `anyio.ClosedResourceError`
2. anyio TaskGroup 把它包装为 `BaseExceptionGroup`（继承 `BaseException`，**不是** `Exception`）
3. `BaseHTTPMiddleware.call_next` 内部用 `except Exception` 抓 inner app 异常 —— **抓不到 `BaseExceptionGroup`**
4. fallthrough 后 Starlette 抛 `RuntimeError("No response returned.")` → HTTP 500

**解决**：`_AuthMiddleware` 改纯 ASGI callable（不再继承 `BaseHTTPMiddleware`），用 `except BaseException`（排除 `SystemExit`/`KeyboardInterrupt`/`asyncio.CancelledError`）捕获后返回 503。客户端会重建 SSE 流并重试 POST，符合 MCP 协议预期。

**关键代码**（`platform_mcp/mcp_server/__init__.py`）：

```python
class _AuthMiddleware:
    """纯 ASGI 鉴权中间件（兼容 MCP streamable_http 的 ExceptionGroup）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        # ... 鉴权（PLATFORM_MCP_API_KEY header）逻辑 ...
        _mcp_identity_var.set(identity)

        response_started = {"value": False}
        async def _send_wrapper(message):
            if message.get("type") == "http.response.start":
                response_started["value"] = True
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        except (SystemExit, KeyboardInterrupt, asyncio.CancelledError):
            raise
        except BaseException:
            if response_started["value"]:
                # response 已 start（典型：POST 200 + SSE 流），SSE 投递失败。
                # re-raise 会让 uvicorn 报 "ASGI callable returned without completing
                # response"，降级为 warning + 优雅 return，客户端会触发 SSE 重连/超时重试。
                logger.warning(
                    "MCP SSE response interrupted after start; client should retry",
                    exc_info=True,
                )
                return
            logger.warning("MCP streamable_http raised exception, returning 503", exc_info=True)
            await _send_json_response(send, 503, {"error": "MCP session unavailable, please retry"})
```

**避坑要点**：

- 不要用 `BaseHTTPMiddleware` 子类处理 streamable_http_app —— TaskGroup 异常无法传播
- `except Exception` 捕获不了 `BaseExceptionGroup`，必须 `except BaseException`（再排除系统控制流异常 `SystemExit`/`KeyboardInterrupt`/`CancelledError`）
- response 已 started 后不能再发 response（违反 ASGI 协议），用 `_send_wrapper` 跟踪状态
- **response started 后 inner app 抛异常时不要 re-raise**：长 SQL 执行期间客户端 SSE channel 断开后，POST 已发 200，writer.send 抛 ClosedResourceError 被包装为 BaseExceptionGroup。re-raise 会让 uvicorn 报 "ASGI callable returned without completing response"（虽然不影响 server 进程存活，但客户端会看到响应中断）。应降级为 warning log + 优雅 return，让连接自然关闭、客户端超时重试。

**参考**：`platform_mcp/mcp_server/__init__.py:_AuthMiddleware`、部署规范 §2.4.2 实现细节、`tests/unit/test_mcp_server_init.py:test_auth_middleware_asgi_inner抛BaseExceptionGroup_返回503`（response 未 start 路径）、`test_auth_middleware_asgi_response已start_SSE投递失败_优雅return不抛`（response 已 start 路径）。

---

### 2.14 main.py uvicorn 不要 reload=True（Windows + watchfiles 死循环）

**现象**：本地启动后端，日志疯狂刷"Reloading..."，CPU 100%。

**根因**：`uvicorn.run(reload=True)` 在 Windows + watchfiles 监听日志目录（loguru 写文件触发 watchfiles 重载 → 重载又写日志 → 再次触发），死循环。

**解决**：`platform_mcp/main.py:121` 的 `uvicorn.run` 不要 `reload=True`；开发态需热重载时单独写 dev 脚本并排除 logs/ 目录。

**参考**：`platform_mcp/main.py:121`。

---

### 2.14 8000 端口遗留进程排查（taskkill + 重启）

**现象**：启动后端报 `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000): only one usage of each socket address`。

**根因**：上次会话的后端进程未关闭，8000 端口被占。

**解决**：
```bash
netstat -ano | grep ":8000.*LISTENING"   # 找 PID
taskkill //PID <PID> //F                  # Windows
# Linux: kill -9 <PID>
```

**参考**：部署规范 §本地开发。

---

### 2.15 _ensure_engine() 必须在 async_session_factory 前

**现象**：`authenticate_user` 报 `'NoneType' object is not callable`。

**根因**：直接用 `async_session_factory()` 前未调 `_ensure_engine()`，`async_session_factory` 为 None。

**解决**：
```python
from platform_mcp.common.database import _ensure_engine, async_session_factory
_ensure_engine()  # 必须先调
async with async_session_factory() as session:
    ...
```
或在 FastAPI 启动 lifespan 中统一调一次（`main.py:26` 已做，但脚本和测试需手动调）。

**参考**：`platform_mcp/common/database.py`、`platform_mcp/main.py:24`。

---

### 2.16 _setup_local.py 实际只做 crypto + alembic + 用户检查

**现象**：开发者误以为 `python scripts/_setup_local.py` 是"全量初始化"（含 admin 密码重置、skill 种子、数据源导入），实际跑完发现业务数据仍为空。

**根因**：`scripts/_setup_local.py` 实际功能：
1. 生成 `crypto-secret.key`（若不存在）
2. `alembic current` + `alembic upgrade head`
3. 查询并打印 seed 用户状态

**不**做：admin 密码重置、skill 种子、POC 数据源导入、API Key 生成。

**解决**：脚本头部 docstring 明确说明功能边界，CLAUDE.md 注释也要对齐（曾经写错为"全量初始化"）。

**参考**：`scripts/_setup_local.py:1`、CLAUDE.md §Development Commands。

---

### 2.17 _seed_skill.py 只 INSERT pmcp_skill，无 web 映射

**现象**：文档写"_seed_skill.py 种 database skill + skill-web 映射"，实际跑完发现 pmcp_skill_web 表无数据。

**根因**：`scripts/_seed_skill.py` 实际只 `INSERT INTO pmcp_skill (skill_code, skill_name, ...) VALUES ('database', ...)`，不写 web 映射表。

**解决**：脚本描述对齐代码实际，避免文档与代码漂移。

**参考**：`scripts/_seed_skill.py:12`。

---

### 2.18 _verify_imports.py 是模块 import 校验，非数据校验

**现象**：开发者跑 `_verify_imports.py` 期望验证 skill + datasource 是否导入成功，实际输出是模块 import 是否成功。

**根因**：`scripts/_verify_imports.py` 实际是 `for mod in [...]: import mod`，校验 Python 模块可加载，与数据库数据无关。

**解决**：
- 文档描述对齐实际功能（"验证所有新模块可成功 import"）。
- 数据校验请直接查 SQL：`SELECT * FROM pmcp_skill; SELECT * FROM pmcp_datasource;`。

**参考**：`scripts/_verify_imports.py:1`。

---

### 2.19 stdio 模式启动时 API Key 校验需 new_event_loop

**现象**：stdio 模式启动时调用 `await _validate_api_key_async(api_key)` 报 `no running event loop`。

**根因**：`main()` 是同步函数，无 event loop，`await` 无法直接用。

**解决**：手动创建 event loop：
```python
import asyncio
loop = asyncio.new_event_loop()
identity = loop.run_until_complete(_validate_api_key_async(api_key))
loop.close()
```

**参考**：`platform_mcp/mcp_server/__init__.py:117`。

---

### 2.20 profile.py / users.py 各端点的隐藏约束

**现象**：开发者复制粘贴端点时漏掉约束（如 list_users 必须 admin、create_user 必须返回 API Key）。

**根因**：端点的隐藏业务约束散落在函数体内，签名上看不出来。

**解决**：关键端点约束清单：
- `GET /users` — admin only（`require_admin`）
- `POST /users` — admin only + 自动生成 API Key + 返回明文一次
- `PUT /users/{id}` — admin only
- `GET /api-keys` — 任意登录用户（返回自己的 Key 掩码列表）
- `POST /api-keys` — 任意登录用户（生成新 Key，返回明文一次）
- `GET /api-keys/full/{user_id}` — self-or-admin
- `POST /api-keys/reset/{user_id}` — admin only
- `GET /profile` — 任意登录用户
- `PUT /profile` — 任意登录用户
- `POST /profile/change-password` — 任意登录用户

**参考**：`platform_mcp/api/users.py`、`platform_mcp/api/api_keys.py`、`platform_mcp/api/profile.py`。

---

### 2.21 FastMCP 工具注册必须用 add_tool + 显式 __signature__（不能用 @mcp.tool + **kwargs）

**现象**：所有 MCP 工具调用（execute_sql_text/file、validate_sql、list_datasources、get_execution_status）从标准 MCP 客户端发起时返回：
```
Error executing tool execute_sql_text:
1 validation error for _handlerArguments
kwargs
  Field required [type=missing, input_value={'datasource_code': 'ora-...'}]
```
工具实际从未执行，MCP server 在协议层卡 5 分钟（query_timeout），客户端看到 "Command failed with no output"。

**根因**：原 `registry._register_single_tool` 用 `@mcp.tool` 装饰器 + `async def _handler(**kwargs)` 签名：

```python
@mcp.tool(name=meta.tool_name, description=meta.description)
async def _handler(**kwargs) -> str:
    actual = kwargs.get("kwargs") if isinstance(kwargs.get("kwargs"), dict) else kwargs
    ...
```

FastMCP 通过 `inspect.signature(fn)` 自省函数签名生成 pydantic model。对 `**kwargs` 签名生成的 model 是 `{kwargs: dict}`（required field），而标准 MCP 客户端按 spec 发 `arguments: {field1, field2, ...}`，pydantic 校验时找不到 `kwargs` 字段直接报错——**handler 函数体根本没被执行**，"兜底代码" `kwargs.get("kwargs")` 是死代码。

**解决**：用 `mcp.add_tool` 而非装饰器，**在 add_tool 之前**用 `_handler.__signature__ = sig` 覆盖签名：

```python
import inspect

_JSON_TYPE_TO_PY = {"string": str, "integer": int, "number": float,
                    "boolean": bool, "array": list, "object": dict}

def _build_handler_signature(input_schema: dict) -> inspect.Signature:
    """从 ToolMeta.input_schema (JSON Schema) 还原显式参数签名。"""
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    params = []
    for name, schema in properties.items():
        py_type = _JSON_TYPE_TO_PY.get(schema.get("type", "string"), str)
        if name in required:
            params.append(inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=py_type))
        else:
            default = schema.get("default") if "default" in schema else None
            params.append(inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=py_type, default=default))
    return inspect.Signature(params)

# 在 _register_single_tool 中：
async def _handler(**kwargs) -> str:
    # kwargs 现在直接是具名参数（FastMCP 已按 __signature__ 校验过）
    ...

_handler.__signature__ = _build_handler_signature(meta.input_schema)  # 必须在 add_tool 之前
mcp.add_tool(_handler, name=meta.tool_name, description=meta.description)
```

**关键时序**：
- `@mcp.tool` 装饰器形式会在装饰瞬间触发 `inspect.signature(fn)`，**之后**设 `__signature__` 无效
- 必须先定义函数 → 设 `__signature__` → 再调 `mcp.add_tool(fn, ...)`

**避坑要点**：
- 不要用 `@mcp.tool` 装饰器 + `**kwargs` 组合注册工具
- `inspect.signature(fn)` 尊重 `fn.__signature__`，但必须在被 FastMCP 自省之前设置
- 标准的 `mcp.add_tool` 调用形式允许在注册前完成签名操纵

**参考**：`platform_mcp/mcp_server/skill/registry.py:_build_handler_signature`、`tests/unit/test_skill_registry.py`、`scripts/_verify_149.py`（实测验证脚本）。

---

### 2.22 审计失败记录的 error_code 强制捕获（V1.0.1 hotfix）

**现象**：审计日志查询 result_status='fail' 或 'error' 的记录时，部分行 `error_code` 为 NULL，违反"失败必须抓到错误码与错误信息"原则。V1.0.1 修复前实测：

| 表 | result_status='fail'/'error' 行数 | error_code 缺失数 | 缺失原因 |
|----|---|---|---|
| `pmcp_audit_log` (auth/fail) | 1 | 1 | web 层 `auth.py login` 失败时 write_audit_log 未传 error_code |
| `pmcp_mcp_call_log` (sql/shell error) | 5 | 5 | `call_log.py` PmcpMcpCallLog 构造器漏传 `error_code=error_code` |

**根因**：

1. **call_log.py 构造器漏字段**：`log_mcp_call` 函数签名虽然接受 `error_code` 参数，并把它透传给 `write_audit_log`（audit_log 表正确入库），但**没传给 PmcpMcpCallLog 模型构造器**，导致 mcp_call_log 表 error_code 列永远为 NULL。
2. **Web 层 fail 路径未带 error_code**：`auth.py:login` 失败时 write_audit_log 只传 `error_message="用户名或密码错误"`，但未传 `error_code`。同样的模式还存在于 `crypto.py:encrypt/verify` 与 `profile.py:change_password`。

**解决**：

1. `platform_mcp/mcp_server/call_log.py:53` — PmcpMcpCallLog 构造器补 `error_code=error_code`
2. `platform_mcp/api/auth.py:27` — login fail write_audit_log 补 `error_code="11001"`（AuthError 默认码）
3. `platform_mcp/api/crypto.py:62,104` — encrypt/verify fail 补 `error_code="15001"`（BusinessError 默认码）
4. `platform_mcp/api/profile.py:98` — change_password 当前密码错补 `error_code="11004"`（与同函数 `return ResponseBase(code=11004)` 对齐）

**全局扫描脚本**（防新增漏网）：

```python
# 检测所有 write_audit_log 调用：若 result_status in {fail,error} 则必须传 error_code
import re, os
for root, _, files in os.walk('platform_mcp'):
    for fn in files:
        if not fn.endswith('.py'): continue
        path = os.path.join(root, fn)
        src = open(path, encoding='utf-8').read()
        for m in re.finditer(r'write_audit_log\s*\(', src):
            i, depth = m.end(), 1
            while i < len(src) and depth > 0:
                depth += (src[i] == '(') - (src[i] == ')')
                i += 1
            body = src[m.end():i-1]
            if re.search(r'result_status\s*=\s*["\'](?:fail|error)["\']', body) and not re.search(r'error_code\s*=', body):
                line = src.count('\n', 0, m.start()) + 1
                print(f"{path}:{line}  FAIL without error_code")
```

**验证（生产环境 192.0.2.216，V1.0.1 部署后）**：

| 场景 | audit_log.error_code | mcp_call_log.error_code |
|------|----------------------|-------------------------|
| castle.zhang 登录失败（web 层）| 11001 ✓ | — |
| castle.zhang 调 execute_sql_text 不存在的数据源（MCP 层）| 12001 ✓ | 12001 ✓ |

**反思**：审计日志的字段完整性不能依赖单个工程师的自觉。除了扫描脚本外，应在 `write_audit_log` 入口加运行时断言（debug 模式下 `assert result_status in ('success', 'fail', 'error')` + 失败时 `assert error_code is not None`），把"漏传 error_code"从隐藏 bug 升级为显式失败。

**参考**：`platform_mcp/api/auth.py:22-30`、`platform_mcp/api/crypto.py:50-66,91-107`、`platform_mcp/api/profile.py:91-100`、`platform_mcp/mcp_server/call_log.py:42-60`、CLAUDE.md §错误码规范、CLAUDE.md §部署原则 #10（README §版本迭代强制更新）。

---

### 2.23 审计 result_status 枚举 fail/error 二选一统一（V1.0.2 hotfix）

**现象**：审计日志查询中，"状态"列有的行显示 `失败`（中文）有的行显示 `fail`（英文 raw）。例如 castle.zhang 登录失败的状态值是 `fail` 而非 `error`，前端 `statusLabel` 只映射 `'success'→成功` / `'error'→失败`，**不识别 `'fail'`** → fallback 直接显示英文 `fail`。

**根因**：

1. `pmcp_audit_log.result_status` 列 comment 写的是 `success/fail/error`（3 值枚举），但语义上 `fail` 与 `error` 重叠，工程实践中无明确区分规则。
2. Web 层（`auth.py:login`、`crypto.py:encrypt/verify`、`profile.py:change_password`、`datasources/servers:test_connection`）习惯写 `'fail'`；MCP 层（`registry.py`）写 `'error'`。
3. 前端 `AuditPage.vue:statusLabel` 只处理 `'success'` 与 `'error'`，`'fail'` 落入 fallback 显示英文 raw value。

**解决**：

1. **代码统一为 `'error'`**（V1.0.2）：6 处 `result_status="fail"` → `result_status="error"`
   - `platform_mcp/api/auth.py:26`
   - `platform_mcp/api/crypto.py:53,61,95,103`（含 PmcpCryptoOperationLog + audit_log 两处 write）
   - `platform_mcp/api/profile.py:97`
   - `platform_mcp/api/datasources.py:207`
   - `platform_mcp/api/servers.py:209`
2. **UI 防御性映射**：`AuditPage.vue:statusLabel` 同时识别 `'fail'` 与 `'error'` → `失败`（应对 backfill 期间过渡态 + 未来误用）
3. **ORM comment 更新**：`audit/models.py` 三处 `result_status` 列 comment 改为 `(success/error)`，注释统一口径
4. **历史数据 backfill**（生产 192.0.2.216）：
   ```sql
   UPDATE pmcp_audit_log SET result_status='error' WHERE result_status='fail';
   UPDATE pmcp_mcp_call_log SET result_status='error' WHERE result_status='fail';
   UPDATE pmcp_crypto_operation_log SET result_status='error' WHERE result_status='fail';
   ```
   实测：2 行 audit_log + 0 行 mcp_call_log + 0 行 crypto_op_log（V1.0.1 部署前仅 castle.zhang 1 次登录失败 + 1 次 V1.0.1 验证记录用了 'fail'）

**反思**：

- 列 comment 里的 `success/fail/error` 是早期"业务失败 vs 系统错误"语义区分的残留，但工程中并未严格执行（如 `crypto.py:encrypt` catch 通用 Exception 写 `fail`，实际语义是系统 error）。**枚举值不应预留未严格使用的近义词**，否则会随时间扩散污染数据。
- UI 显示函数对 enum 值的 fallback 应当保守：未知值显示为 `未知(原值)` 或统一映射到失败，避免英文 raw value 直接泄漏到中文界面。
- 列 comment 不应写未严格定义的枚举值；写枚举值就应当 enforce（write_audit_log 入口加 `assert result_status in {'success','error'}`）。

**验证（V1.0.2 部署后）**：

```
 tbl          | errors | with_code 
--------------+--------+-----------
 audit_log    |   8    |    8      ← 100% 有 error_code
 mcp_call_log |   6    |    6      ← 100% 有 error_code
fail 残留     | 0/0/0  |           ← 全表 0 行 'fail'
```

castle.zhang 两行登录失败记录（id=231 历史 + id=248 V1.0.1 验证）统一为 `result_status='error', error_code='11001'`。

**参考**：`platform_mcp/api/auth.py:22-30`、`platform_mcp/api/crypto.py:50-107`、`platform_mcp/api/profile.py:91-100`、`platform_mcp/api/datasources.py:200-210`、`platform_mcp/api/servers.py:200-210`、`platform_mcp/audit/models.py:23,43,60`、`Platform-MCP-frontend/src/views/audit/AuditPage.vue:117-121`、CLAUDE.md §Key Conventions。

---

## 3. 前端 Vue / TypeScript

### 3.1 MainLayout nav-group-label vs nav-group-title 命名错位

**现象**：侧边栏分组标签（管理中心/系统管理/帮助）不可见，肉眼几乎看不到。

**根因**：`MainLayout.vue` 模板 `<div class="nav-group-label">{{ group.label }}</div>`，但 scoped CSS 定义的是 `.nav-group-title`。class 名不一致，样式不生效。

**解决**：模板和 CSS 统一用 `.nav-group-title`（与原型 `documents/ui/Platform-MCP-portal.html` 一致）。

**参考**：`Platform-MCP-frontend/src/layouts/MainLayout.vue`、UI 原型 L690。

---

### 3.2 el-input 未设 autocomplete 导致浏览器 autofill

**现象**：用户管理"新增用户"弹窗，用户名/密码字段被浏览器自动填了 admin/admin123。

**根因**：`el-input` 默认 `autocomplete` 为开启，浏览器密码管理器对 `type="password"` 字段强制 autofill。

**解决**：
1. el-form 加 `autocomplete="off"`。
2. 表单顶部加隐藏假 input 消耗 autofill：
   ```html
   <input type="text" name="fake-username" style="display:none" autocomplete="off" />
   <input type="password" name="fake-password" style="display:none" autocomplete="off" />
   ```
3. 真实字段加 `autocomplete="new-password"` + 唯一 `name` 属性。

**参考**：`Platform-MCP-frontend/src/views/user/UserPage.vue`、UI 样式规范 §表单。

---

### 3.3 掩码函数统一：抽 utils/format.ts:maskApiKey

**现象**：用户管理显示 `pmcp_a******yz`，个人设置显示 `pmcp_abcd`（10 字符前缀），两边格式不一致。

**根因**：
- `UserPage.vue` 有本地 `maskKey(prefix)` → `prefix.slice(0,7) + "******" + prefix.slice(-2)`
- `ProfilePage.vue` 直接用后端返回的 `key_prefix`（raw_key[:10]，无掩码）

两个页面各自实现，违反 DRY。

**解决**：抽 `Platform-MCP-frontend/src/utils/format.ts`：
```typescript
export function maskApiKey(prefix: string | null | undefined): string {
  if (!prefix) return "—"
  return prefix.length >= 8
    ? prefix.slice(0, 7) + "******" + prefix.slice(-2)
    : prefix + "****"
}
```
UserPage 和 ProfilePage 都 import 此函数，禁止本地实现。

**参考**：`Platform-MCP-frontend/src/utils/format.ts`、UI 样式规范 §API Key 掩码。

---

### 3.4 ProfilePage.toggleApiKey 应 reveal 而非 POST 生成

**现象**：个人设置的 API Key 明文与用户管理中 admin 行的明文对不上。

**根因**：`ProfilePage.vue:toggleApiKey` 原实现 `POST /api-keys` 每次点眼睛都生成新 Key（明文当然每次不同）。

**解决**：改为 `GET /api-keys/full/{user_id}` reveal 现有活跃 Key 明文，不生成新 Key：
```typescript
async function toggleApiKey() {
  if (keyVisible.value) { keyVisible.value = false; return }
  const res = await request.get(`/api-keys/full/${userStore.user.id}`)
  if (res.data?.key) { apiKeyFull.value = res.data.key; keyVisible.value = true }
}
```

**参考**：`Platform-MCP-frontend/src/views/profile/ProfilePage.vue`、`platform_mcp/api/api_keys.py:109`。

---

### 3.5 DatasourcePage 缺 onMounted → 列表永远空

**现象**：数据源管理页打开后列表空白，但后端 `/datasources` 接口能正常返回数据。

**根因**：`DatasourcePage.vue` script setup 定义了 `fetchDatasources` 函数，但**没有调用 `onMounted(fetchDatasources)`**，页面加载时不发请求。

**解决**：在 script setup 末尾加：
```typescript
onMounted(fetchDatasources)
```
对照其他页面（SkillPage/AuditPage/UserPage/CryptoPage）都有 onMounted。

**参考**：`Platform-MCP-frontend/src/views/datasource/DatasourcePage.vue`、Vue 3 onMounted 文档。

---

### 3.6 Element Plus el-table 与原型不符 → 原生 table.data-table

**现象**：用 `el-table` 渲染的表格，列宽、行高、hover 颜色都与原型 HTML 不一致。

**根因**：原型 `documents/ui/Platform-MCP-portal.html` 用原生 `<table class="data-table">`，CSS 在 global.css；`el-table` 自带样式系统，无法精确对齐。

**解决**：所有列表页统一改原生 table：
```html
<table class="data-table">
  <thead><tr><th>...</th></tr></thead>
  <tbody>
    <tr v-for="row in list" :key="row.id"><td>...</td></tr>
  </tbody>
</table>
```
global.css 已定义 `.data-table` 全套样式（thead 背景 #f8fafc、hover #e0e7ff、padding 等）。

**参考**：UI 原型 L350-360、`Platform-MCP-frontend/src/styles/global.css`。

---

### 3.7 全局原型类必须放 global.css，禁止 scoped 重复定义

**现象**：scoped CSS 中的 `.toolbar` 覆盖了 global.css 中的 `.toolbar`（justify-content 不同），样式冲突。

**根因**：每个页面 scoped 中重复定义全局类，scoped 优先级高，覆盖全局。

**解决**：
- 所有原型类（`.card / .toolbar / .data-table / .btn / .tag-* / .status-dot / ...`）只在 `global.css` 定义一次。
- 各页面 scoped 留空或只定义页面特有类（如 `.faq-item.open .faq-a`）。

**参考**：`Platform-MCP-frontend/src/styles/global.css`、UI 样式规范 §组件类清单。

---

### 3.8 Vite 自动切端口 5173→5174，旧进程要 kill

**现象**：开发者两个浏览器 tab 分别开 5173 和 5174，访问行为不一致（一个旧版一个新版）。

**根因**：5173 被旧进程占，Vite 启动时自动切 5174，开发者未察觉。

**解决**：开发前先 kill 旧 Vite：
```bash
netstat -ano | grep ":5173.*LISTENING"  # 找 PID
taskkill //PID <PID> //F
```
统一访问 5173。

**参考**：开发流程约定。

---

### 3.9 浏览器缓存导致 HMR 失效，需 Ctrl+Shift+R

**现象**：改了前端代码但浏览器看不到效果。

**根因**：浏览器缓存了旧的 JS bundle，Vite HMR 推送被忽略。

**解决**：硬刷新 `Ctrl+Shift+R`（Windows）/ `Cmd+Shift+R`（Mac），或在 DevTools → Network → Disable cache。

**参考**：开发流程约定。

---

### 3.10 Vue 模板多余闭合标签 → 编译失败

**现象**：CryptoPage 显示一个文字堆栈的错误页（看起来像 CMD 界面），实际是 Vue 编译错误。

**根因**：模板手写时多了一个 `</div>` 闭合标签，Vue 编译器报错，Vite 显示错误堆栈。

**解决**：DevTools Console 看具体编译错误行号，删除多余标签。IDE 用 Volar 插件可在保存时高亮不匹配的标签。

**参考**：`Platform-MCP-frontend/src/views/crypto/CryptoPage.vue`、Vue 3 模板文档。

---

### 3.11 CSS 文件误粘 HTML 标签 → postcss 报错

**现象**：Vite 报 `[plugin:vite:css] [postcss] Unknown word </style>`。

**根因**：从 HTML 复制 CSS 时误把 `</style>` 闭合标签也粘进 global.css。

**解决**：CSS 文件中只能有 CSS 规则，删除所有 HTML 标签。

**参考**：`Platform-MCP-frontend/src/styles/global.css`。

---

### 3.12 API Key 眼睛按钮：必须 fetch 明文才有意义

**现象**：用户管理 API Key 列点"眼睛"按钮无反应。

**根因**：`toggleReveal(userId)` 只在 `revealedKeys[userId]` 已存在时删除（隐藏），没有 fetch 明文的逻辑。用户首次点眼睛时 `revealedKeys[userId]` 为空，什么都不做。

**解决**：toggleReveal 改为异步，调 reveal 端点拿明文：
```typescript
async function toggleReveal(userId: number) {
  if (revealedKeys.value[userId]) { delete revealedKeys.value[userId]; return }
  const res = await request.get(`/api-keys/full/${userId}`)
  if (res.data?.key) { revealedKeys.value[userId] = res.data.key }
}
```

**参考**：`Platform-MCP-frontend/src/views/user/UserPage.vue`。

---

### 3.13 API Key 复制按钮：掩码状态下也必须 fetch 明文

**现象**：用户管理 API Key 列点"复制"，剪贴板里是掩码 `pmcp_a******yz` 而非明文。

**根因**：`copyUserKey(userId, maskedFallback)` 复制 `revealedKeys[userId] || maskedFallback`，用户没点过眼睛时永远复制掩码。

**解决**：复制时主动 fetch 明文：
```typescript
async function copyUserKey(userId: number, maskedFallback: string) {
  let key = revealedKeys.value[userId]
  if (!key) {
    const res = await request.get(`/api-keys/full/${userId}`)
    if (res.data?.key) { key = res.data.key; revealedKeys.value[userId] = key }
  }
  navigator.clipboard.writeText(key || maskedFallback)
}
```

**参考**：`Platform-MCP-frontend/src/views/user/UserPage.vue`。

---

### 3.14 原型对齐：严格按 documents/ui/Platform-MCP-portal.html，禁自写 CSS

**现象**：页面样式与设计稿差距明显，用户反复反馈"色彩不对""按钮布局不同"。

**根因**：开发者凭印象写 CSS，未严格对照原型 HTML 和 UI 样式规范。

**解决**：
1. 所有页面改动前先 Read `documents/ui/Platform-MCP-portal.html` 对应章节。
2. 复用 global.css 中已定义的原型类（`.card / .toolbar / .data-table / .btn / .tag-*`），不新增样式。
3. 新增组件先在原型 HTML 中设计，再把 CSS 提到 global.css。

**参考**：UI 原型、UI 样式规范、`Platform-MCP-frontend/src/styles/global.css`。

---

### 3.15 隐藏假 input 消耗 autofill（autocomplete="off" 不够）

**现象**：el-form 加了 `autocomplete="off"`，浏览器还是 autofill。

**根因**：现代浏览器（Chrome/Edge）对 `autocomplete="off"` 不完全尊重，特别是密码字段。

**解决**：见 3.2，加隐藏假 input 消耗 autofill + 真实字段用 `autocomplete="new-password"`。

**参考**：`Platform-MCP-frontend/src/views/user/UserPage.vue`、MDN autocomplete 文档。

---

### 3.16 Element Plus form 级 validate() 聚合会吞掉校验失败（promise 误报 true）

**现象**：`el-form` 绑定 `:model`/`:rules`、`el-form-item` 声明 `prop` 均正确，空值时 `await formRef.validate()` 却 resolve `true`，提交未被拦截；但 `formItem.validate(callback)` 的 callback 能正确收到 `false`。

**根因**：EP 2.8.1 `form-item` 的 promise 链中，校验失败的 rejection reason（应为 `{server_code: [...]}` 形态的 fields 对象）丢失为 `undefined`；form 级 `doValidateField` 聚合循环里 `validationErrors = {...validationErrors, ...fields}` 对 `undefined` 展开 → 空对象 → 误判"全部通过"。字段级错误提示（error div）不受影响（`onValidationFailed` 在 reason 丢失前已设置 message）。

**解决**：提交拦截不要只依赖 `formRef.validate()` 的 promise 结果——`handleSubmit` 先做本地确定性 guard（trim 判空 + `ElMessage.error` + return），再调 `validate()` 作为浏览器端第二道防线；`:rules` 保留用于失焦时的字段级错误展示。

**参考**：`node_modules/element-plus/es/components/form/src/form2.mjs`（doValidateField 聚合）、`form-item2.mjs`（validate catch 链）、`BUG20260814134000` 修复过程实录。

---

## 4. MCP 协议

### 4.1 双传输模式：stdio / streamable-http 切换

**现象**：开发者不清楚何时用 stdio 何时用 http。

**根因**：两种模式各有适用场景，未在文档中明确。

**解决**：
| 场景 | 模式 | 配置 |
|------|------|------|
| 本地开发调试 | stdio | Claude Code `.claude.json` 用 `command+args` |
| 生产服务器部署 | streamable-http | Claude Code `.claude.json` 用 `url+transport+headers` |

`settings.mcp.transport` 切换：`stdio` 或 `streamable-http`。

**参考**：`platform_mcp/config.py:76`、`platform_mcp/mcp_server/__init__.py:73`、部署规范 §MCP Server。

---

### 4.2 stdio 模式凭证载体：env PLATFORM_MCP_API_KEY

**现象**：stdio 模式下 MCP Server 不知道当前用户是谁。

**根因**：stdio 模式是子进程，无 HTTP Header。

**解决**：Claude Code `.claude.json` 配置：
```json
{
  "mcpServers": {
    "Platform-MCP": {
      "command": "python",
      "args": ["-m", "platform_mcp.mcp_server"],
      "env": { "PLATFORM_MCP_API_KEY": "<your-api-key>" }
    }
  }
}
```
MCP Server 启动时从 `os.getenv("PLATFORM_MCP_API_KEY")` 读取，校验后进程级绑定身份。

**参考**：`platform_mcp/mcp_server/__init__.py:115`、MCP 接入指南页。

---

### 4.3 http 模式凭证载体：Header PLATFORM_MCP_API_KEY

**现象**：streamable-http 模式下 MCP Server 不知道当前用户是谁。

**根因**：HTTP 模式每请求独立，需 Header 校验。

**解决**：Claude Code `.claude.json` 配置：
```json
{
  "mcpServers": {
    "Platform-MCP": {
      "url": "http://<host>:<port>/mcp",
      "transport": "http",
      "headers": { "PLATFORM_MCP_API_KEY": "<your-api-key>" }
    }
  }
}
```
Starlette middleware 每请求读 Header，校验后 ContextVar set 身份。

**参考**：`platform_mcp/mcp_server/__init__.py:84`。

---

### 4.4 Header 名称统一（禁用 X-API-Key 别名）

**现象**：历史代码中出现过 `X-API-Key` 和 `PLATFORM_MCP_API_KEY` 两种 Header 名，配置混乱。

**根因**：早期文档示例用 `X-API-Key`，后统一为 `PLATFORM_MCP_API_KEY`，但部分代码/文档未对齐。

**解决**：全局统一 `PLATFORM_MCP_API_KEY`（同时兼容下划线/连字符两种命名）：
- 后端（纯 ASGI 中间件直接遍历 scope headers）：`if name in (b"platform_mcp_api_key", b"Platform-MCP-api-key")`
- 前端 Guide 页：两套配置示例都用 `PLATFORM_MCP_API_KEY`
- 文档：禁用 `X-API-Key` 别名

**参考**：`platform_mcp/mcp_server/__init__.py:_AuthMiddleware`、MCP 接入指南页。

---

### 4.5 McpContext.operator 从认证身份读，回退 mcp://{operator_role}

**现象**：审计日志中 operator 显示 `mcp://admin` 而非真实用户名。

**根因**：`McpContext.operator` 设计：优先从认证身份（API Key 校验结果）读 `username`；未设置时回退 `mcp://{settings.mcp.operator_role}`（兼容无 Key 的遗留场景）。

**解决**：
- 生产部署必须配 API Key，operator 才能正确显示真实用户。
- 遗留场景（无 Key）审计会显示 `mcp://admin`，可接受但需文档说明。
- `platform_mcp/mcp_server/context.py:33` 实现此逻辑。

**参考**：`platform_mcp/mcp_server/context.py:22`、架构文档 §8.6 MCP Context。

---

## 5. 配置与部署

### 5.1 crypto-secret.key 是 AES 主密钥，丢失即数据源密码全废

**现象**：迁移项目时漏 copy `crypto-secret.key`，新机无法解密任何数据源密码。

**根因**：所有 `encrypted_password` 字段用 `crypto-secret.key` 作 AES-GCM 主密钥加密，密钥丢失后密码学上无法恢复（即使有密文）。

**解决**：
- `crypto-secret.key` 必须随项目 copy，禁止遗漏。
- 备份策略：将 `crypto-secret.key` 单独加密存到密码管理器（1Password / Bitwarden）。
- `.gitignore` 忽略 `*.key`，必须手动迁移，**不要走 git**。

**参考**：加密方案 §3、`.gitignore`、`platform_mcp/datasource/manager.py:_get_crypto_utils`。

---

### 5.2 settings.yml 含 PG 密码，.gitignore 忽略，迁移手动 copy

**现象**：git clone 后 `settings.yml` 不存在，后端启动报 `database connection failed`。

**根因**：`settings.yml` 含 PostgreSQL 密码（`hdQsjJoY$hJySXZketda`），`.gitignore` 忽略。

**解决**：
- 迁移时手动 copy `settings.yml`。
- 或新机重新生成：参考 `settings.yml` 模板填新密码。
- `settings-dev.yml` / `settings-prod.yml` 同理。

**参考**：`settings.yml`、`.gitignore`、部署规范 §配置文件。

---

### 5.3 poc/config.yml 含目标库密码，.gitignore 忽略

**现象**：git clone 后 POC 无法跑，`poc/config.yml` 不存在。

**根因**：`poc/config.yml` 含 Oracle APP-SAMPLE-1 + MySQL APP-SAMPLE-2 真实密码，`.gitignore` 忽略。

**解决**：
- 迁移时手动 copy `poc/config.yml`。
- 或新机从 `poc/config.example.yml` 复制后填新密码。

**参考**：`poc/config.yml`、`.gitignore`、`poc/config.example.yml`。

---

### 5.4 Oracle Instant Client 路径硬编码（跨机器需改）

**现象**：迁移到新机器后，Oracle 数据源连接报 `DPI-1040 / libclntsh.so not found`。

**根因**：`settings-dev.yml` 和 `poc/config.yml` 硬编码 `D:\Software\Oracle\11g_x64\client_1`，新机器若装在不同路径会找不到。

**解决**：
- 新机器装 Oracle Instant Client 11g x64（必须 11g，thick mode）。
- 修改 `settings-dev.yml` 第 10 行 + `poc/config.yml` 的 `instant_client_dir` 指向新路径。
- 路径用双反斜杠：`D:\\Software\\Oracle\\...`（YAML 转义）。

**参考**：`settings-dev.yml:10`、`poc/config.yml`、部署规范 §Oracle Client。

---

### 5.5 迁移：整个目录 copy + 装 4 个依赖

**现象**：开发者问"迁移到新电脑是不是整个目录 copy 就可以？"

**根因**：项目除源码外还有 4 个外部依赖：Python 3.11.9、PostgreSQL 16.4、Oracle Instant Client 11g、Node.js 22+。

**解决**：迁移步骤清单：
1. 装 Python 3.11.9（推荐 pyenv-win）
2. 装 PostgreSQL 16.4（密码与 settings.yml 一致或改 settings.yml）
3. 装 Oracle Instant Client 11g x64 到 `D:\Software\Oracle\11g_x64\client_1`
4. 装 Node.js 22+
5. xcopy 整个项目目录（含 `crypto-secret.key` + `settings.yml` + `poc/config.yml`）
6. 删除 `Platform-MCP-frontend/node_modules`（跨平台差异）
7. `pip install -e ".[dev]"`
8. `createdb platform_mcp && python -m alembic upgrade head`
9. `python scripts/_seed_skill.py && python scripts/_import_poc_datasources.py`
10. `cd Platform-MCP-frontend && npm install`
11. 启动：`python -m platform_mcp.main` + `npm run dev`

**参考**：部署规范 §迁移、CLAUDE.md §Development Commands。

---

### 5.6 node_modules 跨机器不 copy，新机 npm install

**现象**：跨机器 copy `node_modules` 后 npm 启动报 `EBINANY` 或 native 模块加载失败。

**根因**：`node_modules` 中部分包含平台特定的 native 二进制（esbuild、rollup、swc），Windows/Linux/macOS 二进制不通用。

**解决**：
- 跨机器迁移时**删除 node_modules**，新机 `npm install` 重新装。
- `.gitignore` 已忽略 node_modules，走 git clone 自动正确。

**参考**：`.gitignore`、Node.js 平台二进制文档。

---

### 5.7 .gitignore 还忽略 PostgreSQL/ 数据目录与 logs/

**现象**：开发者以为 git clone 能拿到完整数据，实际数据库数据目录和日志都不在 git 中。

**根因**：`.gitignore` 忽略：
- `PostgreSQL/`（本地 PG 数据目录，体积大且机器特定）
- `logs/` + `*.log`（运行时生成）
- `.claude/`（Claude Code 本地配置）
- `.codegraph/`（CodeGraph 索引）
- `.idea/` / `.vscode/`（IDE 配置）

**解决**：
- 数据库数据**不 copy**，新机重装 PostgreSQL + 跑 alembic + seed。
- 日志可丢，新机重新生成。
- `.claude/` 中 `settings.local.json` 含本地权限配置，按需 copy。

**参考**：`.gitignore`。

---



## 5.X Server Skill 落地避坑（2026-08-07）

| # | 现象 | 根因 | 解决 |
|---|------|------|------|
| 1 | `asyncssh` connect 报 `Permission denied (publickey)` | 服务器未配置 SSH 公钥 | 在 `pmcp_server.encrypted_password` 存 AES 密文密码（与 ssh_key 二选一） |
| 2 | SSH 长连接断开导致 execute_command 挂起 | 未设 `command_timeout` | `pmcp_server.command_timeout` 默认 300s，async with 自动关闭 |
| 3 | confirm_token 复用返回 "无效或已过期" | token 设计为一次性消费 | 每次重新调用获取新 token；测试用例覆盖反重放 |
| 4 | PROD 环境 LOW 命令被升 CRITICAL | `permission.py:check_env_permission` 强制 PROD 升 CRITICAL | 预期行为；developer 角色无 PROD 权限，admin 也需 confirm_token |
| 5 | upload_file 提示 "生产环境必须配置 allowed_sql_dirs" | settings.yml `allowed_sql_dirs: []` 为空 | 预期行为（安全策略）；如需启用，配置路径白名单后重启 |

## 5.Y mypy 引入避坑（2026-08-08）

| # | 现象 | 根因 | 解决 |
|---|------|------|------|
| 1 | `async_sessionmaker[AsyncSession]` has no attribute `__aenter__` | 直接 `async with factory as session`（factory 是 maker 不是 session） | 改为 `async with factory() as session`（多一对括号） |
| 2 | `None not callable` 全工程 7 处 | `async_session_factory = None` 全局变量，mypy 推导为 None | 加 `get_session_factory()` helper 返回非 None 类型 |
| 3 | `Returning Any from function declared to return str` | passlib/sqlparse 等三方库返回 Any | 用 `str()` / `bool()` 包装固化类型 |
| 4 | `Item "None" of "Match | None" has no attribute "group"` | regex.search 返回 Optional | 单次 search 赋值变量后 None 检查 |
| 5 | `Redundant cast to "PmcpServer | None"` | SQLAlchemy stubs 已正确推导 scalar_one_or_none | 删除 cast，让 mypy 自动推导 |
| 6 | `FromClause has no attribute "delete"` | SQLAlchemy 2.0 strict typing | 改用 `delete(Table).where(...)` 函数式 API |
| 7 | `Unreachable statement` | 强制类型注解 `srv: PmcpServer` 让 None 检查失效 | 改用 `cast(PmcpServer | None, ...)` 保留 Optional 推导 |


## 5.Z 部署路径一致性与跨环境迁移避坑（2026-08-08）

| # | 现象 | 根因 | 解决 |
|---|------|------|------|
| 1 | 前端代码部署多次，浏览器刷新后"效果没变" | 服务端 FastAPI 实际加载路径是 `{APP}/ui/dist`（main.py:150 `_CWD_DIST=cwd/'ui'/'dist'`），但部署脚本传到了 `{APP}/Platform-MCP-frontend/dist`，两个目录互不可见 | main.py 探测路径统一改为 `Platform-MCP-frontend/dist`（与源码项目名一致），删除 `ui/` 目录 |
| 2 | el-dialog 内的 scoped `:deep()` CSS 完全不生效 | el-dialog 通过 `<Teleport to="body">` 挂到 body，scoped CSS 的 `[data-v-xxx]` 祖先选择器在 teleported DOM 上不存在 | 改用非 scoped `<style>` 块 + `.audit-detail-dialog` 类锚点；或直接用 inline style (`:style="{...}"`) 绕过 specificity |
| 3 | 浏览器加载了不存在的 `AuditPage-B2IG8ovU.js`（服务端 404） | 浏览器缓存了旧 index.html（在加 `Cache-Control: no-cache` 头之前的版本），旧 index.html 引用的旧 hash 已被新部署覆盖删除 | 用 curl 直连服务端 `/` 看 `index.html` 实际引用，与浏览器 Network 对比；F12 → Application → Clear site data 彻底清缓存 |
| 4 | 审计日志详情字段太长，外部 CSS class 加 `!important` 也不生效 | el-descriptions 用 `<table>` 布局，长 token 拉伸 `<td>`；table-layout 默认 `auto`，word-break 无效 | 长字段内容用 `<span :style="...">` inline style 包裹（绕过所有 CSS 层级）；保留 el-descriptions 原始布局，不破坏视觉 |
| 5 | 服务端 `crypto-secret.key` 解密失败，提示密钥不匹配 | 服务端 crypto key 在 `{APP}/secret/crypto-secret.key`（子目录），与本地仓库根 `crypto-secret.key` 路径不一致；脚本读错文件 | 路径统一：服务端 crypto key 也放在 `{APP}/crypto-secret.key`（根），settings.yml + settings-prod.yml 都用相对路径 `crypto_key_path: "crypto-secret.key"` |
| 6 | 跨环境（本地→服务端）迁移 pmcp_server 数据，密文无法在目标环境解密 | 每环境独立 crypto key（CLAUDE.md 部署原则），明文一样的密码在 A 环境 encrypt 后用 B 环境 decrypt 失败 | 迁移脚本三步：①源 crypto key decrypt 拿明文 ②目标 crypto key 重新 encrypt ③写入目标 DB。`scripts/_migrate_servers.py` 是参考模板（一次性，使用后删除） |
| 7 | "我已经部署了"但其实没生效，反复多轮无效修复 | 只查"上传的目录"的 MD5 hash（自己传错地方也匹配），没查"FastAPI 实际加载的目录" | 验证步骤必须包含 `curl http://server/api/v1/health` + `curl http://server/` 看实际 index.html 引用的 JS hash + 浏览器实际加载的 hash 三方对齐 |
| 8 | 服务端 `Platform-MCP-frontend/dist` 和 `ui/dist` 同时存在，搞不清哪个是源 | 历史遗留双目录 + 多次部署污染 | 路径一致性原则：除 APP 根和 DB 根外，所有相对路径与源码仓库**完全一致**。`ui/` 目录作 stale 删除，唯一加载路径是 `Platform-MCP-frontend/dist` |
| 9 | 服务端 APP 根目录散落 `empty_sql_dirs.py` / `import_poc_inline.py` / `sync_remaining.py` 等临时脚本 | 历次部署/调试遗留 | 部署后清理 checklist：所有临时 `.py` 必须放在 `scripts/` 且用 `_` 前缀（一次性），不在 APP 根目录留散文件 |
| 10 | datasource rename 时担心 FK 级联失败 | 实际 `pmcp_datasource_permission_datasource_id_fkey` 引用 `pmcp_datasource(id)`（BIGINT 主键），不是 `datasource_code`（字符串）；rename code 不影响 FK | rename 前先查 `pg_constraint.confrelid`，确认无 FK 引用目标列后直接 UPDATE |


## 6. 测试

### 6.1 admin_client / dev_client fixture 用 mock_db + dependency overrides

**现象**：集成测试不知道如何 mock 数据库和认证。

**根因**：FastAPI 依赖注入需用 `app.dependency_overrides` 覆盖。

**解决**：`tests/conftest.py` 提供 fixture：
```python
@pytest.fixture
async def admin_client(mock_db):
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "username": "admin", "role_code": "admin", ...
    }
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```
`mock_db` fixture 提供 `AsyncMock` session 返回空结果。

**参考**：测试规范 §集成测试、`tests/conftest.py`。

---

### 6.2 mock target 规则：顶层导入 vs 函数内导入

**现象**：单元测试 mock 不生效，patch 路径不对。

**根因**：Python import 机制决定 patch 路径：
- 模块顶层 `from X import Y` → Y 已绑定到当前模块 → patch `importing_module.Y`
- 函数内 `from X import Y` → Y 在函数调用时才查找 → patch `X.Y`（源模块）

**解决**：
```python
# 被测代码 module_a.py 顶层: from X import Y
# 测试: patch("module_a.Y", ...)

# 被测代码 module_a.py 函数内: def f(): from X import Y; Y()
# 测试: patch("X.Y", ...)
```

**参考**：测试规范 §mock 规则、Python import 机制文档。

---

### 6.3 oracledb 函数内导入 → patch.dict(sys.modules)

**现象**：测试 Oracle 相关代码时报 `ModuleNotFoundError: No module named 'oracledb'`（测试环境未装 oracledb）。

**根因**：`oracledb` 在函数内 import，patch 路径找不到。

**解决**：
```python
mock_oracledb = MagicMock()
with patch.dict(sys.modules, {"oracledb": mock_oracledb}):
    # 调用被测函数，函数内 import oracledb 时拿到 mock
    ...
```

**参考**：测试规范 §native 驱动 mock、`tests/unit/test_oracle_executor.py`。

---

### 6.4 asyncio.run_in_executor 测试 → async def run_sync 同步执行

**现象**：Oracle thick mode 测试覆盖率上不去（run_in_executor 的闭包未执行）。

**根因**：测试中 `loop.run_in_executor(None, sync_fn)` 在 event loop 关闭后才有结果，覆盖率统计漏掉闭包代码。

**解决**：mock event loop 让闭包同步执行：
```python
@pytest.fixture
def mock_event_loop():
    loop = MagicMock()
    loop.run_in_executor = lambda pool, fn: asyncio.ensure_future(
        asyncio.sleep(0, result=fn())
    )
    # 或更简单：
    async def run_sync(_, fn):
        return fn()
    loop.run_in_executor = run_sync
    return loop
```

**参考**：测试规范 §覆盖率技巧、`tests/unit/test_oracle_executor.py`。

---

## 7. 文档规范

### 7.1 CLAUDE.md 行号必须核对实际位置

**现象**：CLAUDE.md 写"config.py line 95-96"，实际是 line 99-100，开发者按行号跳转找不到。

**根因**：文档撰写时基于早期版本行号，代码改动后未同步。

**解决**：
- 文档中引用行号时必须当时 Read 核对。
- 行号易变，建议同时写函数名/类名作为锚点（如 `config.py:get_settings`）。

**参考**：CLAUDE.md §Configuration system。

---

### 7.2 脚本描述必须核对实际功能（_setup_local/_seed_skill/_verify_imports）

**现象**：CLAUDE.md 把 `_setup_local.py` 写成"全量初始化"，实际只做 crypto key + alembic + 用户检查；把 `_verify_imports.py` 写成"校验 skill + datasource 导入"，实际是验证模块 import。

**根因**：脚本名容易望文生义，未实际读取脚本顶部 docstring。

**解决**：脚本描述撰写时必须 Read 脚本头部 docstring + head -20 看实际逻辑。

**参考**：`scripts/_setup_local.py`、`scripts/_seed_skill.py`、`scripts/_verify_imports.py`。

---

### 7.3 测试数字必须实测（pytest --collect-only + vitest list）

**现象**：CLAUDE.md 写"323 backend + 22 frontend"，实际数字可能因新增/删除测试变化。

**根因**：测试数会随开发进度变化，文档易过时。

**解决**：每次更新 CLAUDE.md 时实测：
```bash
python -m pytest tests/ --collect-only -q | tail -3       # backend count
cd Platform-MCP-frontend && npx vitest list 2>&1 | grep -E "\.test\.ts|\.spec\.ts" | wc -l  # frontend count
```
或写"约 320+ backend / 20+ frontend"用模糊表述。

**参考**：CLAUDE.md §Project state。

---

### 7.4 每轮文档审核独立从头，禁用历史记忆

**现象**：文档审核时因"熟悉代码"跳过某些检查，导致上次通过的项这次漏掉。

**根因**：人类/AI 都有惯性思维，沿用上次结论。

**解决**：CLAUDE.md §文档审核标准 已明文规定：
- 每次文档审核都是独立的全新开始
- 不得沿用历史审核的记忆、结论或"已通过"假设
- 所有交叉校验必须从头执行
- 即使某项在上一轮确认通过，本轮也必须重新验证

**参考**：CLAUDE.md §文档审核标准 规则二。

---

## 附录：使用本文件的方式

1. **新功能开发前**：扫描对应类别（如新前端页面看 §3，新 API 看 §2），避免重复踩坑。
2. **代码 review 时**：作为 checklist，逐项核对。
3. **新人 onboarding**：先读本文件了解项目陷阱地图，再读架构文档。
4. **问题复盘**：新遇到的问题追加到对应类别，保持文档演进。
