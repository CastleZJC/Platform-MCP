"""Platform-MCP 配置管理模块 — pydantic-settings + YAML 加载"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(env: str = "dev") -> dict:
    """加载 settings.yml 和 settings-{env}.yml，后者覆盖前者"""
    base_file = _PROJECT_ROOT / "settings.yml"
    env_file = _PROJECT_ROOT / f"settings-{env}.yml"

    config: dict = {}
    if base_file.exists():
        with open(base_file, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            env_config = yaml.safe_load(f) or {}
        _deep_merge(config, env_config)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class DatabaseSettings(BaseSettings):
    url: str = "postgresql+asyncpg://postgres@localhost:5432/platform_mcp"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10


class DatasourceSettings(BaseSettings):
    oracle_instant_client_dir: str = ""
    allowed_sql_dirs: list[str] = []
    default_query_timeout: int = 300
    default_max_concurrent: int = 5
    max_file_size_mb: int = 10
    crypto_key_path: str = ""
    # SFTP 工作站↔MCP 服务器中转目录（BUG20260814163941）；空 = 运行时解析为 {项目根}/sftp_exchange
    sftp_exchange_dir: str = ""


class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


class LogSettings(BaseSettings):
    level: str = "INFO"
    dir: str = "logs"
    rotation: str = "10 MB"
    retention: str = "30 days"


class McpSettings(BaseSettings):
    operator_role: str = "admin"
    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 9000
    http_path: str = "/mcp"


class SkillSettings(BaseSettings):
    upload_dir: str = "uploads/skills"
    max_upload_size_mb: int = 50
    # V3.0 M3（架构 §19.5.6）：广场语义搜索向量栈
    # embedding_backend: auto（探测 pgvector，不可用降级 jsonb）/ pgvector / jsonb（内存余弦，VNF-02）
    embedding_backend: str = "auto"
    # BGE-M3 权重离线目录（VNF-03：不入仓库、不联网下载）；非空且 fastembed 可用才启用 BGE-M3，
    # 否则降级确定性哈希向量（权重缺失降级），保证搜索链路始终可用且可测。
    embedding_model_path: str = ""
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_dim: int = 1024          # BGE-M3 dense 向量维度（pgvector 原生列 vector(1024)）
    embedding_fallback_dim: int = 256  # 降级哈希向量维度（JSONB 存储，控制体积）
    # V3.0 M4（架构 §19.5.6）：本地生成模型栈 —— Qwen3-4B-Instruct GGUF 经 llama-cpp-python（纯 CPU）
    # 产出中英审核报告 / 英文 README / 分享迭代差异描述；权重离线分发（VNF-03：不入仓库、不联网下载），
    # 非空且 llama-cpp-python 可加载才启用，否则模板兜底（60s 超时同样兜底，F-35/VNF-01）。
    # 静态配置（加载期初始化 Provider，切换权重需重启，§19.5.2 静态/动态边界）。
    llm_model_path: str = ""
    llm_model_name: str = "Qwen3-4B-Instruct-GGUF"
    llm_timeout_seconds: int = 60   # 单次生成超时（超时放弃本次，模板兜底）
    llm_max_tokens: int = 1024      # 单次生成最大 token
    llm_n_ctx: int = 8192           # 上下文窗口（prompt + 输出）


class NotifySettings(BaseSettings):
    """V3.0 M5（架构 §19.5.5）：邮件组提醒 —— outbox 发送侧调度参数。

    SMTP 连接参数（host/port/user/password/from）不在 settings：全部经运行时配置中心
    `smtp.*` 键（M1 已注册，flush 时实时读取，免改配置重启，架构 §19.5.2/§19.5.5）。
    """

    flush_interval_seconds: int = 30  # Web 进程周期 flush 间隔
    flush_batch_size: int = 20        # 每轮最多发送条数（防单轮长阻塞）
    max_retry: int = 5                # 单条 outbox 最大重试次数（超过不再重试，状态留 failed）


class AppSettings(BaseSettings):
    name: str = "Platform-MCP"
    version: str = "0.1.0"
    env: str = "dev"

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    datasource: DatasourceSettings = Field(default_factory=DatasourceSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    skill: SkillSettings = Field(default_factory=SkillSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    env = os.getenv("PLATFORM_MCP_ENV", "dev")
    raw = _load_yaml(env)
    # YAML 中 app: 嵌套层提取到顶层
    if "app" in raw:
        raw.update(raw.pop("app"))
    return AppSettings(**raw)
