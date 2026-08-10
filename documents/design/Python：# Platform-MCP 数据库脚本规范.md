# Platform-MCP 数据库脚本规范

> **文档名称**：Platform-MCP 数据库脚本规范
> **基于文档**：《Platform-MCP 技术架构说明文档》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | V1.0 | 2026-08-08 12:00:00 | 正式发布 | 一期 + Server Skill 二期专项全量上线 | castle |
>
> **适用对象**：后端开发、数据库管理员
> **文档用途**：规范 Platform-MCP 项目数据库脚本命名、编写、迁移管理与变更控制

---

## 一、数据库概述

### 1.1 系统库（PostgreSQL 16.4）

存储所有系统元数据，使用 `pmcp_` 前缀。包含用户、角色、权限、数据源、审计日志、Skill 注册等全部系统表。通过 SQLAlchemy 2.0 AsyncSession + asyncpg 访问，使用 Alembic 管理迁移。

### 1.2 目标库（Oracle 11g / MySQL 5.6）

业务执行目标数据库，**不存储系统表**。通过原始驱动（oracledb thick 模式 / aiomysql）建立按需连接，不长期持有连接池。无迁移管理需求。

### 1.3 管理工具

| 数据库 | 迁移工具 | 说明 |
|--------|---------|------|
| PostgreSQL 16.4 | Alembic | 系统库表结构版本管理 |
| Oracle 11g | 无 | 目标库，仅执行业务 SQL |
| MySQL 5.6 | 无 | 目标库，仅执行业务 SQL |

### 1.4 双命名体系（V1.0 发布版）

V1.0 重构数据库脚本结构，采用 **双命名体系** 区分 runtime migration 与 fresh-install 渲染产物：

| 体系 | 位置 | 格式 | 用途 | 示例 |
|------|------|------|------|------|
| **alembic 序号** | `alembic/versions/` | `<NNN>_<snake_case>.py` | runtime migration（autogenerate 增量） | `001_initial_tables.py` |
| **db 时间戳** | `documents/db/` | `<yyyymmddHHMMSS>_<snake_case>.sql` | fresh-install 渲染产物 | `20260808120000_initial_schema.sql` |

**两体系不混用**。alembic 用序号（便于人工追踪迭代链），documents/db/ 用时间戳（与运维部署习惯对齐，便于版本归档排序）。

**当前发布版（V1.0）状态**：
- `alembic/versions/001_initial_tables.py`：单一发布修订，合并历史 10 个迭代（ba0102b846dd → ch0101a947f6）最终态
- `documents/db/20260808120000_initial_schema.sql`：DDL 渲染（15 张 pmcp_* 表 + 索引 + 约束）
- `documents/db/20260808120001_seed_data.sql`：DML 渲染（admin/developer 角色 + admin 用户）
- `documents/db/历史存档/V0/`：发布前 15 个迭代归档（10 alembic .py + 5 历史 .sql）

详细工作流见《部署规范.md §十二·五》。

---

## 二、Alembic 迁移规范

### 2.1 迁移文件命名

Alembic 自动生成迁移文件，格式为 `<revision_id>_description.py`：

```
alembic/versions/
├── 001_initial_tables.py              # 初始表结构
├── 002_add_pmcp_skill_table.py         # 新增 pmcp_skill 表
└── 003_add_audit_log_indexes.py       # 审计日志索引优化
```

### 2.2 迁移文件编写规则

- 使用 `alembic revision --autogenerate -m "描述"` 自动生成
- **不可修改已执行的迁移文件**
- 新增变更仅创建新迁移文件
- `upgrade()` 和 `downgrade()` 必须成对编写
- 自动生成的迁移需人工审核后提交

```python
# 迁移文件模板
"""add pmcp_skill table

Revision ID: 002
Revises: 001
Create Date: 2026-06-03 09:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "pmcp_skill",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("skill_code", sa.String(64), nullable=False, comment="Skill 编码"),
        sa.Column("skill_name", sa.String(128), nullable=False, comment="Skill 名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="Skill 描述"),
        sa.Column("status", sa.SmallInteger(), server_default="1", comment="状态 1-启用 0-禁用"),
        sa.Column("register_method", sa.String(32), nullable=True, comment="注册方式"),
        sa.Column("tool_count", sa.SmallInteger(), server_default="0", comment="Tool 数量"),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_pmcp_skill"),
    )
    op.create_index("un_pmcp_skill_skill_code", "pmcp_skill", ["skill_code"], unique=True)

def downgrade() -> None:
    op.drop_index("un_pmcp_skill_skill_code", table_name="pmcp_skill")
    op.drop_table("pmcp_skill")
```

> **主键约束命名说明**：上例 `PrimaryKeyConstraint("id", name="pk_pmcp_skill")` 为显式命名，**显式命名是可选优化**——实际 V1.0 发布修订 `alembic/versions/001_initial_tables.py` 采用 `sa.PrimaryKeyConstraint("id")`（不显式命名，PostgreSQL 自动生成 `<table>_pkey`），两者等价。新迁移两种风格均可，统一即可。

### 2.3 迁移执行命令

```bash
# 生成迁移（自动检测 Model 变更）
alembic revision --autogenerate -m "描述"

# 执行所有待执行迁移
alembic upgrade head

# 回退一步
alembic downgrade -1

# 查看迁移历史
alembic history

# 查看当前版本
alembic current

# 查看 SQL（不执行）
alembic upgrade head --sql
```

---

## 三、命名规范

### 3.1 表命名

| 对象 | 规则 | 示例 |
|------|------|------|
| 系统表 | `pmcp_名称` | `pmcp_user`, `pmcp_datasource`, `pmcp_audit_log` |
| 关联表 | `pmcp_实体1_实体2` | `pmcp_user_role`, `pmcp_role_permission`, `pmcp_datasource_permission` |
| 字段名 | snake_case | `user_name`, `inserted_at`, `encrypted_password` |

### 3.2 主键命名

| 场景 | 主键字段 | 类型 | 示例 |
|------|---------|------|------|
| 实体表 | `id` | BIGSERIAL | `pmcp_user.id`, `pmcp_datasource.id` |
| 关联表 | `id` | BIGSERIAL | `pmcp_user_role.id`, `pmcp_role_permission.id` |

### 3.3 索引命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 主键约束 | `pk_表名` | `pk_pmcp_user`（PostgreSQL 自动） |
| 唯一索引 | `un_表名_字段名` | `un_pmcp_user_username` |
| 普通索引 | `idx_表名_字段名` | `idx_pmcp_audit_log_inserted_at` |
| 联合索引 | `idx_表名_字段1_字段2` | `idx_pmcp_audit_log_user_id_action` |

---

## 四、字段类型规范（PostgreSQL）

| 场景 | 类型 | 说明 |
|------|------|------|
| 主键 | `BIGSERIAL` | 自增主键，等价于 BIGINT + sequence |
| 短文本 | `VARCHAR(N)` | 按实际长度定义，不用统一 255 |
| 长文本 | `TEXT` | 备注、描述 |
| 精确数值 | `NUMERIC(M,N)` | 金额类，禁止 FLOAT |
| 布尔 | `BOOLEAN` | true/false |
| 时间 | `TIMESTAMP WITH TIME ZONE` | 统一时区处理 |
| 状态/枚举 | `SMALLINT` | 配合注释说明枚举值含义 |
| JSON 扩展 | `JSONB` | 预留扩展数据，为二期新增 Skill 提供灵活结构 |
| 密码密文 | `VARCHAR(512)` | AES:base64 格式密文 |

---

## 五、通用字段约定

### 5.1 审计字段模板

所有系统表必须包含以下审计字段：

```python
# SQLAlchemy Model 审计字段混入
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

class AuditMixin:
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    inserted_by: Mapped[str | None] = mapped_column(String(64))
    updated_by: Mapped[str | None] = mapped_column(String(64))
```

等效 PostgreSQL DDL：

```sql
inserted_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
inserted_by  VARCHAR(64),
updated_by  VARCHAR(64),
```

### 5.2 扩展字段

审计日志表 `pmcp_audit_log` 使用 JSONB 类型存储扩展数据：

```sql
metadata JSONB DEFAULT '{}'::jsonb  -- 预留扩展：数据源编码、环境、风险等级等
```

### 5.3 软删除

使用 `status` 字段管理启停状态（1=启用，0=禁用），不做物理删除。

---

## 六、SQLAlchemy Model 规范

### 6.1 Model 基类

```python
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, SmallInteger, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class BaseModel(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    inserted_by: Mapped[str | None] = mapped_column(String(64))
    updated_by: Mapped[str | None] = mapped_column(String(64))
```

### 6.2 Model 编写示例

```python
class PmcpUser(BaseModel):
    __tablename__ = "pmcp_user"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    remark: Mapped[str | None] = mapped_column(String(512))
```

### 6.3 Alembic env.py 配置

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from platform_mcp.common.database import Base  # 导入所有 Model

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

---

## 七、查询规范

- **禁止** `SELECT *`，明确列出字段
- 分页查询使用 `OFFSET / LIMIT`
- 大表查询必须有索引覆盖或 `LIMIT`
- 禁止在 WHERE 条件中对索引列使用函数
- 使用 SQLAlchemy 2.0 `select()` 语法，禁止 1.x `query()` 语法

```python
# 正确
stmt = select(PmcpUser.username, PmcpUser.nickname).where(PmcpUser.status == 1).limit(20)

# 禁止
# session.query(PmcpUser).all()
```

---

## 八、索引设计原则

- WHERE / JOIN / ORDER BY / GROUP BY 高频字段建索引
- 联合索引遵循最左前缀原则，区分度高的列放左边
- 单表索引数量建议不超过 5 个（不含主键）
- 禁止在低基数列（如 status）上建独立索引
- 外键字段必须建索引
- JSONB 字段使用 GIN 索引
- 时间序列字段（如 audit_log.inserted_at）建议使用 BRIN 索引

---

## 九、初始化数据规范

### 9.1 默认用户

通过 Alembic 迁移或 seed 脚本创建默认管理员：

| 用户名 | 角色 | 用途 |
|--------|------|------|
| `admin` | admin | 系统管理员，拥有全部权限 |

### 9.2 默认角色

| 角色 | 标识 | 权限范围 |
|------|------|---------|
| 系统管理员 | `admin` | 全页面、全操作权限 |
| 开发人员 | `developer` | Skill 可新增（待审核），数据源仅查看/测试 |

### 9.3 初始化脚本

初始化数据通过 Alembic data migration 或独立 seed 脚本执行，使用 `INSERT ... ON CONFLICT DO NOTHING` 保证幂等性：

```python
def upgrade() -> None:
    op.execute("""
        INSERT INTO pmcp_user (username, password, nickname, status)
        VALUES ('admin', '<passlib_hash>', '系统管理员', 1)
        ON CONFLICT (username) DO NOTHING
    """)
    op.execute("""
        INSERT INTO pmcp_role (role_name, role_code, status)
        VALUES ('系统管理员', 'admin', 1), ('开发人员', 'developer', 1)
        ON CONFLICT (role_code) DO NOTHING
    """)
```

---

## 十、分区策略（二期）

审计日志表数据量增长后采用 PostgreSQL 原生按时间分区：

```sql
-- 二期：pmcp_audit_log 按月分区
CREATE TABLE pmcp_audit_log (
    id BIGSERIAL,
    inserted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    -- ...
) PARTITION BY RANGE (inserted_at);

CREATE TABLE pmcp_audit_log_2026q3 PARTITION OF pmcp_audit_log
    FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
```

---

## 十一、字符集

- PostgreSQL 默认 UTF8 编码，无需额外配置
- 连接字符集：`client_encoding=UTF8`
- 排序规则：使用数据库默认（`libc` provider）
