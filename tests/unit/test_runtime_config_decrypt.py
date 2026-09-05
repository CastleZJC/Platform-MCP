"""M5 单元测试 — 运行时配置 sensitive 键透明解密（smtp.password AES-GCM 落库闭环）

覆盖 _decrypt_if_sensitive：非 sensitive 键透传、None 透传、AES: 前缀解密、
历史明文兼容透传、解密失败回退空串（快照不含该键 → get_sync 回退默认值）。
"""

from unittest.mock import MagicMock, patch

from platform_mcp.common.runtime_config import _decrypt_if_sensitive


def _crypto(decrypt_impl):
    crypto = MagicMock()
    crypto.decrypt = MagicMock(side_effect=decrypt_impl)
    utils = MagicMock()
    utils.decrypt = crypto.decrypt
    return utils


class TestDecryptIfSensitive:
    def test_none_passthrough(self):
        assert _decrypt_if_sensitive("smtp.password", None) is None

    def test_non_sensitive_key_untouched(self):
        """非 sensitive 键原样返回（不触碰解密器）"""
        with patch("platform_mcp.datasource.manager._get_crypto_utils") as get:
            assert _decrypt_if_sensitive("smtp.host", "smtp.x.com") == "smtp.x.com"
        get.assert_not_called()

    def test_unknown_key_untouched(self):
        with patch("platform_mcp.datasource.manager._get_crypto_utils") as get:
            assert _decrypt_if_sensitive("not.a.key", "v") == "v"
        get.assert_not_called()

    def test_sensitive_ciphertext_decrypted(self):
        """AES: 前缀密文 → 解密为明文进快照"""
        utils = _crypto(lambda v: "plain-secret" if v.startswith("AES:") else v)
        with patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=utils):
            assert _decrypt_if_sensitive("smtp.password", "AES:abc==") == "plain-secret"

    def test_sensitive_legacy_plaintext_passthrough(self):
        """历史明文（无前缀）兼容透传（CryptoUtils.decrypt 语义）"""
        utils = _crypto(lambda v: v)  # 模拟无前缀透传
        with patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=utils):
            assert _decrypt_if_sensitive("smtp.password", "legacy-plain") == "legacy-plain"
        utils.decrypt.assert_called_once_with("legacy-plain")

    def test_decrypt_failure_returns_empty(self):
        """解密失败（密钥更换等）→ 空串（快照不含该键，get_sync 回退默认值）"""
        utils = _crypto(lambda v: (_ for _ in ()).throw(ValueError("bad key")))
        with patch("platform_mcp.datasource.manager._get_crypto_utils", return_value=utils):
            assert _decrypt_if_sensitive("smtp.password", "AES:garbage==") == ""
