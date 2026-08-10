# Platform-MCP 部署规范

> **文档名称**：Platform-MCP 部署规范
> **基于文档**：《Platform-MCP 技术架构说明文档》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | V1.0 | 2026-08-08 12:00:00 | 正式发布 | 一期 + Server Skill 二期专项全量上线 | castle |
>
> **适用范围**：Platform-MCP 一期生产环境部署（传统部署，不使用 Docker）

---

## 一、部署架构概述

### 1.1 一期服务清单

| 服务 | 技术栈 | 版本 | 端口 | 说明 |
|------|--------|------|------|------|
| Platform-MCP-web | FastAPI + Gunicorn + Uvicorn | Python 3.11.9 | 8080 | Web 管理端 |
| Platform-MCP-mcp | MCP Python SDK | Python 3.11.9 | stdio / 9000 (HTTP) | MCP Server，默认 stdio；生产建议 streamable-http（见 §2.4） |
| postgresql | PostgreSQL | 16.4 | 5432 | 系统数据库 |
| nginx | Nginx | 1.26.1 | 80 / 443 | 反向代理 + 静态资源 |

### 1.2 服务器规划

| 服务器 | 职责 | 服务 | 配置建议 | 操作系统 |
|--------|------|------|---------|---------|
| Server 1 | 全部服务 | Web + MCP + PostgreSQL + Nginx | 8C16G | Rocky Linux 9.4 |

### 1.3 网络拓扑

```
用户 ────────→ Server 1 (Nginx:80/443)
                 ├─ /           → 前端静态资源 (Vue 构建产物)
                 ├─ /api/v1/    → Platform-MCP-web:8080  (Web 管理端 API)
                 └─ /mcp        → Platform-MCP-mcp:9000  (MCP streamable-http，见 §2.4.2)

Claude Code ─┬─ stdio 模式（默认）→ Platform-MCP-mcp 子进程（同机）
             └─ HTTP 模式（生产推荐）→ Nginx /mcp → Platform-MCP-mcp:9000

Platform-MCP-mcp ─┬─→ PostgreSQL:5432  (系统库)
               ├─→ Oracle 11g       (目标库，远端)
               └─→ MySQL 5.6        (目标库，远端)
```

---

## 二、各服务部署详情

### 2.1 PostgreSQL 16.4

#### 安装与配置

```bash
dnf install -y postgresql16-server postgresql16
postgresql-16-setup initdb
systemctl enable --now postgresql-16
```

#### 数据库创建

```bash
sudo -u postgres psql
CREATE DATABASE platform_mcp ENCODING 'UTF8';
CREATE USER platform_mcp WITH PASSWORD '<password>';
GRANT ALL PRIVILEGES ON DATABASE platform_mcp TO platform_mcp;
```

#### 核心配置（postgresql.conf）

```ini
listen_addresses = '*'
max_connections = 200
shared_buffers = 4GB
effective_cache_size = 6GB
work_mem = 32MB
log_timezone = 'Asia/Shanghai'
timezone = 'Asia/Shanghai'
log_statement = 'ddl'
```

#### 访问控制（pg_hba.conf）

```ini
host    platform_mcp    platform_mcp    127.0.0.1/32    scram-sha-256
local   all          all      peer
```

### 2.2 Nginx 1.26.1

```nginx
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /opt/Platform-MCP/ssl/server.crt;
    ssl_certificate_key /opt/Platform-MCP/ssl/server.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        root /opt/Platform-MCP/ui/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/v1/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        client_max_body_size 10m;
    }

    # MCP streamable-http（生产部署时启用）
    location /mcp {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 86400s;
    }
}
```

### 2.3 Platform-MCP-web（FastAPI）

```ini
# /etc/systemd/system/Platform-MCP.service
[Unit]
Description=Platform-MCP Web Server
After=network.target postgresql-16.service

[Service]
Type=notify
User=platform_mcp
Group=platform_mcp
WorkingDirectory=/opt/Platform-MCP/app
Environment=PATH=/opt/Platform-MCP/venv/bin:/usr/bin
ExecStart=/opt/Platform-MCP/venv/bin/gunicorn \
    platform_mcp.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8080 \
    --workers 4 \
    --timeout 300
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2.4 Platform-MCP-mcp（MCP Server）

MCP Server 支持两种传输模式，由 `settings.yml` 的 `mcp.transport` 字段控制：

#### 2.4.1 stdio 模式（本地开发，默认）

MCP Server 由 Claude Code 以子进程启动，配置示例（写入 `~/.claude.json`）：

```json
{
  "mcpServers": {
    "Platform-MCP": {
      "command": "/opt/Platform-MCP/venv/bin/python",
      "args": ["-m", "platform_mcp.mcp_server"],
      "cwd": "/opt/Platform-MCP/app",
      "env": {
        "PKUMCP_ENV": "dev",
        "PLATFORM_MCP_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

#### 2.4.2 streamable-http 模式（生产部署，推荐）

MCP Server 作为独立 systemd 进程运行，监听 9000 端口；Claude Code 通过 URL 远程调用：

```ini
# /etc/systemd/system/Platform-MCP-mcp.service
[Unit]
Description=Platform-MCP MCP Server
After=network.target postgresql-16.service

[Service]
Type=simple
User=platform_mcp
Group=platform_mcp
WorkingDirectory=/opt/Platform-MCP/app
Environment=PATH=/opt/Platform-MCP/venv/bin:/usr/bin
Environment=PKUMCP_ENV=prod
ExecStart=/opt/Platform-MCP/venv/bin/python -m platform_mcp.mcp_server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Claude Code 远程调用配置（`settings-prod.yml` 中 `mcp.transport: streamable-http`，写入 `~/.claude.json`）：

```json
{
  "mcpServers": {
    "Platform-MCP": {
      "url": "http://<server-host>/mcp",
      "transport": "http",
      "headers": {
        "PLATFORM_MCP_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

> **API Key 说明**：每个用户在 Web 管理端"个人设置"页可查看/重置自己的 API Key。admin 创建用户时自动生成 Key。Key 格式为 `pmcp_` + 43 字符随机串，SHA-256 哈希存储。MCP Server 在每次请求时校验 Header 中的 Key，确定调用者身份和角色。

**部署后验证**：

MCP Server 启动后监听 `127.0.0.1:9000/mcp`（host/port/path 来自 `settings.mcp.http_*`）。无 API Key 的 POST 请求应返回 401：

```bash
curl -X POST http://127.0.0.1:9000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'

# 期望响应：HTTP 401，body {"error":"缺少 PLATFORM_MCP_API_KEY 请求头"}
```

> **实现细节**：FastMCP（mcp SDK ≥ 1.9.4）不支持 `add_middleware`，HTTP 模式启动序列为 `mcp.streamable_http_app()` → `app.add_middleware(_AuthMiddleware)` → `uvicorn.run(app, host, port)`。`_AuthMiddleware` 必须是**纯 ASGI 类**（不能用 `BaseHTTPMiddleware` 子类），否则 anyio TaskGroup 抛出的 `BaseExceptionGroup` 会导致 500——详见问题汇总明细 §2.13。

#### 2.4.3 选型对比

| 维度 | stdio 模式 | streamable-http 模式 |
|------|-----------|---------------------|
| 适用场景 | 本地开发、Claude Code 与 MCP 同机 | 远程服务器部署、多客户端共用 |
| 启动方 | Claude Code 拉起子进程 | systemd 独立常驻进程 |
| 跨网络调用 | 不支持 | 支持（通过 Nginx 反代） |
| 资源占用 | 按需启动 | 长期持有 Python 解释器（~80MB） |
| 配置项 | `command` + `args` + `cwd` + `env.PLATFORM_MCP_API_KEY` | `url` + `transport: http` + `headers.PLATFORM_MCP_API_KEY` |
| 身份认证 | 启动时读 env 校验一次，进程级绑定 | 每次请求校验 Header，按用户角色授权 |

### 2.5 Oracle Instant Client

> **架构说明**：Oracle 11g thick 模式技术原理参见 [技术架构说明文档](Python：# Platform-MCP 技术架构说明文档.md) §Oracle 驱动兼容性。本节仅给出操作命令。

```bash
mkdir -p /opt/oracle
cd /opt/oracle
unzip instantclient-basic-linux.x64-11.2.0.4.0.zip

# 环境变量
echo 'export LD_LIBRARY_PATH=/opt/oracle/instantclient_11_2:$LD_LIBRARY_PATH' \
  > /etc/profile.d/Platform-MCP.sh
```

---

## 三、目录结构

> **范围说明**：本章为 root 部署（§2 + §12）的理想目录结构。**用户态实际部署（§13）目录与此不同**，详见 §13.4 `/opt/<user>/mcp_app/{app,db}` 平铺结构。

```
/opt/Platform-MCP/
├── app/                    # Python 应用代码
│   └── platform_mcp/
├── venv/                   # Python 虚拟环境
├── config/                 # 配置文件
│   ├── settings.yml
│   ├── settings-dev.yml
│   └── settings-prod.yml
├── secret/                 # 密钥文件（权限 0600）
│   └── crypto-secret.key
├── logs/                   # 日志文件
├── scripts/                # 运维脚本
├── sql-scripts/            # SQL 脚本白名单目录
└── ui/dist/                # 前端构建产物
```

---

## 四、端口规划

| 服务 | 端口 | 协议 | 开放范围 |
|------|------|------|---------|
| Nginx | 80 / 443 | HTTP/HTTPS | 对外 |
| Platform-MCP-web | 8080 | HTTP | 仅本机 |
| PostgreSQL | 5432 | PostgreSQL | 仅本机 |

---

## 五、配置管理

### 5.1 配置文件清单

| 文件 | 用途 |
|------|------|
| `settings.yml` | 主配置 |
| `settings-dev.yml` | 开发环境（不提交 Git） |
| `settings-test.yml` | 测试环境 |
| `settings-prod.yml` | 生产环境 |
| `crypto-secret.key` | 加密密钥（权限 0600） |

### 5.2 敏感配置管理

| 规则 | 说明 |
|------|------|
| 密钥文件独立存放 | `secret/` 目录，权限 0600 |
| 配置文件不含实际密钥 | 仅指定密钥文件路径 |
| `.gitignore` 排除 | `secret/`、`settings-dev.yml`、`*.key` 不提交 |

### 5.3 加密密钥（crypto-secret.key）跨环境隔离原则

**核心原则：每个环境（dev / test / prod）必须使用独立生成的 crypto-secret.key，绝不跨环境共享或拷贝。**

| 项 | 规范 |
|---|---|
| 文件格式 | 32 raw bytes（**不带 base64 编码**），由 `os.urandom(32)` 或 `head -c 32 /dev/urandom` 生成 |
| 权限 | `0600`，属主为部署账号 |
| 用途 | AES-256-GCM 加密数据源密码、服务器密码/SSH 私钥、API Key（`key_encrypted` 列）|
| 隔离要求 | dev / test / prod 各自独立 key，**绝不复用**；`.gitignore` 通过 `*.key` 规则排除 |
| 验证方式 | `xxd crypto-secret.key \| head -1` 应见 16 字节十六进制；`wc -c crypto-secret.key` 应输出 `32` |

#### 跨环境迁移加密数据（如 dev → prod 同步数据源）

**禁止**直接复制 `pmcp_datasource.encrypted_password` 字段（密文用源 key 加密，目标 key 无法解密 → 数据库写入后调用时 100% 失败）。

正确流程（参考 `remote/import_poc_inline.py` / `remote/sync_remaining.py` 范本）：

```python
# 源环境（dev）：用源 key 解密
src_crypto = CryptoUtils(Path("/path/dev/crypto-secret.key").read_bytes())
plaintext = src_crypto.decrypt(src_encrypted_password)

# 目标环境（prod）：用目标 key 重新加密后写入
dst_crypto = CryptoUtils(Path("/path/prod/crypto-secret.key").read_bytes())
new_encrypted = dst_crypto.encrypt(plaintext)
# INSERT INTO pmcp_datasource (...) VALUES (..., new_encrypted, ...)
```

**禁止行为**：
- 禁止把 dev 的 `crypto-secret.key` 拷到 prod（一旦泄露，所有历史密文被破）
- 禁止跨环境传输明文密码（即使 SSH 加密通道也不行，应在源端解密 + 目标端重新加密）
- 禁止 base64 编码 key 文件（`CryptoUtils.__init__` 强制 `len(key) == 32` raw bytes）

#### 密钥泄露应急流程

1. 立即在 Web 端"数据源管理 / 服务器管理"对所有条目重新录入密码（触发 re-encrypt）
2. 重置所有 API Key（admin 在"用户管理"对每个用户点"重置 Key"）
3. 替换 `crypto-secret.key` 文件（`head -c 32 /dev/urandom > crypto-secret.key && chmod 600`）
4. 重启 web/mcp 服务使新 key 生效

---

## 六、数据备份策略

### 6.1 PostgreSQL 备份

| 项目 | 规范 |
|------|------|
| 备份方式 | `pg_dump` 全量备份 |
| 备份频率 | 每日凌晨 2:00 |
| 保留周期 | 最近 30 天 |
| 恢复验证 | 每月至少一次 |

```bash
# 备份
pg_dump -U platform_mcp -d platform_mcp -F c -f /data/backup/platform_mcp_$(date +%Y%m%d).dump

# 备份验证（确认文件非空且可解析）
pg_restore --list /data/backup/platform_mcp_$(date +%Y%m%d).dump > /dev/null 2>&1 && echo "OK" || echo "FAIL"

# 恢复
pg_restore -U platform_mcp -d platform_mcp /data/backup/platform_mcp_YYYYMMDD.dump

# 定时任务（crontab -e）
# 0 2 * * * pg_dump -U platform_mcp -d platform_mcp -F c -f /data/backup/platform_mcp_$(date +\%Y\%m\%d).dump && find /data/backup -name "platform_mcp_*.dump" -mtime +30 -delete
```

---

## 七、部署前检查清单

- [ ] 操作系统安装完毕（Rocky Linux 9.4）
- [ ] Python 3.11.9 安装验证
- [ ] PostgreSQL 16.4 安装并初始化
- [ ] Nginx 1.26.1 安装
- [ ] Oracle Instant Client 安装（如需 Oracle 目标库）
- [ ] 配置文件准备完毕
- [ ] Secret 文件配置到位（权限 0600）
- [ ] Alembic 迁移执行完毕
- [ ] 前端构建产物部署完毕

---

## 八、部署顺序

1. 操作系统准备（基础工具、防火墙、用户创建）
2. Python 3.11.9（安装 + 虚拟环境）
3. PostgreSQL 16.4（安装 + 数据库 + Alembic 迁移）
4. 应用部署（代码 + 依赖 + 配置文件 + secret 文件）
5. Nginx（反向代理 + 前端静态资源）
6. Oracle Instant Client（如需 Oracle 目标库）
7. systemd 服务注册 + 启动
8. 验证（健康检查 + 功能验证）

---

## 九、健康检查端点

| 服务 | 端点 | 预期响应 |
|------|------|---------|
| Platform-MCP-web | `GET /api/v1/health` | `{"status": "UP"}` |
| Platform-MCP-mcp (HTTP) | `POST /mcp/` 无 `PLATFORM_MCP_API_KEY` Header | HTTP 401 `{"error":"缺少 PLATFORM_MCP_API_KEY 请求头"}` |
| PostgreSQL | `SELECT 1` | 查询成功 |
| Nginx | `GET /` | HTTP 200 |

---

## 十、监控与运维

| 指标 | 告警阈值 |
|------|---------|
| CPU 使用率 | > 80% 持续 5 分钟 |
| 内存使用率 | > 85% |
| 磁盘使用率 | > 80% |
| PostgreSQL 连接数 | > 150 |
| Web 响应时间 P99 | > 3 秒 |

---

## 十一、版本升级与回滚

### 升级流程

1. 备份数据库
2. 停止服务：`systemctl stop Platform-MCP`
3. 更新代码
4. 执行迁移：`alembic upgrade head`
5. 启动服务：`systemctl start Platform-MCP`
6. 验证健康检查：`curl https://localhost/api/v1/health`
7. 冒烟测试：登录、数据源列表、执行一条简单 SQL

### 回滚流程

1. 停止服务：`systemctl stop Platform-MCP`
2. 回滚代码至上一版本
3. 回滚数据库：`alembic downgrade -1`（回退一个版本）
4. 如需全量恢复：`pg_restore -U platform_mcp -d platform_mcp /data/backup/platform_mcp_YYYYMMDD.dump`
5. 启动服务：`systemctl start Platform-MCP`
6. 验证健康检查

### 数据库变更原则

- DDL 变更**只增不减**
- 通过 Alembic 管理所有变更
- 不直接修改生产数据库

---

## 十二、离线部署（RHEL 7.9）

> **适用场景**：目标服务器无法访问公网（Internet）、内部 yum 仓库不含 Python 3.11 / PostgreSQL 16 等新版依赖。典型为客户内网环境、隔离区机房、受控生产网。
>
> **操作系统差异提示**：RHEL 7.9（Maipo）glibc 2.17，比 §1.2 默认的 Rocky Linux 9.4（glibc 2.34）老。这意味着：(1) 系统 yum 仓库的 Python 仅 2.7，必须源码编译 Python 3.11.9；(2) PostgreSQL 16 需从 PGDG 仓库下载 RPM 离线安装；(3) 部分 Python wheel（如 `cryptography`、`psycopg`）优先取 `manylinux2014` 预编译包，避免现场编译。

### 12.1 阶段一：外网跳板机准备（联网环境）

在外网可达的跳板机（如办公电脑、临时云主机）上完成全部依赖下载，打成 tarball 再拷入内网。

```bash
# 跳板机：CentOS 7 或 RHEL 7 同族环境最佳（保证 glibc 兼容）
mkdir -p ~/platform_mcp-offline/{rpms,wheels,src,oracle,nginx}

# (1) Python 3.11.9 源码
cd ~/platform_mcp-offline/src
wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz

# (2) 编译 Python 所需的 RHEL 7 开发工具 RPM（若跳板机本身已装可跳过）
yum install -y epel-release
yumdownloader --resolve --destdir ~/platform_mcp-offline/rpms \
    gcc make openssl-devel bzip2-devel libffi-devel zlib-devel \
    readline-devel sqlite-devel xz-devel tk-devel

# (3) PostgreSQL 16 RPM（RHEL 7 从 PGDG 仓库取）
cd ~/platform_mcp-offline/rpms
wget https://download.postgresql.org/pub/repos/yum/reporpms/EL-7-x86_64/pgdg-redhat-repo-latest.noarch.rpm
rpm2cpio pgdg-redhat-repo-latest.noarch.rpm | cpio -idmv   # 解出 repo 文件以备手工下载
# 实际取包（在跳板机装好 pgdg-redhat-repo 后）：
yumdownloader --resolve --destdir ~/platform_mcp-offline/rpms \
    postgresql16-server postgresql16-contrib postgresql16-libs

# (4) Nginx（取 EPEL 稳定版 1.20+，或 mainline 1.26）
yumdownloader --resolve --destdir ~/platform_mcp-offline/nginx nginx

# (5) Python 依赖 wheel（manylinux2014 兼容 glibc 2.17）
cd ~/platform_mcp-offline/wheels
# 用与目标机一致的 Python 版本下载 wheel，避免 ABI 不匹配
# 完整对齐 pyproject.toml 的 20 个依赖项（含 extras）
pip3.11 download -d . \
    "fastapi==0.115.0" "pydantic==2.8.2" "pydantic-settings==2.5.2" \
    "sqlalchemy[asyncio]==2.0.35" "asyncpg==0.30.0" "alembic==1.13.2" \
    "mcp==1.9.4" "oracledb==2.4.1" "aiomysql==0.2.0" \
    "cryptography==43.0.1" "passlib==1.7.4" "bcrypt==4.2.0" "python-multipart==0.0.9" \
    "loguru==0.7.2" "httpx==0.27.2" "tenacity==9.0.0" \
    "pyyaml==6.0.2" "uvicorn[standard]==0.30.6" "gunicorn==23.0.0" \
    "psycopg2-binary==2.9.9" "sqlparse==0.5.0" "asyncssh==2.17.0"

# 说明：
# - asyncpg 0.30.0 用于 FastAPI 异步 PostgreSQL 访问（核心 ORM 路径）
# - psycopg2-binary 2.9.9 用于 scripts/ 下同步脚本（如 _setup_local.py）
# - pydantic-settings 升至 2.5.2（mcp 1.9.4 强制依赖，2.4.0 pip 装不上）
# - bcrypt 4.2.0 必装：passlib 验证 $2b$ bcrypt 哈希必须依赖 bcrypt 包作为 backend；
#   早期说法"passlib 用 cryptography 后端不需 bcrypt"是错误的——cryptography 不实现 bcrypt 算法

# (6) Oracle Instant Client 11.2（Thick 模式必需）
cd ~/platform_mcp-offline/oracle
wget https://download.oracle.com/otn/linux/instantclient/11204/oracle-instantclient11.2-basic-11.2.0.4.0.x86_64.rpm
wget https://download.oracle.com/otn/linux/instantclient/11204/oracle-instantclient11.2-sqlplus-11.2.0.4.0.x86_64.rpm   # 可选，排查用

# (7) 打包
cd ~
tar -czf platform_mcp-offline-$(date +%Y%m%d).tar.gz platform_mcp-offline/
sha256sum platform_mcp-offline-$(date +%Y%m%d).tar.gz > platform_mcp-offline-$(date +%Y%m%d).tar.gz.sha256
```

**清单（核对项）**：

| 子目录 | 内容 | 说明 |
|--------|------|------|
| `src/Python-3.11.9.tgz` | Python 源码 | 内网编译安装 |
| `rpms/*.rpm` | 编译工具链 + PostgreSQL 16 | 离线 `yum localinstall` |
| `nginx/*.rpm` | Nginx | 离线安装 |
| `wheels/*.whl` | Python 依赖 | `pip install --no-index` |
| `oracle/*.rpm` | Oracle Instant Client 11.2 | Thick 模式必需 |

### 12.2 阶段二：内网传输与校验

```bash
# 用 scp / U 盘 / 运维平台将 tarball 拷入目标服务器 /tmp
scp platform_mcp-offline-YYYYMMDD.tar.gz root@<target>:/tmp/

# 目标机校验完整性
cd /tmp && sha256sum -c platform_mcp-offline-YYYYMMDD.tar.gz.sha256
tar -xzf platform_mcp-offline-YYYYMMDD.tar.gz -C /opt/
ls /opt/platform_mcp-offline/   # 应看到 rpms/ wheels/ src/ oracle/ nginx/
```

### 12.3 阶段三：系统准备

```bash
# (1) 创建服务用户
groupadd -r platform_mcp
useradd -r -g platform_mcp -d /opt/Platform-MCP -s /sbin/nologin platform_mcp

# (2) 创建目录
mkdir -p /opt/Platform-MCP/{app,venv,config,secret,logs,scripts,sql-scripts,ui/dist}
mkdir -p /data/backup
chown -R platform_mcp:platform_mcp /opt/Platform-MCP

# (3) 防火墙（仅开 443，内网管理端口按需）
firewall-cmd --permanent --add-service=https
firewall-cmd --permanent --add-port=9000/tcp   # 可选：MCP HTTP 直接访问（仅内网调试）
firewall-cmd --reload

# (4) SELinux（建议保持 enforcing，按需放宽 audit 日志目录）
setsebool -P httpd_can_network_connect 1   # 允许 Nginx 反代到后端
```

### 12.4 阶段四：安装编译工具链 + 源码编译 Python 3.11.9

```bash
# (1) 离线安装编译依赖
cd /opt/platform_mcp-offline/rpms
yum localinstall -y *.rpm

# (2) 编译 Python（RHEL 7 默认 glibc 2.17 足够，但需 openssl 1.1.1+ 才能编出 ssl 模块）
#     若 RHEL 7 自带 openssl 为 1.0.2，需先离线升级到 openssl11（EPEL 提供）
yum localinstall -y openssl11-libs   # 如已在 rpms/ 目录则上一条已装

cd /opt/platform_mcp-offline/src
tar -xzf Python-3.11.9.tgz && cd Python-3.11.9
./configure \
    --prefix=/usr/local/python3.11 \
    --enable-optimizations \
    --enable-shared \
    LDFLAGS="-Wl,-rpath /usr/local/python3.11/lib"
make -j$(nproc) && make altinstall

# (3) 建立软链 + 验证
ln -sf /usr/local/python3.11/bin/python3.11 /usr/local/bin/python3.11
ln -sf /usr/local/python3.11/bin/pip3.11    /usr/local/bin/pip3.11
python3.11 --version    # Python 3.11.9
python3.11 -c "import ssl; print(ssl.OPENSSL_VERSION)"   # 确认 SSL 模块可用
```

### 12.5 阶段五：PostgreSQL 16 离线安装

```bash
cd /opt/platform_mcp-offline/rpms
yum localinstall -y postgresql16-server-*.rpm postgresql16-*.rpm

# 初始化 + 启动
/usr/pgsql-16/bin/postgresql-16-setup initdb
systemctl enable --now postgresql-16

# 建库建用户（同 §2.1）
sudo -u postgres /usr/pgsql-16/bin/psql <<'SQL'
CREATE DATABASE platform_mcp ENCODING 'UTF8';
CREATE USER platform_mcp WITH PASSWORD '<password>';
GRANT ALL PRIVILEGES ON DATABASE platform_mcp TO platform_mcp;
SQL
```

`postgresql.conf` 与 `pg_hba.conf` 配置参见 §2.1。**RHEL 7 注意**：配置文件路径为 `/var/lib/pgsql/16/data/`，与 Rocky 9 一致。

### 12.6 阶段六：应用部署（venv + wheel 离线安装）

```bash
# (1) 创建虚拟环境
/usr/local/bin/python3.11 -m venv /opt/Platform-MCP/venv
chown -R platform_mcp:platform_mcp /opt/Platform-MCP/venv

# (2) 拷贝应用代码（从 GitLab 归档 tar 或 CI 产物）
tar -xzf Platform-MCP-app-<commit>.tar.gz -C /opt/Platform-MCP/app/

# (3) 离线安装 Python 依赖
/opt/Platform-MCP/venv/bin/pip install --no-index --find-links=/opt/platform_mcp-offline/wheels/ \
    /opt/Platform-MCP/app/

# (4) 配置文件 + 密钥
cp /opt/Platform-MCP/app/config/settings.yml.example        /opt/Platform-MCP/config/settings.yml
cp /opt/Platform-MCP/app/config/settings-prod.yml.example    /opt/Platform-MCP/config/settings-prod.yml

# 密钥文件（32 raw bytes，权限 0600，owner platform_mcp）— 严禁 base64 编码
head -c 32 /dev/urandom > /opt/Platform-MCP/secret/crypto-secret.key
chmod 0600 /opt/Platform-MCP/secret/crypto-secret.key
chown platform_mcp:platform_mcp /opt/Platform-MCP/secret/crypto-secret.key

# (5) Alembic 迁移
cd /opt/Platform-MCP/app
sudo -u platform_mcp PKUMCP_ENV=prod /opt/Platform-MCP/venv/bin/python -m alembic upgrade head

# (6) 前端构建产物（在外网跳板机 npm build 后，将 dist/ 拷入）
tar -xzf Platform-MCP-ui-dist-<commit>.tar.gz -C /opt/Platform-MCP/ui/
```

### 12.7 阶段七：Oracle Instant Client 11.2

```bash
cd /opt/platform_mcp-offline/oracle
yum localinstall -y oracle-instantclient11.2-basic-*.rpm

# RHEL 7 安装后通常自动创建 /etc/ld.so.conf.d/oracle-instantclient.conf
ldconfig
echo 'export LD_LIBRARY_PATH=/usr/lib/oracle/11.2/client64/lib:$LD_LIBRARY_PATH' \
  > /etc/profile.d/Platform-MCP.sh

# 验证
source /etc/profile.d/Platform-MCP.sh
/opt/Platform-MCP/venv/bin/python -c "import oracledb; oracledb.init_oracle_client(lib_dir='/usr/lib/oracle/11.2/client64/lib'); print('ok')"
```

### 12.8 阶段八：systemd 服务 + Nginx

systemd 单元文件直接套用 §2.3（web）与 §2.4.2（mcp streamable-http）。Nginx 配置套用 §2.2，**RHEL 7 注意 SSE 流式要求**：

```bash
cd /opt/platform_mcp-offline/nginx
yum localinstall -y nginx-*.rpm
systemctl enable nginx

# RHEL 7 的 Nginx 配置路径：/etc/nginx/conf.d/Platform-MCP.conf
# 关键：proxy_buffering off（SSE 必需），proxy_read_timeout 拉长
```

### 12.9 阶段九：端口检查与启动顺序

**端口检查清单（启动前 / 启动后各执行一次）**：

```bash
# 启动前 — 确认目标端口未被占用
ss -lntp | grep -E ':(80|443|8080|9000|5432)\s'

# 启动顺序
systemctl start postgresql-16
systemctl start Platform-MCP          # Web:8080
systemctl start Platform-MCP-mcp      # MCP:9000
systemctl start nginx              # 80/443

# 启动后 — 确认监听
ss -lntp | grep -E ':(80|443|8080|9000|5432)\s'
```

| 端口 | 服务 | 监听地址 | 期望状态 |
|------|------|---------|---------|
| 5432 | PostgreSQL | 127.0.0.1 | LISTEN |
| 8080 | Platform-MCP-web | 127.0.0.1 | LISTEN |
| 9000 | Platform-MCP-mcp | 127.0.0.1 | LISTEN |
| 80   | Nginx HTTP | 0.0.0.0 | LISTEN（301 跳 443） |
| 443  | Nginx HTTPS | 0.0.0.0 | LISTEN |

### 12.10 阶段十：冒烟验证

```bash
# (1) Web 健康
curl -k https://localhost/api/v1/health
# 期望 {"status":"UP"}

# (2) MCP 鉴权（无 Key 应返回 401）
curl -X POST http://127.0.0.1:9000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
# 期望 HTTP 401

# (3) 数据库连通（系统库）
sudo -u postgres /usr/pgsql-16/bin/psql -d platform_mcp -c "SELECT count(*) FROM pmcp_user;"

# (4) Oracle Thick 验证（需 admin 在 Web 端配置好数据源后，从 MCP 调 list_datasources + execute_sql_text）

# (5) 前端首页
curl -k https://localhost/ | head -n 5
```

### 12.11 常见坑（RHEL 7.9 专属）

| 现象 | 根因 | 解决 |
|------|------|------|
| `pip install` 报 `error: command 'gcc' failed` | 编译工具链未装或 wheel 不带 `manylinux` 标签 | 确认 §12.4 编译依赖全装；重新在跳板机用 Python 3.11.9 取 wheel |
| `import ssl` 报 `ModuleNotFoundError` | Python 编译时缺 openssl-devel | RHEL 7 需装 `openssl11-libs`（EPEL）再重新 `./configure && make altinstall` |
| Oracle 连接 `DPY-3010: ... thick mode required` | Instant Client 未 `init_oracle_client` | 启动前 `source /etc/profile.d/Platform-MCP.sh`；systemd 单元文件需加 `Environment=LD_LIBRARY_PATH=/usr/lib/oracle/11.2/client64/lib` |
| Nginx 反代 MCP 后 Claude Code 请求卡住不响应 | 默认 `proxy_buffering on` 导致 SSE 缓冲 | Nginx `/mcp` location 内显式 `proxy_buffering off;`（已在 §2.2 配置） |
| Gunicorn worker 崩溃，日志报 `glibc detected ... double free` | glibc 2.17 在高并发 asyncpg 下偶发；或 wheel 为 manylinux_2_17 以上但 ABI 不匹配 | 降并发 `--workers 2`；或重取 wheel 时显式 `--platform manylinux2014_x86_64 --python-version 3.11 --only-binary=:all:` |
| `systemctl start Platform-MCP` 失败，`Type=notify` 超时 | RHEL 7 systemd 版本旧，`Type=notify` 需要 `sd_notify` 支持 | 改 `Type=simple` + `ExecStart` 直接拉 gunicorn（去掉 `--workers 4` 或保留均可，UvicornWorker 自带协程） |

### 12.12 离线更新流程

```bash
# (1) 外网跳板机：取新版本 app tarball + 新增 wheel（若有新增依赖）
# (2) 内网目标机
systemctl stop Platform-MCP Platform-MCP-mcp
mv /opt/Platform-MCP/app /opt/Platform-MCP/app.bak.$(date +%Y%m%d)
tar -xzf Platform-MCP-app-<new-commit>.tar.gz -C /opt/Platform-MCP/app/
/opt/Platform-MCP/venv/bin/pip install --no-index --find-links=/opt/platform_mcp-offline/wheels/ \
    /opt/Platform-MCP/app/ --upgrade
sudo -u platform_mcp PKUMCP_ENV=prod /opt/Platform-MCP/venv/bin/python -m alembic upgrade head
systemctl start Platform-MCP Platform-MCP-mcp

# (3) 回滚
systemctl stop Platform-MCP Platform-MCP-mcp
rm -rf /opt/Platform-MCP/app
mv /opt/Platform-MCP/app.bak.YYYYMMDD /opt/Platform-MCP/app
sudo -u platform_mcp PKUMCP_ENV=prod /opt/Platform-MCP/venv/bin/python -m alembic downgrade -1
systemctl start Platform-MCP Platform-MCP-mcp
```

---


## 十二·五、V1.0 类型检查与 DB 脚本工作流

> **章节编号说明**：本节为 §十二（root 离线部署）的增补内容，与 §十三（用户态部署）并列。为保留既有引用，沿用"十二·五"编号（中文数字化名），不再调整为 §十三。

### 12.5.1 mypy 类型检查（CI 必过项）

V1.0 引入 mypy==1.11.2 作为后端类型守门：

```bash
pip install mypy==1.11.2 types-PyYAML
mypy platform_mcp/
# 期望：Success: no issues found in 63 source files
```

pyproject.toml `[tool.mypy]` 配置详见《代码规范.md §十一》。

### 12.5.2 documents/db/ 发布脚本工作流

V1.0 重构数据库脚本结构：
- `alembic/versions/001_initial_tables.py`：单一发布修订（合并历史 10 个迭代）
- `documents/db/20260808120000_initial_schema.sql`：DDL 渲染产物
- `documents/db/20260808120001_seed_data.sql`：DML（admin/developer 角色 + admin 用户）
- `documents/db/历史存档/V0/`：发布前 15 个迭代归档

**Fresh-install 两种等价方式**：

```bash
# 方式 A（推荐）：alembic 驱动
createdb -U platform_mcp -d platform_mcp
PLATFORM_DB_URL='postgresql://platform_mcp@host:5432/platform_mcp' alembic upgrade head

# 方式 B：raw SQL（无 alembic 环境）
psql -U platform_mcp -d platform_mcp -f documents/db/20260808120000_initial_schema.sql
psql -U platform_mcp -d platform_mcp -f documents/db/20260808120001_seed_data.sql
```

**升级现有部署**（V0 → V1）：

```sql
UPDATE alembic_version SET version_num = '001' WHERE version_num = 'ch0101a947f6';
```

## 十三、无 root + 无外网部署（用户态 portable）

> **适用场景**：目标服务器为 RHEL/CentOS 7.x，**仅有普通用户账号（无 sudo / root）**，且**无外网**。本章为 §12 的用户态补充：所有操作在 `$HOME` 或运维分配的用户目录下完成，**不使用 systemd / yum / systemctl / groupadd**。
>
> **已验证环境**：RHEL Server 7.9 (Maipo) + glibc 2.17 + 8C7.6G + 普通账号 appuser，2026-08-07 实测通过。

### 13.1 与 §12（root 版）的核心差异

| 维度 | §12 root 版 | §13 用户态版（本章） |
|------|------------|---------------------|
| 服务账号 | `groupadd + useradd` 新建 | 用现有账号（运维分配） |
| Python 3.11 | 源码 `./configure && make altinstall`（依赖 gcc + openssl11-libs） | **`python-build-standalone` 预编译 tarball**（自带 libffi/zlib/bzip2，解压即用） |
| PostgreSQL 16 | `yum localinstall RPM` + `systemctl` | **EnterpriseDB binary tarball** 解压 + 用户态 `initdb` / `pg_ctl` |
| Oracle Instant Client | `yum localinstall RPM` + `ldconfig` | **zip 解压** + 启动脚本注入 `LD_LIBRARY_PATH` |
| 静态前端 | Nginx `root` 指令 | **FastAPI `StaticFiles` mount**（单端口 8080 对外，弃用 Nginx） |
| 进程管理 | systemd unit + `systemctl enable` | **`nohup` + 用户级 `crontab @reboot`** |
| HTTPS | Nginx TLS 终止 | 内网 HTTP 直连；如需 TLS 走 uvicorn `--ssl-*` 或运维层 LB |
| 端口 | 80/443（< 1024，需 root 或 setcap） | **8080（Web）+ 9000（MCP）**（> 1024，无需特权） |
| 部署根目录 | `/opt/Platform-MCP/`（root 创建后 chown） | 运维分配的用户目录，如 `/opt/<user>/mcp_app/` |

### 13.2 部署架构

```
用户浏览器 ────HTTP────▶ Server:8080  (FastAPI 单进程)
                          ├─ /            → StaticFiles (前端 dist)
                          ├─ /api/v1/*    → Web API 路由
                          └─ (无 Nginx)

Claude Code ───HTTP(header PLATFORM_MCP_API_KEY)──▶ Server:9000/mcp  (FastMCP streamable-http)

Server 进程：
  pg_ctl (portable PG 16, 127.0.0.1:5432)
    └─ platform_mcp_web (uvicorn, 0.0.0.0:8080)
    └─ platform_mcp_mcp (FastMCP,  0.0.0.0:9000)
       └─ → PostgreSQL 16 (本机)
       └─ → Oracle 11g / MySQL 5.6 (远端目标库)
```

### 13.3 已验证环境清单（部署前自检）

SSH 登录后执行以下命令采集，对照"期望值"列。**任何一项为 ✗ 都需先与运维沟通**。

| 检查命令 | 期望值 | 含义 |
|---------|-------|------|
| `cat /etc/redhat-release` | `Red Hat Enterprise Linux Server release 7.x` | glibc 2.17，兼容 manylinux2014 wheel |
| `ldd --version \| head -1` | `ldd (GNU libc) 2.17` 或更高 | wheel 兼容性 |
| `nproc && free -h` | ≥ 4 核 / ≥ 4G 可用 | 资源 |
| `df -h /opt/<user>` | ≥ 20G 可用 | 解压 + pgdata + 日志 |
| `openssl version` | ≥ 1.1.1（非系统默认 1.0.2k） | Python ssl 模块；缺失则用 standalone 自带 |
| `gcc --version` | ≥ 4.8.5 | 仅 fallback 编译时用 |
| `command -v tar xz curl` | 全部 FOUND | 解压与下载工具 |
| `ldconfig -p \| grep libaio` | 有输出 | Oracle Instant Client 依赖 |
| `ss -lnt \| grep -E ':8080\|:9000\|:5432'` | 无输出 | 端口空闲 |
| `crontab -l` | 不报 `command not found` | 用户级自启 |
| `sudo -n true` | 报错（无 sudo 权限） | 确认无 root，方案对齐 |
| `curl -m 5 https://example.com` | `000` 或超时 | 确认无外网 |

> **目标路径**：本章假设运维已分配 `/opt/<user>/mcp_app/{app,db}` 两个目录且属主为部署账号、mode 775。若未预创建，联系运维补建（**不要尝试 mkdir**，因为 `/opt/<user>` 通常父目录无写权限）。

### 13.4 目录布局

```
/opt/<user>/mcp_app/
├── app/                              # 应用层（运维预建，775）
│   ├── python/                       # python-build-standalone 解压（自带 stdlib + libffi）
│   ├── venv/                         # 应用虚拟环境
│   ├── platform_mcp/                    # 应用代码（pip install -e 或 tar 解压）
│   ├── config/
│   │   ├── settings.yml              # 主配置
│   │   └── settings-prod.yml         # 生产覆盖（PKUMCP_ENV=prod 加载）
│   ├── secret/crypto-secret.key      # AES 密钥（chmod 0600）
│   ├── ui/dist/                      # 前端构建产物
│   ├── oracle/instantclient_11_2/    # Oracle Instant Client zip 解压
│   ├── wheels/                       # 离线 wheel 缓存
│   ├── logs/                         # loguru 日志
│   └── run/                          # 启停脚本 + pid 文件
└── db/                               # 数据库层（运维预建，775）
    ├── pgsql/                        # PostgreSQL 16 binary tarball 解压
    └── pgdata/                       # initdb 初始化的数据目录
```

### 13.5 本地准备（外网跳板机）

> **跳板机选项**：Win11 + WSL2 Ubuntu，**或** Win11 + Docker Desktop（任一 Linux 容器即可）。本章命令在 Linux 环境下执行，下载产物放到 Win11 本地 `D:\IDEA\Platform-MCP\remote\` 子目录（对应容器内 `/mnt/d/IDEA/Platform-MCP/remote/`）。

#### 13.5.1 跳板机准备目录

```bash
# WSL2 或 Docker 容器内
mkdir -p /mnt/d/IDEA/Platform-MCP/remote/{python,pgsql,wheels,oracle,app,ui}
```

#### 13.5.2 下载 Python 3.11 预编译（python-build-standalone）

```bash
cd /mnt/d/IDEA/Platform-MCP/remote/python
# 选 install_only_stripped 变体（约 50MB，自带 libffi/zlib/bzip2/sqlite）
wget https://github.com/astral-sh/python-build-standalone/releases/download/20240814/cpython-3.11.9+20240814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
```

> **不可用时的 fallback**：源码编译。要求目标机有 openssl 1.1.1+ 头文件（如本案例 `/usr/local/openssl/include/openssl/ssl.h`），编译命令 `./configure --prefix=$HOME/python3.11 --with-openssl=/usr/local/openssl --enable-shared LDFLAGS="-Wl,-rpath $HOME/python3.11/lib" && make -j$(nproc) && make altinstall`。libffi-devel 等缺失会导致 `_ctypes` / `_sqlite3` 等模块不可用，但 fastapi/pydantic/sqlalchemy/asyncpg/cryptography/oracledb/aiomysql 核心 wheel 均不依赖这些模块。

#### 13.5.3 下载 PostgreSQL 16 portable tarball

```bash
cd /mnt/d/IDEA/Platform-MCP/remote/pgsql
wget https://get.enterprisedb.com/postgresql/postgresql-16.4-1-linux-x64-binaries.tar.xz
# 约 200MB，解压即用，无需 root
```

#### 13.5.4 下载 Oracle Instant Client 11.2 zip

```bash
cd /mnt/d/IDEA/Platform-MCP/remote/oracle
# Oracle 官网需登录接受协议，浏览器下载后放入此目录：
#   instantclient-basic-linux.x64-11.2.0.4.0.zip
#   instantclient-sqlplus-linux.x64-11.2.0.4.0.zip   (可选，排查用)
```

#### 13.5.5 离线 wheel 缓存

```bash
cd /mnt/d/IDEA/Platform-MCP/remote/wheels
# 用同版本 Python 3.11 下载（容器内临时装一份）
python3.11 -m venv /tmp/wb && source /tmp/wb/bin/activate
pip install --upgrade pip wheel
pip download -d . \
    "fastapi==0.115.0" "pydantic==2.8.2" "pydantic-settings==2.4.0" \
    "sqlalchemy[asyncio]==2.0.35" "asyncpg==0.30.0" "alembic==1.13.2" \
    "mcp==1.9.4" "oracledb==2.4.1" "aiomysql==0.2.0" \
    "cryptography==43.0.1" "passlib==1.7.4" "bcrypt==4.2.0" "python-multipart==0.0.9" \
    "loguru==0.7.2" "httpx==0.27.2" "tenacity==9.0.0" \
    "pyyaml==6.0.2" "uvicorn[standard]==0.30.6" "gunicorn==23.0.0" \
    "psycopg2-binary==2.9.9" "sqlparse==0.5.0" "asyncssh==2.17.0"
```

#### 13.5.6 应用代码 + 前端 + 配置模板（Win11 本地完成）

```powershell
cd D:\IDEA\Platform-MCP

# (1) 应用代码打包（含本次新加的 StaticFiles mount 改动，见 §13.7）
git archive --format=tar.gz -o remote\app\Platform-MCP-app.tar.gz HEAD

# (2) 前端构建
cd Platform-MCP-frontend
npm install
npm run build
tar -czf ..\remote\ui\dist.tar.gz -C dist .

# (3) 配置模板（settings-prod.yml 在服务器现场写，含密码不进 Git）
Copy-Item settings.yml remote\app\
```

#### 13.5.7 上传清单

| 本地路径 | 服务器路径 | 大小 |
|---|---|---|
| `remote/python/cpython-3.11.9*.tar.gz` | `/opt/<user>/mcp_app/app/` | ~50 MB |
| `remote/pgsql/postgresql-16.4-*.tar.xz` | `/opt/<user>/mcp_app/db/` | ~200 MB |
| `remote/oracle/instantclient-*.zip` | `/opt/<user>/mcp_app/app/oracle/` | ~70 MB |
| `remote/wheels/*.whl` | `/opt/<user>/mcp_app/app/wheels/` | ~150 MB |
| `remote/app/Platform-MCP-app.tar.gz` | `/opt/<user>/mcp_app/app/` | ~5 MB |
| `remote/app/settings.yml` | `/opt/<user>/mcp_app/app/config/` | <1 KB |
| `remote/ui/dist.tar.gz` | `/opt/<user>/mcp_app/app/ui/` | ~5 MB |

> **SFTP 工具**：WinSCP / FileZilla / `psftp.exe`（PuTTY 套件，命令行）。本章示例用 `psftp`。

### 13.6 服务器端部署（10 步，全部用户态）

> 设：`APP=/opt/<user>/mcp_app/app`，`DB=/opt/<user>/mcp_app/db`。所有命令以部署账号 SSH 登录后执行。

#### 步骤 1：解压 Python 3.11 + 创建 venv

```bash
cd $APP
tar -xzf cpython-3.11.9+20240814-*.tar.gz
# 得到 $APP/python/（内含 bin/python3.11）
$APP/python/bin/python3.11 --version    # Python 3.11.9
$APP/python/bin/python3.11 -m venv $APP/venv
$APP/venv/bin/python -c "import ssl; print(ssl.OPENSSL_VERSION)"   # 验证 ssl 可用
```

#### 步骤 2：解压 PostgreSQL 16 + initdb + 建库

```bash
cd $DB
tar -xJf postgresql-16.4-1-linux-x64-binaries.tar.xz
# 得到 $DB/pgsql/

export PATH=$DB/pgsql/bin:$PATH
export LD_LIBRARY_PATH=$DB/pgsql/lib:$LD_LIBRARY_PATH

# 初始化数据目录（首次）
initdb -D $DB/pgdata -U platform_mcp --auth-local=trust --auth-host=scram-sha-256

# 监听本机
cat >> $DB/pgdata/postgresql.conf <<EOF
listen_addresses = '127.0.0.1'
port = 5432
timezone = 'Asia/Shanghai'
log_timezone = 'Asia/Shanghai'
EOF

# 本机 trust 认证（生产可改 scram-sha-256 + 密码）
cat > $DB/pgdata/pg_hba.conf <<EOF
local   all   all               trust
host    all   all   127.0.0.1/32   trust
host    all   all   ::1/128        trust
EOF

# 启动 + 建库
pg_ctl -D $DB/pgdata -l $APP/logs/pg.log -o "-i" start
createdb -h 127.0.0.1 -U platform_mcp platform_mcp
```

#### 步骤 3：离线装应用依赖

```bash
cd $APP
tar -xzf Platform-MCP-app.tar.gz    # 解出 platform_mcp/ + pyproject.toml + alembic.ini + scripts/
$APP/venv/bin/pip install --no-index --find-links=$APP/wheels/ $APP/
# 验证核心依赖
$APP/venv/bin/python -c "import fastapi, mcp, oracledb, asyncpg, cryptography; print('all deps OK')"
```

#### 步骤 4：解压 Oracle Instant Client

```bash
cd $APP/oracle
unzip instantclient-basic-linux.x64-11.2.0.4.0.zip
# 得到 $APP/oracle/instantclient_11_2/
# 系统已装 libaio（见 §13.3 自检），无需额外
```

#### 步骤 5：生成密钥 + 写生产配置

```bash
head -c 32 /dev/urandom > $APP/secret/crypto-secret.key
chmod 600 $APP/secret/crypto-secret.key

cat > $APP/config/settings-prod.yml <<EOF
app:
  env: prod
server:
  host: "0.0.0.0"
  port: 8080
  workers: 1
  cors_origins: ["http://<server-host>:8080"]
database:
  url: "postgresql+asyncpg://platform_mcp@127.0.0.1:5432/platform_mcp"
  echo: false
  pool_size: 5
  max_overflow: 10
datasource:
  crypto_key_path: "$APP/secret/crypto-secret.key"
  oracle_instant_client_dir: "$APP/oracle/instantclient_11_2"
  allowed_sql_dirs: ["$APP/sql-scripts"]
  default_query_timeout: 300
  default_max_concurrent: 5
  max_file_size_mb: 10
mcp:
  transport: streamable-http
  http_host: "0.0.0.0"
  http_port: 9000
  http_path: "/mcp"
  operator_role: "admin"
log:
  level: INFO
  dir: "$APP/logs"
  rotation: "10 MB"
  retention: "30 days"
EOF
chmod 600 $APP/config/settings-prod.yml
```

#### 步骤 6：Alembic 迁移 + seed 用户

```bash
cd $APP
PKUMCP_ENV=prod venv/bin/python -m alembic upgrade head
# seed（首次）：scripts/_setup_local.py 已支持 trust 认证
PKUMCP_ENV=prod venv/bin/python scripts/_setup_local.py
# 若报密码错，临时：export PLATFORM_DB_USER=platform_mcp PLATFORM_DB_HOST=127.0.0.1
```

#### 步骤 7：启停脚本（模板见 §13.7）

把 §13.7 的 5 个脚本写到 `$APP/run/` 下，`chmod +x $APP/run/*.sh`。

#### 步骤 8：启动 + 验证

```bash
bash $APP/run/start_all.sh
sleep 5

# 健康检查
curl -s http://127.0.0.1:8080/api/v1/health                 # → {"status":"UP"}
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/   # → 200（前端）
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:9000/mcp/   # → 401（无 Key）
```

#### 步骤 9：用户级 crontab 自启

```bash
(crontab -l 2>/dev/null; echo "@reboot $APP/run/start_all.sh >> $APP/logs/cron.log 2>&1") | crontab -
```

#### 步骤 10：每日备份 cron

```bash
mkdir -p /opt/<user>/mcp_app/backup
CRON_LINE="0 2 * * * $DB/pgsql/bin/pg_dump -h 127.0.0.1 -U platform_mcp -d platform_mcp -F c -f /opt/<user>/mcp_app/backup/platform_mcp_\$(date +\%Y\%m\%d).dump && find /opt/<user>/mcp_app/backup -name 'platform_mcp_*.dump' -mtime +30 -delete"
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
```

### 13.7 启停脚本模板

#### `run/start_pg.sh`

```bash
#!/bin/bash
APP=/opt/<user>/mcp_app/app
DB=/opt/<user>/mcp_app/db
export PATH=$DB/pgsql/bin:$PATH
export LD_LIBRARY_PATH=$DB/pgsql/lib:$LD_LIBRARY_PATH
pg_ctl -D $DB/pgdata -l $APP/logs/pg.log start
```

#### `run/start_web.sh`

```bash
#!/bin/bash
APP=/opt/<user>/mcp_app/app
export PATH=$APP/venv/bin:$APP/python/bin:$PATH
export LD_LIBRARY_PATH=$APP/oracle/instantclient_11_2:$LD_LIBRARY_PATH
export PKUMCP_ENV=prod
cd $APP
nohup venv/bin/python -m platform_mcp.main > logs/web.out 2>&1 &
echo $! > run/web.pid
```

#### `run/start_mcp.sh`

```bash
#!/bin/bash
APP=/opt/<user>/mcp_app/app
export PATH=$APP/venv/bin:$APP/python/bin:$PATH
export LD_LIBRARY_PATH=$APP/oracle/instantclient_11_2:$LD_LIBRARY_PATH
export PKUMCP_ENV=prod
cd $APP
nohup venv/bin/python -m platform_mcp.mcp_server > logs/mcp.out 2>&1 &
echo $! > run/mcp.pid
```

#### `run/start_all.sh`

```bash
#!/bin/bash
APP=/opt/<user>/mcp_app/app
bash $APP/run/start_pg.sh
sleep 3
bash $APP/run/start_web.sh
sleep 1
bash $APP/run/start_mcp.sh
```

#### `run/stop_all.sh`

```bash
#!/bin/bash
APP=/opt/<user>/mcp_app/app
DB=/opt/<user>/mcp_app/db
[ -f $APP/run/mcp.pid ] && kill $(cat $APP/run/mcp.pid) 2>/dev/null
[ -f $APP/run/web.pid ] && kill $(cat $APP/run/web.pid) 2>/dev/null
$DB/pgsql/bin/pg_ctl -D $DB/pgdata stop
```

> ⚠️ **settings 类变更必须 stop_all.sh + start_all.sh，禁止只跑 start_all.sh**
>
> 生产环境实际 `start_all.sh` 含"进程在跑就 skip"逻辑（避免重复启动双实例）。
> 这意味着：仅修改 `settings-prod.yml` / `crypto-secret.key` / `.env` 后直接跑 `start_all.sh`，
> MCP/Web 进程仍存在 → 脚本 skip → **变更不生效**。
>
> **正确流程**（settings / crypto key / 环境变量类变更）：
> ```bash
> bash $APP/run/stop_all.sh
> # 确认进程已退出（防御）
> pgrep -af 'platform_mcp|mcp_server' && pkill -9 -f 'platform_mcp' || true
> bash $APP/run/start_all.sh
> ```
>
> **代码类变更**：走 §13.12 升级流程（其中已包含 stop_all.sh → start_all.sh，无需额外处理）。
> 验证：变更后 `curl http://127.0.0.1:8080/api/v1/health` + MCP 实际调用一次确认行为符合预期。

### 13.8 代码改动：FastAPI StaticFiles mount

> **唯一代码改动**：让 FastAPI 单端口同时承担 API 与静态前端，弃用 Nginx。

**文件**：`platform_mcp/main.py`，在 `register_api_routes(app)` 之后、`health` 路由之前追加：

```python
# 静态前端：仅当 ui/dist 存在时挂载（开发环境不挂）
from pathlib import Path
from fastapi.staticfiles import StaticFiles

_UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
if _UI_DIST.exists():
    app.mount("/", StaticFiles(directory=_UI_DIST, html=True), name="ui")
```

**作用**：
- 生产环境 `$APP/ui/dist/` 存在 → mount，访问 `http://<host>:8080/` 返回前端 index.html
- 开发环境 dist 不存在 → 不 mount，前端走 Vite 5173，互不影响

**不改**：
- `mcp_server/__init__.py`（已 ASGI middleware，9000 端口独立）
- `config.py`（`PKUMCP_ENV` 加载机制已就绪）
- `scripts/_setup_local.py`（已支持 `PLATFORM_DB_*` 环境变量）

### 13.9 验证 + Claude Code 远程接入

**部署后冒烟**：

| 端点 | 期望 |
|------|------|
| `curl http://<host>:8080/api/v1/health` | `{"status":"UP"}` |
| `curl -I http://<host>:8080/` | HTTP 200，Content-Type: text/html |
| `curl -X POST http://<host>:9000/mcp/`（无 Header） | HTTP 401 |
| `curl -X POST http://<host>:9000/mcp/ -H "PLATFORM_MCP_API_KEY:<key>" -d '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'` | HTTP 200 + `mcp-session-id` Header |

**Claude Code 远程接入**（`~/.claude.json`）：

```json
{
  "mcpServers": {
    "Platform-MCP": {
      "url": "http://<server-host>:9000/mcp",
      "transport": "http",
      "headers": {
        "PLATFORM_MCP_API_KEY": "<admin 在 Web 端生成后导出的 key>"
      }
    }
  }
}
```

### 13.10 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| `python-build-standalone` 在 glibc 2.17 跑不动 | Python 起不来 | manylinux2014 链接（glibc 2.17 兼容）；跑不动则 fallback 到源码编译（OpenSSL 1.1.1 头文件齐全，仅 `_ctypes`/`_sqlite3` 等模块缺失，不影响核心 wheel） |
| 离线 wheel 缺包 | pip install 失败 | 跳板机 `pip download` 自动解析依赖；安装报错时按提示追加下载 |
| portable PG 进程挂掉 | Web 报 500 | `start_all.sh` 启动前 `pg_ctl status` 检查；可选 watchdog cron 每分钟探活重启 |
| pgdata 损坏（机器崩溃） | 数据丢失 | §13.6 步骤 10 已配 pg_dump + 30 天保留 |
| `ulimit -n` 默认 1024 | 高并发时 too many open files | 一期并发低，先观察；调高需在 `start_*.sh` 加 `ulimit -n 65536`（受 hard limit 限制） |
| 同机其他应用资源争抢 | 内存/CPU 紧张 | 评估总占用；Platform-MCP Web+MCP+PG 共 ~500MB |
| `settings-prod.yml` 含敏感路径 | 泄露风险 | 文件 mode 0600，`crypto-secret.key` mode 0600，均不进 Git |
| 无 systemd → 重启不自启 | 业务不可用 | 用户级 `crontab @reboot`（§13.6 步骤 9） |
| 无 Nginx → 无 HTTPS | 明文传输 | 内网部署可接受；如需 HTTPS 走 uvicorn `--ssl-certfile/--ssl-keyfile`，证书由运维签发 |

### 13.11 回滚

```bash
# 仅停服务（数据保留）
bash $APP/run/stop_all.sh

# 完整回滚（含数据恢复）
bash $APP/run/stop_all.sh
$DB/pgsql/bin/pg_restore -h 127.0.0.1 -U platform_mcp -d platform_mcp -c /opt/<user>/mcp_app/backup/platform_mcp_YYYYMMDD.dump
bash $APP/run/start_all.sh
```

### 13.12 升级流程

```bash
# (1) 跳板机：取新版本 app tarball + 新增 wheel（若有新增依赖）
# (2) 内网目标机
bash $APP/run/stop_all.sh
mv $APP/platform_mcp $APP/platform_mcp.bak.$(date +%Y%m%d)
tar -xzf Platform-MCP-app-<new>.tar.gz -C $APP/
# 如有新依赖：跳板机 pip download 后追加到 wheels/
$APP/venv/bin/pip install --no-index --find-links=$APP/wheels/ $APP/ --upgrade
PKUMCP_ENV=prod $APP/venv/bin/python -m alembic upgrade head
bash $APP/run/start_all.sh

# (3) 回滚代码（数据保留）
bash $APP/run/stop_all.sh
rm -rf $APP/platform_mcp
mv $APP/platform_mcp.bak.YYYYMMDD $APP/platform_mcp
PKUMCP_ENV=prod $APP/venv/bin/python -m alembic downgrade -1
bash $APP/run/start_all.sh
```
