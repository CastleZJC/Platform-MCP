# Platform-MCP 数据库脚本

> 发布版 DDL/DML 与历史归档目录。

## 目录结构

```
db/
├── README.md                                        ← 本文件
├── 20260808120000_initial_schema.sql                ← 发布版 DDL（V1.0 基线表 + 索引 + 约束）
├── 20260808120001_seed_data.sql                     ← 发布版 DML（admin/developer 角色 + admin 用户）
├── 20260811000000_drop_unused_permission_tables.sql ← migration 002 渲染（DROP 4 张废弃权限表）
├── 20260811000001_phase2_tables_and_skill_extensions.sql ← migration 003 渲染（V2.1 分组 5 表 + skill 扩展）
├── 20260814000000_code_nonempty_check_constraints.sql    ← migration 004 渲染（非空检查约束）
├── 20260902000000_unified_group_roles_locale_skill_status.sql ← migration 005 渲染（V3.0 M0 统一组 + 三角色 + locale + 状态机列）
├── backup/                                          ← 迁移前数据备份（本地专用，.gitignore 不入库）
└── 历史存档/
    └── V0/                                ← 发布前迭代
        ├── db_scripts/                    ← 5 个 .sql（20260605–20260612）
        └── py_scripts/                    ← 10 个 alembic .py（ba0102b846dd–ch0101a947f6）
```

> `backup/` 存放执行破坏性迁移（如 005 统一组合并/DROP）前的 `pg_dump --data-only` 快照，作本地回滚安全网；对远程无意义，已加入 `.gitignore`。

## 命名规范（双重体系）

| 体系 | 位置 | 格式 | 用途 |
|------|------|------|------|
| **alembic 序号** | `alembic/versions/` | `<NNN>_<snake_case>.py` | runtime migration（autogenerate 增量） |
| **db 时间戳** | `db/` | `<yyyymmddHHMMSS>_<snake_case>.sql` | fresh-install 渲染产物 |

两体系不混用。alembic 用序号、db 用时间戳。

## 与 alembic/versions/ 的关系

| 角色 | 文件 | 职责 |
|------|------|------|
| **单一真相源** | `alembic/versions/001_initial_tables.py` | 当前发布版 schema 的 alembic 修订（合并历史 10 个迭代最终态） |
| **渲染产物** | `documents/db/20260808120000_initial_schema.sql` + `documents/db/20260808120001_seed_data.sql` | 等价 raw SQL，便于 fresh-install `psql -f` |

未来 schema 变更：
- 在 `alembic/versions/` 新增 `002_xxx.py`、`003_xxx.py` 增量修订
- 大版本节点重新合并为 `002_initial.py`，归档旧链到 `documents/db/历史存档/V<n-1>/`，重新渲染 `documents/db/` 时间戳脚本

## Fresh-install 部署

```bash
# 方式 A（推荐）：alembic 驱动
createdb -U postgres platform_mcp
PLATFORM_DB_URL='postgresql://postgres:***@host:5432/platform_mcp' alembic upgrade head

# 方式 B：raw SQL（无 alembic 环境）
psql -U postgres -d platform_mcp -f documents/db/20260808120000_initial_schema.sql
psql -U postgres -d platform_mcp -f documents/db/20260808120001_seed_data.sql
```

两方式产出 schema 等价（已 pg_dump diff 验证）。

## 历史归档说明

`documents/db/历史存档/V0/` 含发布前（V1.0 之前）的全部迭代，按文件类型分子目录：
- `db_scripts/` — 5 个 .sql（`20260605090000_*` → `20260612131500_*`）
- `py_scripts/` — 10 个 alembic .py（`ba0102b846dd_*` → `ch0101a947f6_*`）

仅作历史追溯，runtime 不读。
