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
    allowed_envs: list[str] | None = None
    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 9000
    http_path: str = "/mcp"


class SkillSettings(BaseSettings):
    upload_dir: str = "uploads/skills"
    max_upload_size_mb: int = 50


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


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    env = os.getenv("PLATFORM_MCP_ENV", "dev")
    raw = _load_yaml(env)
    # YAML 中 app: 嵌套层提取到顶层
    if "app" in raw:
        raw.update(raw.pop("app"))
    return AppSettings(**raw)
