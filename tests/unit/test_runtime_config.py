"""单元测试 — 运行时配置中心（V3.0 M1，架构 §19.5.2）

覆盖：validate_value 类型解析与注册表一致性；
RuntimeConfigService 快照读取 / 默认回退 / 失效刷新 / DB 故障容错。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.common.runtime_config import KNOWN_KEYS, RuntimeConfigService, validate_value
from platform_mcp.i18n import RESOURCES


class TestValidateValue:
    def test_int_ok(self):
        assert validate_value("session.timeout_minutes", "45") == 45

    def test_int_invalid(self):
        with pytest.raises(ValueError):
            validate_value("session.timeout_minutes", "abc")

    def test_int_negative_rejected(self):
        with pytest.raises(ValueError):
            validate_value("session.timeout_minutes", "-1")

    def test_locale_key(self):
        assert validate_value("sys.default_locale", "en-US") == "en-US"
        with pytest.raises(ValueError):
            validate_value("sys.default_locale", "fr-FR")

    def test_log_level(self):
        assert validate_value("log.level", "debug") == "DEBUG"
        with pytest.raises(ValueError):
            validate_value("log.level", "VERBOSE")

    def test_page_size_choices(self):
        assert validate_value("sys.default_page_size", "50") == 50
        assert validate_value("sys.default_page_size", "75") == 75
        with pytest.raises(ValueError):
            validate_value("sys.default_page_size", "15")
        with pytest.raises(ValueError):
            validate_value("sys.default_page_size", "30")

    def test_unknown_key_passthrough(self):
        assert validate_value("custom.unknown.key", "whatever") == "whatever"


class TestKnownKeysRegistry:
    def test_registry_completeness(self):
        assert len(KNOWN_KEYS) == 13

    def test_effect_semantics(self):
        for key, spec in KNOWN_KEYS.items():
            assert spec.effect in ("relogin", "immediate", "new_user_only"), key

    def test_relogin_keys(self):
        relogin = {k for k, s in KNOWN_KEYS.items() if s.effect == "relogin"}
        assert relogin == {"sys.default_locale", "session.timeout_minutes"}

    def test_new_user_only_keys(self):
        nu = {k for k, s in KNOWN_KEYS.items() if s.effect == "new_user_only"}
        assert nu == {"sys.default_page_size"}

    def test_page_size_choices_spec(self):
        assert KNOWN_KEYS["sys.default_page_size"].choices == (5, 10, 20, 50, 75, 100)
        assert KNOWN_KEYS["sys.default_page_size"].default_factory() == 20

    def test_sensitive_keys(self):
        sensitive = {k for k, s in KNOWN_KEYS.items() if s.sensitive}
        assert sensitive == {"smtp.password"}

    def test_desc_keys_resolvable_by_i18n(self):
        """注册表描述键必须可被 i18n 字典解析（消费端闭环）。"""
        for key, spec in KNOWN_KEYS.items():
            assert spec.desc_key.startswith("config.desc."), key
            assert spec.desc_key in RESOURCES, key


class TestRuntimeConfigService:
    def test_unknown_key_raises(self):
        svc = RuntimeConfigService()
        with pytest.raises(KeyError):
            svc.get_sync("no.such.key")

    def test_defaults_without_load(self):
        svc = RuntimeConfigService()
        assert svc.get_sync("session.timeout_minutes") == 30
        assert svc.get_sync("sys.default_locale") == "zh-CN"
        assert svc.get_sync("sys.default_page_size") == 20

    def test_raw_configured_none_when_unset(self):
        svc = RuntimeConfigService()
        assert svc.raw_configured("session.timeout_minutes") is None

    def test_snapshot_typed_value(self):
        svc = RuntimeConfigService()
        svc._raw = {"session.timeout_minutes": "45"}
        svc._loaded = True
        assert svc.get_sync("session.timeout_minutes") == 45
        assert svc.raw_configured("session.timeout_minutes") == "45"

    def test_invalid_snapshot_falls_back_to_default(self):
        svc = RuntimeConfigService()
        svc._raw = {"session.timeout_minutes": "abc"}
        svc._loaded = True
        assert svc.get_sync("session.timeout_minutes") == 30

    def test_invalidate_resets_snapshot_time(self):
        svc = RuntimeConfigService()
        svc._snapshot_at = 123.0
        svc.invalidate()
        assert svc._snapshot_at == 0.0

    @pytest.mark.asyncio
    async def test_refresh_db_failure_first_load(self):
        """首次加载即失败：回退空快照 + loaded=True，业务读取走注册表默认值。"""
        svc = RuntimeConfigService()
        with patch("platform_mcp.common.database.get_session_factory", side_effect=RuntimeError("db down")):
            await svc.refresh(force=True)
        assert svc.loaded is True
        assert svc.get_sync("session.timeout_minutes") == 30

    @pytest.mark.asyncio
    async def test_refresh_loads_rows(self):
        svc = RuntimeConfigService()
        row = SimpleNamespace(config_key="session.timeout_minutes", config_value="99", status=1)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=session_cm)
        with patch("platform_mcp.common.database.get_session_factory", return_value=factory):
            await svc.refresh(force=True)
        assert svc.raw_configured("session.timeout_minutes") == "99"
        assert svc.get_sync("session.timeout_minutes") == 99
