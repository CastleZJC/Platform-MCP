# Platform-MCP

> 内部 MCP (Model Context Protocol) 能力平台
> 双 Skill：Database（SQL 执行）+ Server（Linux SSH/SFTP）— 共 31 个 MCP 工具（含 Skill 广场/双通道生态），通过 Claude Code 等调用方远程执行，配备 Web 管理台与全链路审计

**语言**: 中文（本文） | [English](README.en.md)

## 项目概览

Platform-MCP 是一个内部 MCP 服务平台，提供：

- **Database Skill（5 tools）**：执行本地 SQL 文件 / SQL 文本 / 风险校验 / 数据源列举 / 异步状态查询
- **Server Skill（6 tools）**：Linux 远程 Shell 执行 / SFTP 上传下载 / 命令风控校验 / 服务器列举 / 异步状态查询
- **双传输 MCP Server**：stdio（环境变量）+ streamable-http（Header）双入口
- **API Key 认证**：双存储（key_hash SHA-256 校验 + key_encrypted AES-GCM admin reveal）
- **Web 管理台**：数据源管理 + 服务器管理 + 用户管理 + API Key 管理 + 审计日志 + 个人设置
- **权限控制**：admin/developer/user 三角色（V3.0 M0 起），developer 禁 PROD；服务器与数据源各自独立权限
- **风险引擎**：SQL 与 Shell 共用 4 级（LOW/MEDIUM/HIGH/CRITICAL），HIGH+ 需 `confirm_token` 反重放二次确认
- **多语种中/英（V3.0 M1）**：前端 vue-i18n 全站 key 化 + 后端资源字典 + MCP 工具描述中英并列；个人设置切换**即时生效**（前端界面与后端生成内容均实时读 `pmcp_user.locale`，无需重新登录）；系统配置 `sys.default_locale` 仅影响未设置个人偏好的用户（新用户初始值），不影响已有偏好的老用户
- **运行时配置中心（V3.0 M1）**：已知键注册表（12 键，生效语义 relogin/immediate，凭证值不回显）+ 30s 快照缓存，默认语言/会话失效时间/日志级别等非重启生效项统一由系统配置页管理
- **双 AI 通道（V3.0 M3/M4）**：Skill 广场 BGE-M3 语义搜索（纯 CPU，pgvector/JSONB 双实现）+ Web 本地生成 Qwen3-4B GGUF（llama-cpp-python 纯 CPU，中英双语报告/README/迭代 diff，权重离线分发、缺失自动模板兜底）+ CC 侧外部大模型 glm 5.3 产物经 MCP 回传重放校验存档（generated_by=template/model/external 三态留痕）
- **邮件组提醒 ×4（V3.0 M5）**：生产 HIGH+ 数据库/服务器操作（审计日志单一咽喉路由）、Skill 审核事件（含结果全量通知提交人）、用户管理安全事件（含连续登录失败锁定 5 次锁 15 分钟）；outbox 模式失败可重试全程可审计，SMTP 参数经运行时配置中心维护（密码 AES-GCM 加密）

## 快速启动

### 前置要求

- Python 3.11.9+（<3.12）
- PostgreSQL 16.4（系统库）
- Oracle 11g / MySQL 5.6（目标库，可选）

### 后端启动

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 创建本地配置（必填 database.url）
cp settings.yml.example settings.yml
# 编辑 settings.yml，替换 <password> / HOST 为你的 PostgreSQL 实际值

# 3. 准备 PostgreSQL：创建库 + 用户
createdb platform_mcp
psql -d platform_mcp -c "CREATE USER pmcp WITH PASSWORD '<your-password>';"

# 4. 设置 Alembic DB URL（用于 migration；可写入 ~/.bashrc 持久化）
export PLATFORM_DB_URL="postgresql://pmcp:<password>@localhost:5432/platform_mcp"

# 5. 生成 crypto 密钥 + Alembic 升级 + 检查 seed 用户
python scripts/_setup_local.py

# 6. 种 database + server skill 到 pmcp_skill 表
python scripts/_seed_skill.py

# 7. 启动 FastAPI Web（默认端口 8000）
python -m platform_mcp.main

# 8. 启动 MCP Server（mode 由 settings.mcp.transport 决定）
python -m platform_mcp.mcp_server
```

### 前端启动

```bash
cd platform-mcp-frontend
npm install
npm run dev    # 默认端口 5173（占用自动递增）
```

访问 `http://localhost:5173`，默认账号：`admin` / `admin123`

### 数据库初始化

```bash
# 生成加密密钥 + Alembic 升级 + 检查 seed 用户
python scripts/_setup_local.py

# 种 database + server skill 到 pmcp_skill 表
python scripts/_seed_skill.py
```

## 技术栈

**后端**：Python 3.11.9 + FastAPI 0.115.0 + SQLAlchemy 2.0.35 + Alembic 1.13.2 + oracledb 2.4.1 + aiomysql 0.2.0 + asyncssh 2.17.0（Server Skill SSH/SFTP）

**前端**：Vue 3.5.34 + Vite 8.0.12 + TypeScript 6.0.2 + Element Plus 2.8.1 + Pinia 2.2.2 + Axios 1.7.4 + vue-i18n ^9.14.5（中/英双语）

**数据库**：PostgreSQL 16.4（系统），Oracle 11g / MySQL 5.6（目标）

## 架构（简化）

```
Claude Code ──stdio(env PLATFORM_MCP_API_KEY)──▶ MCP Server ──┐
           ╲                                        ├──▶ PostgreSQL（系统库，ORM）
            ╲                                       │    Oracle / MySQL（Database Skill 目标）
Claude Code ──HTTP(header PLATFORM_MCP_API_KEY)──▶ ──┤    Linux SSH/SFTP（Server Skill 目标）
                                                │
Browser ──HTTP(session cookie)──▶ FastAPI Web ──┘
```

## 目录结构

```
Platform-MCP/
├── platform_mcp/                # 后端代码
│   ├── api/                     # FastAPI 路由（15 模块：auth/users/datasources/servers/api_keys/skills/groups/system_config/audit/crypto/profile/guide/plaza/notify/kb〔501 占位〕）
│   ├── auth/                    # 认证鉴权 + API Key
│   ├── datasource/              # 数据源管理（DB Skill 目标）
│   ├── server/                  # 服务器管理（Linux SSH 目标，Server Skill 用）
│   ├── skills/
│   │   ├── database/            # Database Skill（5 tools：SQL 执行 + 风控）
│   │   ├── server/              # Server Skill（6 tools：SSH/SFTP + 风控）
│   │   ├── common/              # 共享风控类型（risk_types + permission）
│   │   ├── audit/               # 14 条合规审计引擎（V2.1；内容脱敏已移除）
│   │   ├── readme/ upload/      # README 模板生成 / Skill 包上传链路（V2.1）
│   │   ├── versioning/          # 版本化双语存档（V3.0 M2）
│   │   ├── plaza/ plaza_service/ embedding/  # 广场领域服务 + BGE-M3 向量栈（V3.0 M3）
│   │   ├── ecosystem/           # Skill 生态 MCP 工具 + ToolMeta.roles（V3.0 M2/M3）
│   │   └── llm/                 # 本地生成模型栈 Qwen3-4B（V3.0 M4）
│   ├── mcp_server/              # MCP 协议 + 双传输 + 上下文/审计
│   ├── audit/                   # 审计日志
│   ├── notify/                  # 邮件组提醒（四组 + outbox 发送，V3.0 M5）
│   ├── kb/                      # 三期知识库骨架（五表 ORM + RAG/GRAPH 抽象 + 501 占位，V3.0 M6）
│   ├── i18n/                    # 多语种资源字典（zh-CN/en-US 1:1，V3.0 M1）
│   └── common/                  # 公共组件（database / crypto / response / runtime_config / 等）
├── platform-mcp-frontend/       # 前端代码（Vue 3，12 业务页面另含登录页，含服务器管理/分组管理/系统配置/邮件提醒，vue-i18n 双语）
├── tests/                       # 后端测试（1554 用例）
├── scripts/                     # 工具脚本
├── alembic/                     # 数据库迁移
├── documents/                   # 设计文档
```

## 文档索引

| 文档 | 说明 |
|------|------|
| `CLAUDE.md` | Claude Code 工作指南（项目整体原则） |
| `documents/design/Python：# Platform-MCP 技术架构说明文档.md` | 技术架构（权威来源） |
| `documents/design/Python：# Platform-MCP 代码规范.md` | 编码规范 |
| `documents/design/Python：# Platform-MCP 部署规范.md` | 生产部署 |
| `documents/design/Python：# Platform-MCP 测试规范文档.md` | 测试策略 |
| `CLAUDE.md` § 文档审核标准 | 文档审核规则（嵌入 CLAUDE.md） |
| `documents/ui/Platform-MCP-portal.html` | UI 原型（单文件 HTML） |

## 版本迭代

> **基线 V1.0 = 2026-08-08**。后续生产发布（含 hotfix、迭代版本、配置类变更上线）必须在此表追加一行——详见 `CLAUDE.md §部署原则 #10`。表内行序按里程碑批次优先于日期（如 V2.1 批次行先于其后日期更晚的 hotfix 行）；`pyproject.toml` 的 `version` 为简记（3.0.x），与表内里程碑行非一一对应。

| 版本 | 日期 | 类型 | 摘要 | 修改人 |
|------|------|------|------|--------|
| V3.0-M6 | 2026-09-05 | 迭代 | V3.0 M6 三期 KB 骨架 + 二期收尾（模型：glm 5.3）：**（1）migration 010**（编号顺延：原拆分口径 008，因 008 组去环境维度/009 notify 占用，head=010）——kb 骨架五表：`pmcp_kb`（kb_code UNIQUE + kb_type personal/shared + owner_id + status 值域复用 review 8 状态，三期挂接）/ `pmcp_kb_doc` / `pmcp_kb_chunk`（chunking_strategy 7 枚举 + embedding JSONB 同 plaza 惯例，UNIQUE(doc_id,chunk_index)）/ `pmcp_kb_version`（双语同 pmcp_skill_version）/ `pmcp_kb_share`（审核流三期直接挂接 review 不另建）。**（2）kb 空包四件**——`platform_mcp/kb/`：models.py 五表 ORM + chunking.py（7 切片枚举 + coerce_strategy）+ rag.py（Indexer/Retriever ABC）+ graph.py（GraphStore ABC）。**（3）API 501 占位**——`api/kb.py` 7 端点（列表/创建/详情/上传文档/搜索/图谱/分享）统一 5 字段响应体 code=15002 + 路由注册（api 15 模块）。**（4）文档定稿（F-42 终核）**——架构 §19.6 落地标注 + §14.1 表清单 27 张 / 正式版表数与里程碑行 / db 010 SQL 渲染 / CLAUDE.md 基线。测试：tests/unit/test_kb_skeleton.py 22 用例。验证：pytest 1554 / mypy 0 (108 files) / vitest 174 / vue-tsc 0 / build 通过（F-41 全过；6.4 生产三段式发布属部署动作待实际部署时执行；基线勘误——M5 实测 1532 非 1537，本轮 1554=1532+22 以实测为准） | castle |
| V3.0-M5 | 2026-09-05 | 迭代 | V3.0 M5 邮件组提醒 ×4（模型：glm 5.3）：**（1）migration 009**（编号顺延：原拆分口径 007/008 已被 embedding/组去环境维度占用，head=009）——notify 三表（`pmcp_notify_group` 四事项 + 参数化模板 + enabled 独立启停 + seed 默认模板 / `pmcp_notify_group_member` 仅 admin 入组 / `pmcp_notify_outbox` pending/sent/failed + retry_count）+ `pmcp_user` 加 failed_attempts/locked_until 锁定字段 + aiosmtplib 依赖 + settings notify 段（flush 间隔/批量/最大重试）。**（2）服务层**——`platform_mcp/notify/` service（render_template `{{param}}` 渲染缺参空串 + dispatch 独立 session 异常全捕获不阻断业务 + 停用组静默）/ sender（SMTP 参数经运行时配置中心 smtp.* 五键〔密码 AES-GCM 加密落库、读出透明解密〕+ flush_outbox 未配置仅统计积压不取件、失败 retry+1+error 留痕）/ 周期 flush 任务挂 Web lifespan。**（3）捕捉点三类**——write_audit_log 单一咽喉路由（PROD+HIGH/CRITICAL+sql/datasource→db_high_op、shell/server→server_high_op，覆盖 Web+MCP 双入口）；skill_review 提审/通过/合并/拒绝/撤回五流程点 + 结果全量通知提交人；user_mgmt 用户创建/停用/角色变更/API Key 重置撤销（本人直发）+ 连续登录失败锁定（5 次锁 15 分钟锁定期静默）。**（4）API + 前端**——`api/notify.py` 六端点（组列表/组更新/成员加删/outbox 分页记录/测试发送，错误码 13001-13007）+ NotifyPage（四事项启停/成员管理〔候选仅 admin+无邮箱提示〕/模板编辑含参数说明/outbox 记录/测试发送）+ 路由菜单 adminOnly + i18n 中英。**（5）附带修复**——api_keys.py delete/refresh 两处 user_id 未定义 NameError（mypy 抓出真 bug）+ SMTP 密码加密链三处类型收口。验证：pytest 1537（勘误：实测 1532，见 V3.0-M6 行勘误）/ mypy 0 (102 files) / vitest 174 / vue-tsc 0 / build 通过（F-37/38/39 全过，R-13 SMTP 为生产前置，部署规范 §2.7） | castle |
| V3.0-M4 | 2026-09-05 | 迭代 | V3.0 M4 本地生成模型 + 分享迭代交互（模型：glm 5.3）：**（1）本地生成模型栈**——`platform_mcp/skills/llm/` 三模块：`__init__.py`（provider 实现：QwenLlamaCppProvider——Qwen3-4B GGUF llama-cpp-python 纯 CPU，单槽双层互斥〔per-loop Semaphore(1) 跨 loop 重建 + threading.Lock〕+ 60s 超时 + 进程级单例，权重离线分发 VNF-03、缺失自动降级）+ generation.py（中英 prompt + `replay_validate_artifact` 重放校验〔临时目录重演上传包→14 条审计+脱敏→🔴 拒绝/🟡🟢 透传〕+ `build_iteration_diff` 含 BGE-M3 语义相似度）+ tasks.py（upload 后 BackgroundTasks 异步升级版本存档 report_zh/en + readme_en，VNF-01 无生成等待；测试抓出并修复重放键映射 BUG：report_zh/en→report、readme_en→readme）。**（2）分享迭代内容级**——`GET /skills/{id}/iteration-diff`（广场快照 vs 本地 SKILL.md 行级 diff + 语义相似度 + 双语描述）+ MCP `get_skill_iteration_diff`。**（3）外部通道回传**——MCP `submit_skill_artifact`（CC+glm 5.3 生成产物回传，重放校验后存档 generated_by=external，F-36）。**（4）前端**——SkillPage 分享迭代 Sheet 差异块 + 版本行 generated_by 三态标签 + README/报告弹窗“性能有限建议外部大模型”提示（i18n +10 键）。**（5）权重校验脚本**——`scripts/_init_llm_weights.py`（GGUF 魔数/≥1MB/SHA-256/--probe 加载探测）+ settings.yml.example 补 skill 段（embedding+llm 共 10 键）。工具 29→31（admin 31 / developer 30 / 一般用户 19）。验证：pytest 1470 / mypy 0 (96 files) / vitest 167 / vue-tsc 0 / build 通过 | castle |
| V3.0-M3R | 2026-09-05 | 复核修订 | M3 用户验收反馈批次（4 轮）：**（1）Skill 广场列精简 + admin 停用**——列表不显示版本/分享者/描述（版本轨迹与分享者信息内部保留），RM 入口移至操作列；新增 admin 停用操作（`POST /plaza/{id}/disable` 第 9 端点，停用后全角色 Web+MCP 双端不可见、版本存档与审计保留，可经重新分享恢复）。**（2）Skill 黑名单**——去除"类型"列（黑名单为个人屏蔽清单，无类型维度），补 RM 操作（广场项读 `/plaza/{id}/readme`、个人项读 `/skills/{id}/versions` 最新存档）。**（3）Skill 管理**——删除审计列，审核反馈并入"分享管理"Sheet 审核日志（逐版本结论 + 双语存档报告详情）。**（4）README 双语纯净三轮增强**——split_bilingual「中文 / English」并列描述拆分器（功能描述/工具描述/审核报告按语言拆分，规避内部斜杠误切）；结构重构（去 H1 标题行、功能描述=Skill 真实描述正文、移除"经 MCP 通道创建暂未附源码包"样板段、requirements 依赖清单、文件数统计、generated_by=template 署名 footer）；内置 Skill 描述经 `skill.desc.*` 双语字典取值（RESOURCES 24→26 key，英文 Description 纯英文）。**（5）装饰器注册 Skill 无需审核**——`register_method=decorator` 快速开始 3 步（无审核步骤），upload/form 保留 4 步审核流程。**（6）MCP 接入指南 500 修复**——`guide.py` `status==1` int 字面量对 varchar 状态机类型报错 → `ReviewStatus.ENABLED`。存量版本存档幂等重生成（字段置 NULL → 启动期 backfill 补全）。**（7）运行时配置中心收敛**——KNOWN_KEYS 14→12 键（`mcp.allowed_envs` 移除、`allowed_sql_dirs` 转静态配置、smtp 凭证掩码简化、二次确认移除）。验证：pytest 1385 / mypy 0 (93 files) / vitest 163 / vue-tsc 0 / build 通过 | castle |
| V3.0-M3 | 2026-09-04 | 迭代 | V3.0 M3 广场 + 搜索 + 角色过滤：**（1）Skill 广场**——`pmcp_skill_plaza` 公共池（migration 006，涉库/涉服务器标记 involve_flags 对一般用户 Web+MCP 双端不可见）+ `api/plaza.py` 8 端点（列表/语义搜索/详情/双语 README/复制到个人库/屏蔽/撤销/黑名单清单）+ `plaza_visible_to_role` 双端共用可见性 + 用户黑名单双端过滤。**（2）语义搜索**——fastembed BGE-M3 `EmbeddingStore` 双实现（pgvector / JSONB+内存余弦降级）+ migration 007（`embedding` JSONB 列 + 条件 `embedding_vec` vector(1024) 列，受限时运行期自动降级）。**（3）MCP 角色过滤**——registry `ToolMeta.roles`，工具 11→29 按角色过滤（admin 29 / developer 28 / 一般用户 17），双端承接 review_skill / query_audit_logs / update_profile / change_password。**（4）前端功能广场页**——PlazaPage（广场/黑名单双 Tab、语义搜索 similarity 列、README 双语弹窗、复制/屏蔽/撤销）+ 全角色一级导航 + 一般用户落地页重定向 /plaza。验证：pytest 1340 / mypy 0 (93 files) / vitest 156 / build 通过 | castle |
| V3.0-M2 | 2026-09-03 | 迭代 | V3.0 M2 Skill 生命周期：migration 006（`pmcp_skill_version` 版本化双语存档〔readme/报告 zh+en + audit_snapshot + generated_by 留痕，UNIQUE(skill_id,version) 不可篡改〕、`pmcp_skill_blacklist`、`pmcp_skill` 加 plaza_id/origin/share_status/review_comment）；8 状态 varchar 状态机 + 转移校验 + 个人库可见性过滤；registry 启动与路由真实消费 `pmcp_skill.status` 过滤内置 Skill（勘误 5 关闭）；可复用审核服务抽取（`platform_mcp/review/`，供三期 KB 复用）；MCP 双通道（create_skill_draft 自动扫广场相似推荐 / update_my_skill / submit_skill_for_review / withdraw_review / resolve_share_iteration）；Web 上传链路版本化升级 + 双语审核报告/README 生成（模板兜底 generated_by 留痕）；SkillPage 增强（README 弹窗、分享/更新/迭代 Sheet、admin 审核弹窗）；后端 i18n 字典 16→24 键（8 个状态标签随消费方回加）。验证：pytest / mypy / vitest / vue-tsc 全绿 | castle |
| V3.0-M1 | 2026-09-03 | 迭代 | V3.0 M1 i18n 基建 + 运行时配置中心：**（1）多语种中/英**——前端 vue-i18n 全站 key 化（15 文件 129 用例，localStorage `pmcp_locale`，默认中文）、后端资源字典 RESOURCES（23 key × zh-CN/en-US 1:1 镜像）、11 个 MCP 工具描述中英并列、个人设置 `pmcp_user.locale` 切换经登录快照（`SessionInfo.locale/ttl_seconds`）重新登录生效不重启。**（2）运行时配置中心**——KNOWN_KEYS 注册表 14 键（值类型/生效语义 relogin|immediate/敏感标记/i18n 描述）、30s 快照缓存 + 后台周期刷新、`log.level` 即时热切换（修复 logsetup 缺 global 声明致 UnboundLocalError 隐患）、登录读取点改造（`session.timeout_minutes` TTL + `sys.default_locale` 默认语言）、SystemConfigPage 注册表驱动升级（行 id 合并/已配置-默认态/敏感键掩码+`confirm_sensitive` 二次确认/自定义键并存）+ 侧边栏菜单启用（勘误 4 关闭）。验证：段一全绿（pytest 900、mypy 0/80、vue-tsc 0、vitest 129） | castle |
| V3.0-M0 | 2026-09-02 | 迭代 | V3.0 地基：统一组模型（`pmcp_group` + 3 成员表，migration 005，head=005，存量按"同 env 同名合并"回填并 DROP 旧分组 5 表）、组过滤下沉 manager 层双入口生效（修复 MCP 层组过滤缺口）、一般用户第三角色（role seed `user`）、`pmcp_user.locale` 列、`pmcp_skill.status` varchar 状态机、分组管理/系统配置菜单启用、GroupPage 统一组重写、三页"所属组"列 + admin 行级分组分配、MCP 身份贯通（`McpContext.identity`） | castle |
| V2.1 | 2026-08-13 | 迭代 | 二期首批（commit bd178b6）：Skill 源码上传注册（.7z/.zip ≤50MB → 解压 → SKILL.md frontmatter 解析 → 14 条合规审计〔文件系统/数据库/网络/凭据/结构 5 类，🔴阻止/🟡警告/🟢建议〕→ 内部代号/厂商名/内网 IP 脱敏 → README 模板生成 → `pmcp_skill` 待审核 + `pmcp_skill_audit_report` 每规则存底 + 审核 approve→ENABLED / reject→REJECTED）、分组管理（group ×2 + member ×2 + user_group 五表，admin CRUD+分配 / dev 只读，迁移 005 已并入统一组模型）、系统配置 CRUD API（`/system-configs`，admin 专用）、废弃表清理（migration 002 DROP 4 张权限表）、前端 SkillPage 重写 + GroupPage + SystemConfigPage（路由注册，菜单待启用） | castle |
| V1.1.6 | 2026-08-25 | hotfix | BUG20260824090000 文件通道 PL/SQL 块执行异常：**（1）前导注释/BOM 致块判定失效**——sqlparse 将前导注释并入块语句、read_text(utf-8) 不剥 BOM，块开头正则失配 → 块尾 end; 被误剥（PLS-00103，与 08-24 内部反馈同款报错）/ BOM 更致块被内部分号撕碎成 2 残句；修复：块判定剥前导噪声（BOM/空白/行注释/块注释）后匹配 + 分句屏蔽器跳 BOM + 双读取点 utf-8-sig。**（2）仅注释语句误入分句**——尾注释曾被切成独立 UNKNOWN/HIGH 语句（触发整批 confirm 门、确认后执行必败致整文件失败）；修复：分句末过滤仅注释语句。**（3）Oracle 超时无服务端会话终止**——thick 线程不可取消，超时仅弃权且连接在执行线程脚下关闭，被杀会话在库端继续执行拖垮共享目标库（击杀后 ORA-12170 持续数十分钟）；修复：conn.break_() OOB 打断在飞调用 + 线程回收 + 连接正常关闭（服务端会话终止）+ 超时结果附 source_session（sid/serial）。验证：段一全绿（pytest 821、mypy 0/76、vue-tsc 0、vitest 116）+ 本地实例重启后 11 工具完整性与 4 形态针对性实测全过（详见 documents/bug/BUG20260824090000） | castle |
| V1.1.5 | 2026-08-17 | hotfix | BUG20260817220800 execute_command 多语句静默截断（V1.1.0 引入，V1.1.4 发布当日复核发现）：`echo $$; exec <cmd>` 包装中 POSIX `exec` 用第一条命令替换 shell，`;`/`&&`/`||` 后命令全部静默丢弃（exit 0）——生产实证 `echo A; echo B; pwd; id` 仅回显 A。修复：`exec bash -c {shlex.quote(command)}` 完整承载命令串，审计 source_session PID 捕获语义不变。验证：段一全绿（pytest 801、mypy 0/76、vue-tsc 0、vitest 117）+ 生产实测多语句全量输出 + 五段链式命令按序全执行（详见 documents/bug/BUG20260817220800） | castle |
| V1.1.4 | 2026-08-17 | hotfix | BUG20260814163941 断点续传专项 + BUG20260817123100 SQL 多语句执行异常：**（1）断点续传**——SFTP 腿 `_sftp_put/get_resumable`（r+b/ab 断点续写 + 尺寸完整性校验 + 3 次自动重试，成功/耗尽均清理）；HTTP 腿分片上传 `/transfer/chunk`+`/transfer/merge`（合并尺寸校验，失败保留分片供补传）+ Range 下载 206 + 截断上传校验（收到字节 ≠ Content-Length → 400+清理）；Windows 工作站路径前置识别（报错内嵌双向 curl 中转指引，PLATFORM_MCP_API_KEY）。**（2）SQL 多语句**——text/file 统一 `split_statements` 分句（SQL*Plus `/` 碎片过滤）、多语句低风险逐条执行（statement_count/results[]）、含 HIGH/CRITICAL 直接拒绝 `MULTI_STMT_HIGH_RISK`、confirm_token 绑定 sql_hash 封死换 SQL 复用 + 重试指引、审计 error_code 透传（CONFIRM_REQUIRED 也如实记 error）。**（3）生产冒烟补漏**——uvicorn 真实断开时 `request.stream()` 抛 ClientDisconnect（非 OSError）逃逸 503 且部分落盘不清理（pytest ASGITransport 优雅结束流覆盖不到），upload/upload_chunk 改 400+清理，附 http.disconnect 回归用例。验证：11 工具生产实测 + 专项（100MB SFTP sha256 双端一致 / 20MB 分片中转全链路一致 / Range 206 / 截断 400 零残留）+ 段四标记行清理 0 残留（详见两份 BUG 文档） | castle |
| V1.0.1 | 2026-08-09 | hotfix | 审计日志失败记录完整性增强（合并两次细粒度修复为同日 hotfix）：**（1）error_code 强制捕获**——`call_log.py` PmcpMcpCallLog 构造补 `error_code=error_code`（修前 mcp_call_log 全表 error 行 0/5 有码）；`auth.py` login fail 补 `error_code="11001"`；`crypto.py` encrypt/verify fail 补 `error_code="15001"`；`profile.py` change-password fail 补 `error_code="11004"`。**（2）result_status 枚举统一**——web 层 6 文件 8 处 `'fail'` → `'error'`（auth/crypto/profile/datasources/servers）+ UI `statusLabel` 防御性同时识别 fail/error → 失败 + `audit/models.py` 列 comment 更新为 `(success/error)`。**（3）历史数据 backfill**——UPDATE fail→error 共 2 行 + NULL error_code 按错误信息模式匹配 backfill 6 行（11001/12001/10001/15001），最终态 0 fail 残留 + error 行 error_code 完整率 100%。生产验证：castle.zhang 4 行登录失败记录全 error/11001 ✓；castle.zhang MCP 失败 → audit_log + mcp_call_log 双表 error_code=12001 ✓ | castle |
| V1.0 | 2026-08-08 | 基线发布 | 一期 + Server Skill 二期专项全量上线：11 MCP tools（database 5 + server 6）、15 系统表、9 前端页面、双传输 MCP（stdio + streamable-http）、API Key 双存储（hash + encrypted） | castle |

## 测试

```bash
# 后端（1554 用例，--ignore=tests/performance 口径）
python -m pytest tests/ --ignore=tests/performance --cov=platform_mcp
mypy platform_mcp/    # 类型检查（V1.0 新增，108 files 0 errors）

# 前端（174 用例）
cd platform-mcp-frontend
npx vitest run
```

## 配置

| 文件 | 用途 | 来源 |
|---|---|---|
| `settings.yml` | 基础配置（database.url 等，必填） | 从 `settings.yml.example` 复制 |
| `settings-dev.yml` | dev 环境覆盖（已含） | 已追踪，按需修改 `oracle_instant_client_dir` |
| `settings-prod.yml` | prod 环境覆盖 | 从 `settings-prod.yml.example` 复制（仅 prod 需要） |
| `crypto-secret.key` | AES 密钥（32 raw bytes） | `scripts/_setup_local.py` 自动生成 |
| `alembic.ini` | Alembic migration 配置 | 已追踪；DB URL 占位，可用 `PLATFORM_DB_URL` 环境变量覆盖 |

## 许可

本项目基于 **MIT License** 开源，详见 [LICENSE](LICENSE)。

### 第三方依赖开源许可

本项目使用以下开源组件，各组件遵循其原始许可协议：

| 类别 | 组件 | 许可协议 |
|---|---|---|
| 后端框架 | FastAPI、Pydantic、SQLAlchemy、Alembic、Gunicorn、loguru | MIT |
| ASGI 服务器 | Uvicorn | BSD-3-Clause |
| SSH/SFTP | asyncssh | EPL-2.0 |
| 数据库驱动 | oracledb | Apache 2.0 |
|  | aiomysql | MIT |
|  | psycopg2-binary | LGPL-3.0 |
| 加密 | cryptography | Apache-2.0 OR BSD-3-Clause |
| HTTP 客户端 | httpx | BSD-3-Clause |
| MCP 协议 | mcp SDK | MIT |
| 配置 | PyYAML | MIT |
| 重试/容错 | tenacity | Apache-2.0 |
| SQL 解析 | sqlparse | BSD-3-Clause |
| 前端框架 | Vue、Vite、Pinia、Vue Router、Axios | MIT |
| 国际化 | vue-i18n | MIT |
| 类型系统 | TypeScript | Apache-2.0 |
| UI 组件库 | Element Plus | MIT |

### 商业数据库许可说明

Platform-MCP 支持连接 Oracle 11g 与 MySQL 5.6 作为**目标数据库**，使用方需自行获取相应数据库的合法授权与许可，本项目不包含也不提供任何商业数据库的许可。Oracle 驱动（oracledb）的 thick 模式依赖 Oracle Instant Client，需另行下载并遵守 Oracle 的许可协议。
