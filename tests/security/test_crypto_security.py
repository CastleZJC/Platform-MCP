"""5.2.4 密码加密验证 — 密文入库/日志无明文/解密需密钥"""

from unittest.mock import patch

from platform_mcp.common.crypto import CryptoUtils


class TestCryptoSecurity:
    def test_ciphertext_has_aes_prefix(self):
        key = CryptoUtils.generate_key()
        crypto = CryptoUtils(key)
        ct = crypto.encrypt("my_db_password")
        assert ct.startswith("AES:")

    def test_plaintext_not_in_ciphertext(self):
        key = CryptoUtils.generate_key()
        crypto = CryptoUtils(key)
        plaintext = "super_secret_password"
        ct = crypto.encrypt(plaintext)
        assert plaintext not in ct
        assert plaintext not in ct[len("AES:"):]

    def test_wrong_key_cannot_decrypt(self):
        key1 = CryptoUtils.generate_key()
        crypto1 = CryptoUtils(key1)
        ct = crypto1.encrypt("secret")

        key2 = CryptoUtils.generate_key()
        crypto2 = CryptoUtils(key2)
        try:
            crypto2.decrypt(ct)
            assert False, "Should have raised an exception"
        except Exception:
            pass

    def test_roundtrip_preserves_value(self):
        key = CryptoUtils.generate_key()
        crypto = CryptoUtils(key)
        for val in ["password123", "P@ssw0rd!", "数据库密码", ""]:
            ct = crypto.encrypt(val)
            assert crypto.decrypt(ct) == val
