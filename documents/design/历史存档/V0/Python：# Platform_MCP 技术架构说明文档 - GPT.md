# Platform_MCP 技术架构说明文档 - GPT2

- **适用对象**：架构师、后端开发、前端开发、运维工程师、测试工程师  
- **文档用途**：用于项目启动阶段的 IT 内部宣讲、技术评审、系统设计与实施基线对齐  

---

## 版本更新日志

| 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
|---|---|---|---|---|
| V1.0 | 2025-08-08 00:00:00 | 新建 | 初版技术架构说明文档，基于 Python 技术路线，补充详细技术栈、模块设计、接口边界、部署方案、运维要求、测试基线与实施约束，明确 Python 3.11.9 为基础运行版本 | castle.zhang |

---

# 1. 文档概述

## 1.1 编写背景
Platform_MCP 项目面向内部场景建设统一的 MCP 能力平台。项目首期目标是落地数据库相关 Skill，通过标准 MCP 接口承接 Claude Code 等调用方的数据库执行请求，同时建设配套的管理界面、权限控制、状态查看和审计能力。

本文件在《Platform_MCP 架构说明（正式版）》基础上，进一步下沉到技术实现层，作为项目启动阶段的统一技术基线。

---

## 1.2 文档目标
本文档用于统一以下内容：

- 统一整体技术方向
- 统一后端、前端、数据库和部署实施基线
- 统一 MCP 扩展方式
- 统一模块职责与边界
- 统一接口、日志、权限、审计、安全和兼容性原则
- 统一开发、测试、部署和运维协作方式

---

## 1.3 适用范围
本文档适用于以下角色：

- 架构师：用于架构评审和演进设计
- 后端开发：用于服务实现和模块边界约束
- 前端开发：用于页面范围和接口对接
- 运维工程师：用于部署、配置、监控和运行维护
- 测试工程师：用于测试范围界定和测试用例设计

---

# 2. 系统建设目标

## 2.1 总体目标
建设一套内部统一的 MCP 服务平台，满足以下要求：

- 提供 Claude Code 可调用的 MCP 服务入口
- 首期支持数据库 Skill
- 支持执行本地 `.sql` 文件内容和 SQL 文本
- 提供统一权限管理、数据源管理和审计能力
- 支持 Oracle 11g、MySQL 5.6 等存量数据库接入
- 提供密码加解密管理界面
- 提供 MCP 调用状态查看页面
- 保留后续扩展其他 Skill 的能力

---

## 2.2 核心建设原则
- **稳定优先**：优先选择成熟、长期维护稳定的技术组件
- **兼容优先**：兼容老数据库、老驱动和传统部署方式
- **简单优先**：不引入 Docker、K8s、微服务等当前阶段不必要复杂度
- **扩展优先**：MCP 层按 Skill 插件式能力扩展设计
- **审计优先**：所有关键调用、配置变更、安全操作可追溯

---

# 3. 系统定位与边界

## 3.1 系统定位
Platform_MCP 是一个：

- MCP 统一能力服务
- 首期聚焦数据库 Skill 的执行服务
- 带 Web 管理台的内部管理平台
- 可扩展其他 Skill 的技术底座

---

## 3.2 非目标说明
以下内容不作为首期建设重点：

- Web 在线 SQL 富编辑器
- 工作流审批引擎
- 微服务拆分
- Docker/K8s 云原生部署
- 多机房高可用架构
- 大规模分布式任务调度平台

---

# 4. 总体架构设计

## 4.1 总体架构结论
系统采用：

- **Python 单体模块化架构**
- **Web 管理端 + MCP Server + Skill 层 + PostgreSQL 系统库**
- **Python 数据库驱动连接目标数据库**
- **虚拟环境部署 + systemd + Nginx**

---

## 4.2 总体逻辑架构

### 4.2.1 调用侧
- Claude Code
- Web 管理用户
- 运维管理员

### 4.2.2 接入侧
- MCP Tool 接口
- Web REST API

### 4.2.3 业务服务侧
- 权限认证
- MCP 请求分发
- Skill 注册与执行
- 数据源管理
- 密码加解密
- SQL 执行
- 风险识别
- 审计日志
- 状态监控

### 4.2.4 数据侧
- PostgreSQL 系统库
- Oracle 11g
- MySQL 5.6

---

## 4.3 典型调用链

### 4.3.1 Claude Code 执行 SQL 文件
1. Claude Code 调用 MCP Tool
2. MCP Server 接收请求
3. 路由到 `database skill`
4. 读取本地 `.sql` 文件内容
5. 执行 SQL 风险识别
6. 根据数据源配置建立数据库连接
7. 执行 SQL
8. 返回执行结果
9. 写入 MCP 调用日志和审计日志

---

### 4.3.2 管理员配置数据源密码
1. 管理员进入 Web 密码加解密页
2. 输入明文密码
3. 后端执行加密
4. 返回密文
5. 保存到数据源配置
6. 写入加密操作审计日志

---

# 5. 技术选型基线

## 5.1 选型原则
技术栈版本遵循以下原则：

- 选择当前仍活跃维护、社区稳定、长期可用的版本
- 在兼容 Oracle 11g、MySQL 5.6 的前提下，优先选择成熟稳定版本
- 避免使用过于激进的新特性
- 明确锁定主版本与推荐小版本，便于统一开发和部署环境

---

## 5.2 后端技术栈

| 组件 | 推荐版本 | 说明 |
|---|---|---|
| Python | 3.11.9 | 正式基础运行版本，稳定、成熟，适合作为项目统一解释器版本 |
| FastAPI | 0.115.0 | Web API 与管理接口框架，性能高、文档友好 |
| Uvicorn | 0.30.6 | ASGI Server，适合开发、测试与轻量运行 |
| Gunicorn | 23.0.0 | 生产环境进程管理，建议结合 Uvicorn Worker 使用 |
| Pydantic | 2.8.2 | 数据校验与配置建模 |
| pydantic-settings | 2.4.0 | 配置管理 |
| SQLAlchemy | 2.0.35 | PostgreSQL 系统库 ORM 与数据库访问 |
| Alembic | 1.13.2 | 数据库版本迁移工具 |
| psycopg | 3.2.1 | PostgreSQL 驱动，建议系统库优先使用 |
| oracledb | 2.4.1 | Oracle 驱动，需重点验证 Oracle 11g 兼容性 |
| PyMySQL | 1.1.1 | MySQL 驱动，适合管理与轻量访问 |
| mysqlclient | 2.2.4 | MySQL C 驱动，可作为高兼容备选 |
| cryptography | 43.0.1 | AES 加解密实现 |
| passlib | 1.7.4 | 用户密码摘要处理 |
| PyJWT | 2.9.0 | 如采用 JWT 方案时使用 |
| loguru | 0.7.2 | 日志增强，可选 |
| structlog | 24.4.0 | 结构化日志，可选 |
| python-multipart | 0.0.9 | 表单与上传支持 |
| httpx | 0.27.2 | HTTP 客户端 |
| tenacity | 9.0.0 | 重试控制 |
| orjson | 3.10.7 | 高性能 JSON，可选 |
| PyYAML | 6.0.2 | YAML 配置处理 |
| uv | 0.4.13 | Python 依赖与虚拟环境管理工具，可选优先 |
| pip | 24.2 | 标准包管理工具 |

---

## 5.3 前端技术栈

| 组件 | 推荐版本 | 说明 |
|---|---|---|
| Node.js | 20.15.1 LTS | 前端构建运行环境 |
| npm | 10.7.0 | 包管理工具 |
| Vue | 3.4.38 | 稳定主流版本 |
| Vite | 5.4.2 | 构建工具 |
| TypeScript | 5.5.4 | 类型约束 |
| Vue Router | 4.4.3 | 路由管理 |
| Pinia | 2.2.2 | 状态管理 |
| Element Plus | 2.8.1 | UI 组件库 |
| Axios | 1.7.4 | HTTP 请求 |
| ECharts | 5.5.1 | 状态监控图表，可选 |
| ESLint | 9.9.1 | 代码规范 |
| Prettier | 3.3.3 | 代码格式化 |

---

## 5.4 数据库与中间件

| 组件 | 推荐版本 | 说明 |
|---|---|---|
| PostgreSQL | 16.4 | 系统库，稳定且适合管理类数据 |
| Nginx | 1.26.1 | 静态资源与反向代理 |
| systemd | OS 自带稳定版本 | 服务托管 |
| Linux OS | Rocky Linux 9.4 / RHEL 9.x / CentOS Stream 9 | 推荐服务器环境 |

---

## 5.5 测试与质量工具

| 组件 | 推荐版本 | 说明 |
|---|---|---|
| pytest | 8.3.2 | Python 单元与集成测试主框架 |
| pytest-asyncio | 0.23.8 | 异步测试支持 |
| pytest-cov | 5.0.0 | 覆盖率统计 |
| httpx | 0.27.2 | API 测试客户端 |
| Faker | 28.4.1 | 测试数据构造 |
| Postman | 11.x | 接口测试 |
| Apache JMeter | 5.6.3 | 压测工具 |
| SonarQube | 10.6 | 代码质量检查，可选 |
| Ruff | 0.6.3 | Python 代码规范与静态检查 |
| Black | 24.8.0 | 代码格式化 |
| isort | 5.13.2 | import 排序 |

---

# 6. 版本兼容性特别说明

## 6.1 Python 版本建议
项目统一基线明确为：

- **Python 3.11.9**

建议原则：

- 开发、测试、生产统一使用 Python 3.11.9
- 不允许开发环境与生产环境混用 3.10 / 3.12，避免依赖差异
- CI/CD、虚拟环境、运维脚本全部以 3.11.9 为标准

---

## 6.2 Oracle 11g 驱动建议
建议专项验证以下内容：

- `oracledb 2.4.1` 在 thin 模式下对 Oracle 11g 的兼容情况
- 若 thin 模式存在限制，评估切换 thick 模式
- 验证内容包括：
  - 基本连接
  - SELECT 查询
  - DML 执行
  - 事务提交回滚
  - 存储过程调用
  - 游标返回
  - 中文字符集处理
  - 日期时间字段兼容

如兼容性不足，需在项目启动前固化 Oracle 访问替代策略或驱动封装策略。

---

## 6.3 MySQL 5.6 驱动建议
建议优先验证：

- `PyMySQL 1.1.1`
- `mysqlclient 2.2.4`

建议优先顺序：

1. 优先使用 `PyMySQL 1.1.1`，部署简单、纯 Python 实现
2. 若性能或兼容性存在问题，使用 `mysqlclient 2.2.4`

需重点验证：

- 认证协议兼容
- 时区参数
- 字符集处理
- 多语句执行支持
- 事务行为一致性

---

# 7. 模块化架构设计

## 7.1 模块清单
建议工程按以下逻辑模块组织：

- `app/api`
- `app/auth`
- `app/datasource`
- `app/crypto`
- `app/mcp_core`
- `app/skill_api`
- `app/skill_registry`
- `app/skills/database`
- `app/sql_executor`
- `app/risk_engine`
- `app/audit`
- `app/monitor`
- `app/common`

---

## 7.2 模块职责

### 7.2.1 app/api
负责：
- Web REST API
- 前端对接接口
- 页面数据聚合输出

---

### 7.2.2 app/auth
负责：
- 登录认证
- 用户、角色、权限管理
- 资源访问鉴权

---

### 7.2.3 app/datasource
负责：
- 数据源信息管理
- 环境管理
- 连接参数管理
- 数据源权限控制

---

### 7.2.4 app/crypto
负责：
- 密码加密与解密
- 密钥读取
- 密码操作审计

---

### 7.2.5 app/mcp_core
负责：
- MCP 请求接收
- Tool 参数解析
- 调用链路上下文封装
- 统一响应结构

---

### 7.2.6 app/skill_api
负责：
- Skill 接口标准
- Tool 输入输出模型
- 扩展规范定义

---

### 7.2.7 app/skill_registry
负责：
- Skill 注册发现
- Tool 与 Skill 映射
- Skill 执行入口管理

---

### 7.2.8 app/skills/database
负责：
- 数据库 Skill 业务逻辑
- Tool 能力落地
- SQL 文件/文本执行组织

---

### 7.2.9 app/sql_executor
负责：
- SQL 执行
- 多语句分段
- 查询结果映射
- 存储过程调用

---

### 7.2.10 app/risk_engine
负责：
- SQL 风险识别
- 高危语句标记
- 语法解析失败记录

---

### 7.2.11 app/audit
负责：
- 审计日志记录
- MCP 调用日志
- 配置变更日志
- 安全操作日志

---

### 7.2.12 app/monitor
负责：
- MCP 调用状态输出
- 服务运行状态输出
- 概览统计数据输出

---

### 7.2.13 app/common
负责：
- 通用异常
- 通用响应模型
- 枚举
- 工具类
- 常量

---

# 8. MCP 能力架构

## 8.1 设计原则
MCP 层按“统一入口 + Skill 扩展”设计：

- MCP Server 负责接入
- Skill 负责能力实现
- Registry 负责路由
- Audit 负责全链路记录

---

## 8.2 首期 Skill 规划
首期仅建设：

- `database`

未来预留：
- `file`
- `log`
- `config`
- `deploy`
- `shell`

---

## 8.3 Tool 规划
建议首期 database skill 提供：

- `execute_sql_file`
- `execute_sql_text`
- `validate_sql`
- `list_datasources`
- `get_execution_status`

---

## 8.4 Skill 统一接口建议
每个 Skill 实现需统一具备：

- `skill_name()`
- `list_tools()`
- `validate(request)`
- `execute(request, context)`
- `support(tool_name)`

---

## 8.5 统一上下文信息
MCP 调用上下文建议统一封装：

- trace_id
- request_id
- operator
- skill_name
- tool_name
- target_datasource
- target_env
- request_time
- risk_level
- execution_status

---

# 9. 数据源与目标数据库设计

## 9.1 系统库与目标库分离原则
- PostgreSQL 用于系统管理数据
- Oracle/MySQL 用于业务执行目标库
- 系统库访问与目标库访问逻辑严格分离

---

## 9.2 数据源配置内容
每个数据源建议包括：

- 数据源编码
- 数据源名称
- 数据库类型
- 主机地址
- 端口
- 数据库实例名/服务名
- 用户名
- 密文密码
- 环境标识
- 是否启用
- 驱动类型
- 连接串
- 备注信息

---

## 9.3 连接管理策略
建议：

- 系统库使用 SQLAlchemy 管理连接池
- 目标库采用按请求动态创建连接方式
- 不长期持有所有目标数据库连接
- 降低老旧数据库连接稳定性风险
- 避免无效长连接积压

---

## 9.4 支持矩阵建议
首期明确支持：

| 能力 | Oracle 11g | MySQL 5.6 |
|---|---|---|
| SELECT 查询 | 支持 | 支持 |
| INSERT/UPDATE/DELETE | 支持 | 支持 |
| 多语句执行 | 需验证 | 支持 |
| 存储过程调用 | 支持 | 需验证 |
| 事务控制 | 支持 | 支持 |

---

# 10. SQL 执行设计

## 10.1 执行方式
系统支持两类执行方式：

- SQL 文件执行
- SQL 文本执行

---

## 10.2 文件执行说明
SQL 文件执行流程：

1. 接收文件路径
2. 读取本地 `.sql` 文件
3. 进行编码校验
4. 执行语句拆分
5. 风险识别
6. 建立数据库连接
7. 执行语句
8. 汇总结果返回

---

## 10.3 多语句处理建议
建议：
- 第一版采用简单稳定策略
- 按分号拆分时需处理注释、字符串常量、PL/SQL 块等特殊情况
- Oracle 存储过程脚本建议单独走专门解析策略

---

## 10.4 返回结果建议
统一返回：

- 是否成功
- 影响行数
- 结果集摘要
- 错误信息
- 执行耗时
- 风险等级
- 审计编号

---

# 11. 风险识别设计

## 11.1 风险识别目标
对 SQL 在执行前做基础风险识别，降低误操作风险。

---

## 11.2 建议识别内容
- 语句类型识别
- 是否为 DDL
- 是否为 DML
- 是否缺少 WHERE
- 是否为全表更新/删除风险
- 是否包含 DROP/TRUNCATE 等高危操作
- 是否解析失败

---

## 11.3 风险等级建议
- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

---

# 12. 安全设计

## 12.1 认证方案
Web 端建议采用：

- 用户名密码登录
- Session 或 JWT 二选一

首期更建议：
- **Session 方案**

原因：
- 内部系统简单稳定
- 后台管理场景更易控制
- 更适合权限收敛和会话失效管理

---

## 12.2 权限模型
建议权限控制维度包括：

- 用户
- 角色
- Skill
- Tool
- 环境
- 数据源
- 管理页面功能点

---

## 12.3 密码加解密方案
建议：
- AES-256
- GCM 优先，CBC 作为兼容备选
- 随机 IV / nonce
- Base64 输出

密钥：
- 存在独立 secret 文件
- 严禁入库明文保存
- 严禁写死代码

---

## 12.4 审计要求
以下操作必须审计：

- 登录登出
- MCP Tool 调用
- SQL 执行
- 数据源新增修改删除
- 权限变更
- 密码加密
- 密码解密
- 系统参数修改

---

# 13. Web 前端设计基线

## 13.1 页面范围
建议首期页面如下：

1. 登录页  
2. 首页 / 系统概览页  
3. 数据源管理页  
4. 密码加解密页  
5. 用户管理页  
6. 角色权限管理页  
7. 审计日志页  
8. MCP 调用状态页  
9. 系统配置页  

---

## 13.2 前端职责边界
前端只负责：

- 页面交互
- 表单校验
- 数据展示
- 调用后端接口

前端不负责：

- SQL 真正执行
- 数据库密码真实加解密
- 风险识别逻辑
- 权限判定最终决策

---

## 13.3 状态页设计要求
MCP 状态页按 skill/tool 维度展示：

- 调用时间
- 调用人
- skill
- tool
- 数据源
- 环境
- 请求摘要
- 风险等级
- 状态
- 耗时
- 错误原因
- 审计编号

---

# 14. 系统库设计基线

## 14.1 建议核心表
- `sys_user`
- `sys_role`
- `sys_user_role`
- `sys_permission`
- `sys_role_permission`
- `sys_datasource`
- `sys_datasource_permission`
- `sys_audit_log`
- `sys_mcp_call_log`
- `sys_crypto_operation_log`
- `sys_system_config`

---

## 14.2 日志表设计建议
日志表建议具备以下字段：

- 主键 ID
- trace_id
- request_id
- operator
- skill_name
- tool_name
- datasource_code
- env_code
- request_summary
- result_status
- risk_level
- error_message
- start_time
- end_time
- duration_ms
- created_at

---

# 15. 接口设计基线

## 15.1 Web 管理接口
建议至少包括：

- 登录接口
- 用户管理接口
- 角色管理接口
- 数据源管理接口
- 密码加解密接口
- 审计日志查询接口
- MCP 状态查询接口
- 系统配置接口

---

## 15.2 MCP Tool 接口
建议包括：

- `execute_sql_file`
- `execute_sql_text`
- `validate_sql`
- `list_datasources`
- `get_execution_status`

---

## 15.3 返回结构统一原则
所有接口建议统一响应格式：

- code
- message
- data
- trace_id
- timestamp

---

# 16. 日志与监控设计

## 16.1 应用日志分类
建议区分：

- 应用运行日志
- 安全日志
- 审计日志
- SQL 执行日志
- MCP 调用日志
- 错误日志

---

## 16.2 日志输出建议
- 控制台输出用于开发环境
- 文件输出用于测试和生产环境
- 采用按天滚动
- 保留周期按运维规范设置
- 推荐 JSON 结构化输出，便于检索与审计

---

## 16.3 运行监控建议
首期可采用轻量监控：

- 应用存活检查
- Python 进程监控
- 内存使用监控
- CPU 使用监控
- 错误率监控
- MCP 调用量统计
- 执行耗时统计

---

# 17. 部署与运维基线

## 17.1 部署形态
不采用 Docker，采用传统部署：

- Python 虚拟环境部署
- Gunicorn + Uvicorn Worker 运行后端
- 前端静态资源部署
- PostgreSQL 独立部署
- Nginx 反向代理
- systemd 托管

---

## 17.2 目录结构建议
建议服务器目录：

- `/opt/Platform-MCP/app/`
- `/opt/Platform-MCP/venv/`
- `/opt/Platform-MCP/config/`
- `/opt/Platform-MCP/secret/`
- `/opt/Platform-MCP/logs/`
- `/opt/Platform-MCP/scripts/`

---

## 17.3 配置文件建议
配置文件建议分离：

- `settings.yml`
- `settings-dev.yml`
- `settings-test.yml`
- `settings-prod.yml`
- `datasource-template.yml`
- `crypto-secret.key`

---

## 17.4 systemd 服务建议
服务名建议：

- `Platform-MCP.service`

启动命令建议采用：

- `gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080`

---

## 17.5 Nginx 建议职责
- 托管前端静态资源
- 反向代理后端接口
- 路由转发
- 访问日志记录

---

# 18. 测试基线

## 18.1 测试范围
测试需覆盖：

- Web 页面功能
- 后端接口
- MCP Tool 调用
- 数据源管理
- 密码加解密
- 审计日志
- 状态页展示
- Oracle/MySQL 兼容验证

---

## 18.2 测试分类
- 单元测试
- 集成测试
- 接口测试
- 回归测试
- 兼容性测试
- 安全测试
- 压力测试

---

## 18.3 重点测试项
- Oracle 11g 连接与执行
- MySQL 5.6 连接与执行
- SQL 文件执行正确性
- 多语句处理正确性
- 风险识别准确性
- 密码解密权限控制
- MCP 调用日志完整性
- 权限隔离有效性

---

# 19. 非功能性要求

## 19.1 可用性
- 服务支持稳定持续运行
- 异常请求不影响整体服务可用性

---

## 19.2 可维护性
- 模块职责清晰
- 日志可定位
- 配置可管理
- 错误信息可追踪

---

## 19.3 安全性
- 密码密文存储
- 解密操作受控
- 权限最小化
- 全链路审计

---

## 19.4 可扩展性
- MCP 统一入口不绑定单一数据库能力
- Skill 可逐步扩展
- 接口和日志结构可复用

---

# 20. 实施建议

## 20.1 实施优先级
建议分阶段推进：

### 第一阶段
- 项目框架搭建
- 用户认证
- 数据源管理
- 密码加密能力
- PostgreSQL 系统库初始化

### 第二阶段
- MCP Core
- Database Skill
- SQL 执行器
- 审计日志

### 第三阶段
- MCP 状态页
- 风险识别增强
- Oracle/MySQL 专项兼容联调
- 运维部署完善

---

## 20.2 启动前确认项
项目启动前需确认：

- Python 版本固定为 3.11.9
- Oracle 11g 驱动最终模式与版本
- MySQL 5.6 驱动版本
- SQL 文件路径读取策略
- Claude Code 与 MCP 对接方式
- 密钥文件存储规范
- 审计日志保留策略

---

# 21. 技术结论

## 21.1 正式技术路线
Platform_MCP 首期正式技术路线建议如下：

- **后端**：Python 3.11.9 + FastAPI 0.115.0  
- **运行**：Gunicorn 23.0.0 + Uvicorn 0.30.6  
- **前端**：Vue 3.4.38 + Vite 5.4.2 + Element Plus 2.8.1  
- **系统库**：PostgreSQL 16.4  
- **目标数据库连接**：Python 驱动（Oracle 11g / MySQL 5.6）  
- **部署方式**：虚拟环境 + systemd + Nginx  
- **扩展模式**：MCP 统一入口 + Skill 插件式扩展  

---
