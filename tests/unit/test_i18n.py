"""单元测试 — i18n 资源字典（V3.0 M1，架构 §19.5.2）

覆盖：normalize_locale 回退链、get_text 语言/回退/参数插值、资源字典多语言 1:1 覆盖。
"""

from platform_mcp.i18n import (
    DEFAULT_LOCALE,
    RESOURCES,
    SUPPORTED_LOCALES,
    get_text,
    normalize_locale,
    split_bilingual,
)


class TestNormalizeLocale:
    def test_supported_passthrough(self):
        assert normalize_locale("zh-CN") == "zh-CN"
        assert normalize_locale("en-US") == "en-US"

    def test_invalid_falls_back_to_default(self):
        assert normalize_locale("fr-FR") == DEFAULT_LOCALE
        assert normalize_locale("") == DEFAULT_LOCALE
        assert normalize_locale(None) == DEFAULT_LOCALE

    def test_constants(self):
        assert DEFAULT_LOCALE == "zh-CN"
        assert set(SUPPORTED_LOCALES) == {"zh-CN", "en-US"}


class TestGetText:
    def test_default_locale_zh(self):
        assert get_text("config.effect.immediate") == "即时生效"
        assert get_text("config.effect.relogin") == "重新登录后生效"

    def test_en_us(self):
        assert get_text("config.effect.immediate", "en-US") == "Effective immediately"
        assert get_text("config.effect.relogin", "en-US") == "Effective after re-login"

    def test_unknown_locale_falls_back_to_default(self):
        assert get_text("config.effect.immediate", "fr-FR") == "即时生效"

    def test_missing_key_returns_key(self):
        assert get_text("no.such.key") == "no.such.key"

    def test_params_interpolation(self):
        RESOURCES["__test__.param"] = {"zh-CN": "你好 {name}", "en-US": "Hello {name}"}
        try:
            assert get_text("__test__.param", "zh-CN", name="Castle") == "你好 Castle"
            assert get_text("__test__.param", "en-US", name="Castle") == "Hello Castle"
        finally:
            del RESOURCES["__test__.param"]

    def test_params_error_falls_back_to_raw(self):
        RESOURCES["__test__.bad"] = {"zh-CN": "值 {missing}", "en-US": "Value {missing}"}
        try:
            assert get_text("__test__.bad", "zh-CN", other=1) == "值 {missing}"
        finally:
            del RESOURCES["__test__.bad"]

    def test_all_resources_cover_every_locale(self):
        """资源字典 1:1 覆盖：每个 key 必须为全部支持语言提供非空文案。"""
        for key, entry in RESOURCES.items():
            for locale in SUPPORTED_LOCALES:
                assert entry.get(locale), f"{key} 缺少 {locale} 文案"


class TestSplitBilingual:
    def test_标准并列拆分(self):
        assert split_bilingual("列出数据源 / List datasources") == ("列出数据源", "List datasources")

    def test_中文段内工具清单斜杠不误切(self):
        text = "查询异步任务状态（execute_command / upload_file）的 execution_id / Query async task status"
        zh, en = split_bilingual(text)
        assert zh == "查询异步任务状态（execute_command / upload_file）的 execution_id"
        assert en == "Query async task status"

    def test_纯英文描述不拆_两语言同值(self):
        assert split_bilingual("HTTP / HTTPS client util") == ("HTTP / HTTPS client util",) * 2

    def test_英文段含CJK不拆_防误切(self):
        text = "说明 / 说明（English 段含中文）"
        assert split_bilingual(text) == (text, text)

    def test_空值返回空串(self):
        assert split_bilingual(None) == ("", "")
        assert split_bilingual("") == ("", "")
