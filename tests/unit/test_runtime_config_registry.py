"""单元测试 — 系统配置注册表部署期自检（V3.0，架构 §19.5.2）

覆盖：全量注册表默认自检通过（所有配置项参数均需在系统配置中，无硬代码空兜底）、
int/json_list/json_list_or_null/string 各类型默认值非法被检出、default_factory
异常被检出、label/hint i18n 缺失被检出。
"""

from __future__ import annotations

import pytest

from platform_mcp.common.runtime_config import KNOWN_KEYS, ConfigKeySpec, validate_registry


def _spec(key: str, value_type: str, default_factory, label_key: str = "config.label.log.level",
          hint_key: str | None = "config.hint.log.level") -> ConfigKeySpec:
    return ConfigKeySpec(key, value_type, "immediate", False, "config.desc.log.level",
                         default_factory, label_key=label_key, hint_key=hint_key)


class TestValidateRegistry:
    def test_全量注册表自检通过(self):
        """14 键默认值类型合法且 label/hint i18n 齐备（部署检查基线）"""
        assert validate_registry() == []

    def test_int默认值非法被检出(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "bad.int", _spec("bad.int", "int", lambda: "not-int"))
        problems = validate_registry()
        assert any("bad.int: int 键默认值非法" in p for p in problems)

    def test_int负数被检出(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "bad.neg", _spec("bad.neg", "int", lambda: -1))
        assert any("bad.neg: int 键默认值非法" in p for p in validate_registry())

    def test_json_list默认值非法被检出(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "bad.list", _spec("bad.list", "json_list", lambda: "DEV"))
        assert any("bad.list: json_list 键默认值非法" in p for p in validate_registry())

    def test_json_list_or_null合法None不报错(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "ok.nullable", _spec("ok.nullable", "json_list_or_null",
                                                             lambda: None))
        assert not any("ok.nullable" in p for p in validate_registry())

    def test_string默认值非法被检出(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "bad.str", _spec("bad.str", "string", lambda: 123))
        assert any("bad.str: string 键默认值非法" in p for p in validate_registry())

    def test_default_factory异常被检出(self, monkeypatch):
        def _boom():
            raise RuntimeError("settings missing")

        monkeypatch.setitem(KNOWN_KEYS, "bad.boom", _spec("bad.boom", "int", _boom))
        assert any("bad.boom: 默认值产出失败" in p for p in validate_registry())

    def test_label_key缺失被检出(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "bad.nolabel", _spec("bad.nolabel", "int", lambda: 1,
                                                             label_key=""))
        assert any("bad.nolabel: 配置项简述 i18n 缺失" in p for p in validate_registry())

    def test_hint_key不在i18n资源被检出(self, monkeypatch):
        monkeypatch.setitem(KNOWN_KEYS, "bad.nohint", _spec("bad.nohint", "int", lambda: 1,
                                                            hint_key="config.hint.absent.key"))
        assert any("bad.nohint: 取值参考 i18n 缺失" in p for p in validate_registry())

    @pytest.mark.asyncio
    async def test_部署自检不依赖数据库(self):
        """纯内存校验：settings 可加载即通过，无需 DB 连接（main lifespan 启动序最前）"""
        from platform_mcp.common.runtime_config import validate_registry as _v

        assert isinstance(_v(), list)
