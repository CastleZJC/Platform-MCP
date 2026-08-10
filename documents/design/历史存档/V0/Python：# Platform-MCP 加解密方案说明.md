# Platform-MCP 加解密方案说明

> **文档名称**：Platform-MCP 加解密方案说明
> **基于文档**：《Platform-MCP 技术架构说明文档》
>
> **修订记录**：
>
> | 版本 | 日期时间 | 修订性质 | 修订摘要 | 修改人 |
> |------|----------|----------|----------|--------|
> | v20260603090000 | 2026-06-03 09:00:00 | 初始创建 | 基于技术架构文档，建立双层加解密方案 | castle.zhang |
>
> **适用对象**：后端开发、运维工程师、安全评审人员
> **文档用途**：定义 Platform-MCP 平台敏感数据加解密策略、技术选型、使用方法与部署集成方案

---

## 一、方案概述

### 1.1 背景与需求

Platform-MCP 平台在配置文件和数据库中存储多种敏感信息：

- 数据源连接密码（`pmcp_datasource.encrypted_password`）
- 加密密钥本身的管理与保护
- 审计日志中禁止记录明文密码

**安全要求**：

1. 配置文件中所有敏感值**不得以明文形式存储**
2. 数据库中存储的敏感字段**不得以明文形式存储**
3. 各环境（dev / test / prod）**统一使用密文加密**
4. 双进程（Web + MCP Server）共享同一密钥

### 1.2 加密分层策略

```
┌───────────────────────────────────────────────────────┐
│       第一层：运行时凭证保护（独立 Secret 文件）           │
│  ┌───────────────────────────────────────────────────┐ │
│  │ AES-256-GCM 加密密钥存储于独立文件                  │ │
│  │ 机制：文件权限 0600 + .gitignore 排除               │ │
│  │ 读取：应用启动时从指定路径加载                       │ │
│  │ 保护：文件权限 + 配置分离 + 进程隔离                 │ │
│  └───────────────────────────────────────────────────┘ │
│                                                       │
│              第二层：数据库存储加密                       │
│  ┌───────────────────────────────────────────────────┐ │
│  │ pmcp_datasource.encrypted_password 敏感字段          │ │
│  │ 工具：CryptoUtils（AES-256-GCM，CBC 作为兼容备选） │ │
│  │ 格式：AES:base64(iv+ciphertext+tag)               │ │
│  │ 时机：业务代码在写入/读取时显式加解密                │ │
│  └───────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

**两层密钥独立管理**：secret 密钥文件与数据库密文各自独立。

### 1.3 安全边界认知

> 加解密方案解决的核心问题是**防止配置文件泄露**（Git 泄露、备份泄露、文件系统遍历），而非防止服务器 root 级攻击。
>
> 攻击者如果已获得服务器 root/shell 权限，任何方案都无法保护密码——因为密码最终必须以明文形式存在于应用内存中。
>
> 本方案属于**纵深防御**：配置文件密文 + 密钥安全传递，使得单一泄露途径无法获取完整凭证。

---

## 二、技术选型

### 2.1 加密算法

| 维度 | 选择 | 说明 |
|------|------|------|
| 算法（默认） | AES-256-GCM | 认证加密，防篡改；所有新写入使用 GCM |
| 算法（兼容备选） | AES-256-CBC | 仅用于解密历史遗留密文，新写入不使用 |
| 库 | cryptography 43.0.1 | Python 标准加密库，Apache 2.0 |
| 密钥长度 | 256 位（32 字节） | AES-256 |
| IV 长度 | GCM 12 字节 / CBC 16 字节 | 各模式推荐长度 |
| 认证标签 | 128 位 | GCM 默认；CBC 模式无认证标签 |
| 填充方式 | GCM 无需填充 / CBC 使用 PKCS7 | CBC 标准填充 |

### 2.2 密钥管理方式

| 维度 | 环境变量注入 | 独立 Secret 文件（选定） |
|------|-------------|------------------------|
| 安全性 | `ps aux` 可见，进程信息泄露 | 文件权限 0600，仅应用用户可读 |
| 多进程 | 环境变量需分别设置 | 两个进程共享同一文件 |
| 审计 | 难以追踪读取 | 文件访问可审计 |
| 运维 | 修改需重启 | 修改密钥文件后重启 |

**选型结论：独立 Secret 文件**

理由：Platform-MCP 为双进程架构（systemd 托管 Web + Claude Code 子进程 MCP Server），共享文件系统上的 secret 文件是最自然且安全的密钥共享方式。

---

## 三、运行时凭证保护（独立 Secret 文件）

### 3.1 方案概述

加密密钥存储于独立文件，应用启动时读取。配置文件中仅指定密钥文件路径，不包含实际密钥内容。

**配置文件示例（settings.yml）**：

```yaml
datasource:
  crypto_key_path: /opt/Platform-MCP/secret/crypto-secret.key
```

**密钥文件内容**：32 字节随机二进制（AES-256 密钥），由 `CryptoUtils.generate_key()` 或 `openssl rand -out crypto-secret.key 32` 生成。

### 3.2 Secret 文件清单

| 文件 | 路径 | 用途 | 权限 |
|------|------|------|------|
| `crypto-secret.key` | `/opt/Platform-MCP/secret/crypto-secret.key` | AES-256-GCM 加密密钥 | 0600 |

### 3.3 配置文件引用方式

使用 `pydantic-settings` 读取配置（在 `platform_mcp.config.DatasourceSettings` 中定义）：

```python
class DatasourceSettings(BaseSettings):
    crypto_key_path: str = ""  # 密钥文件路径
    oracle_instant_client_dir: str = ""
    # ...

class AppSettings(BaseSettings):
    datasource: DatasourceSettings = Field(default_factory=DatasourceSettings)
```

### 3.4 双进程密钥共享

Platform-MCP 有两个独立进程共享同一密钥：

| 进程 | 启动方式 | 密钥获取 |
|------|---------|---------|
| Web（FastAPI） | systemd 托管 | 启动时从配置文件读取 key_file 路径，加载密钥 |
| MCP Server | Claude Code 子进程 | 启动时从同一配置文件读取 key_file 路径，加载密钥 |

两个进程共享 `/opt/Platform-MCP/secret/` 目录和 `/opt/Platform-MCP/config/` 配置文件。

### 3.5 开发环境配置

开发环境密钥文件路径在 `settings-dev.yml` 中覆盖（或使用项目根目录的 `crypto-secret.key`）：

```yaml
# settings-dev.yml
datasource:
  crypto_key_path: "crypto-secret.key"
```

`.gitignore` 中添加：

```
secret/
*.key
settings-dev.yml
```

---

## 四、数据库存储加密（业务层）

### 4.1 适用范围

| 字段 | 表 | 加密方式 | 说明 |
|------|-----|---------|------|
| `encrypted_password` | pmcp_datasource | AES-256-GCM（CBC 作为兼容备选，可逆） | 数据源连接密码，使用时需解密 |

### 4.2 加密工具类设计

**模块**：`platform_mcp.common.crypto`

```python
import base64
import os
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoUtils:
    """AES-256-GCM 加解密工具类，用于数据库中敏感字段的加解密。
    密文格式：AES:base64(iv+ciphertext+tag)
    """

    PREFIX_GCM = "AES:"
    PREFIX_CBC = "AES-CBC:"

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("密钥必须是 32 字节 (AES-256)")
        self._key = key

    def encrypt(self, plaintext: str) -> str:
        """AES-256-GCM 加密，返回 AES:base64(iv+ciphertext+tag) 格式"""
        nonce = os.urandom(12)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return f"{self.PREFIX_GCM}{base64.b64encode(nonce + ciphertext).decode()}"

    def decrypt(self, ciphertext: str) -> str:
        """解密，自动识别 GCM/CBC 格式，无前缀视为明文透传"""
        if ciphertext.startswith(self.PREFIX_GCM):
            return self._decrypt_gcm(ciphertext[len(self.PREFIX_GCM):])
        elif ciphertext.startswith(self.PREFIX_CBC):
            return self._decrypt_cbc(ciphertext[len(self.PREFIX_CBC):])
        return ciphertext

    @staticmethod
    def generate_key() -> bytes:
        """生成 32 字节随机密钥"""
        return os.urandom(32)
```

**密钥加载入口（集中化）**：所有需要 `CryptoUtils` 实例的业务代码必须通过 `platform_mcp.datasource.manager._get_crypto_utils()` 获取，禁止直接 `CryptoUtils(key)` —— 这是 CLAUDE.md 明确要求的集中加载约束，确保双进程（Web + MCP Server）使用同一密钥文件。

**CBC 兼容解密说明**：

当解密遇到历史遗留的 CBC 密文（前缀 `AES-CBC:`）时，CryptoUtils 自动切换为 CBC 模式解密。新写入一律使用 GCM，CBC 仅做解密兼容。

```
密文格式区分：
  AES:base64(...)      → GCM 模式（默认）
  AES-CBC:base64(...)  → CBC 模式（历史遗留）
  无前缀               → 明文直接返回
```

**密钥生成方式**：

```bash
# Linux（生成 32 字节二进制）
openssl rand -out /opt/Platform-MCP/secret/crypto-secret.key 32
chmod 600 /opt/Platform-MCP/secret/crypto-secret.key

# 项目内置（开发环境）
python -c "from platform_mcp.common.crypto import CryptoUtils; open('crypto-secret.key','wb').write(CryptoUtils.generate_key())"
```

### 4.3 使用示例

#### 保存数据源时加密

```python
from platform_mcp.datasource.manager import _get_crypto_utils

async def create_datasource(db: AsyncSession, dto: DatasourceCreateRequest) -> int:
    crypto = _get_crypto_utils()
    encrypted_pwd = crypto.encrypt(dto.password)
    ds = PmcpDatasource(
        datasource_name=dto.name,
        db_type=dto.db_type,
        encrypted_password=encrypted_pwd,
        # ...
    )
    db.add(ds)
    await db.commit()
    return ds.id
```

#### 使用数据源时解密

```python
from platform_mcp.datasource.manager import _get_crypto_utils

async def get_connection(datasource: PmcpDatasource):
    crypto = _get_crypto_utils()
    plain_password = crypto.decrypt(datasource.encrypted_password)
    # 使用 plain_password 建立连接
```

### 4.4 数据库字段格式

**密文格式**：`AES:base64EncodedCiphertext`

```
明文: MySecretPassword123
密文: AES:Y2hhbmdlX3RoaXNfYW5kX3RyeQ==...
```

**兼容策略**：

- 字段值以 `AES:` 开头 → GCM 密文，GCM 解密
- 字段值以 `AES-CBC:` 开头 → CBC 密文（历史遗留），CBC 解密
- 字段值不以 `AES:` 或 `AES-CBC:` 开头 → 视为明文，直接使用

此兼容策略支持**渐进迁移**：无需一次性迁移所有存量数据，新写入走加密，存量数据按需迁移。

### 4.5 密钥传递

| 环境 | 传递方式 |
|------|---------|
| 开发 | `settings-dev.yml` 指定本地密钥文件路径 |
| 生产 | `settings-prod.yml` 指定 `/opt/Platform-MCP/secret/crypto-secret.key` |

---

## 五、安全注意事项

### 5.1 密钥轮换流程

1. 生成新密钥：`openssl rand -32 | base64 -w 0`
2. 编写数据迁移脚本：用旧密钥解密 → 用新密钥加密 → 更新数据库记录
3. 替换密钥文件内容
4. 重启 Web 进程（`systemctl restart Platform-MCP`）
5. MCP Server 在下次启动时自动使用新密钥
6. 验证数据源连接正常

**轮换建议频率**：

| 密钥类型 | 建议频率 | 说明 |
|---------|---------|------|
| crypto-secret.key | 每半年评估 | 需同步迁移数据库密文 |

### 5.2 密钥泄露应急响应

1. **发现**：确认泄露范围
2. **隔离**：限制泄露渠道（撤销 Git 历史、更换文件权限）
3. **轮换**：立即生成新密钥并替换 secret 文件
4. **迁移**：执行数据迁移脚本（旧密钥解密 → 新密钥加密）
5. **重启**：重启所有服务
6. **验证**：确认新密钥生效、旧密钥失效
7. **复盘**：记录泄露原因，加强防护措施

### 5.3 密文迁移策略

**新部署**：直接使用密文，无需迁移。

**已有明文数据迁移**：

1. 部署含 CryptoUtils 的应用版本（兼容模式：无前缀视为明文）
2. 确认应用正常运行
3. 执行迁移脚本，将数据库中的明文字段加密为 `AES:...` 格式
4. 验证迁移结果

### 5.4 安全红线

| 规则 | 说明 |
|------|------|
| Secret 文件不提交 Git | `secret/` 和 `*.key` 在 `.gitignore` 排除 |
| Secret 文件权限 0600 | 仅应用运行用户可读 |
| 配置文件不含实际密钥 | 仅指定密钥文件路径 |
| 审计日志禁止记录明文 | 加解密操作仅记录动作，不记录内容 |
| 生产密钥定期评估轮换 | 按频率评估并执行 |

---

## 六、开源许可

| 组件 | 版本 | 许可证 | 说明 |
|------|------|--------|------|
| cryptography | 43.0.1 | Apache License 2.0 | AES-256-GCM 算法提供者 |

---

## 附录

### A. 密钥生成与部署

```bash
# 1. 生成密钥（32 字节二进制）
openssl rand -out /opt/Platform-MCP/secret/crypto-secret.key 32

# 2. 设置权限
chmod 600 /opt/Platform-MCP/secret/crypto-secret.key
chown platform_mcp:platform_mcp /opt/Platform-MCP/secret/crypto-secret.key

# 3. 验证
wc -c /opt/Platform-MCP/secret/crypto-secret.key  # 应输出 32
```

### B. 密文格式速查

| 格式 | 示例 | 说明 |
|------|------|------|
| 数据库字段密文（GCM） | `AES:Y2hhbmdlX3RoaXNf...` | 以 AES: 开头，默认格式 |
| 数据库字段密文（CBC） | `AES-CBC:Y2hhbmdlX3RoaXNf...` | 以 AES-CBC: 开头，历史遗留 |
| 无前缀（明文） | `MyPassword123` | 兼容渐进迁移 |

### C. 相关文档

| 文档 | 关系 |
|------|------|
| 《Platform-MCP 部署规范》| secret 目录结构与权限管理 |
| 《Platform-MCP 代码规范》| 加解密代码编写规范 |
| 《Platform-MCP 技术架构说明文档》§12.3 | 密码加解密架构设计 |
