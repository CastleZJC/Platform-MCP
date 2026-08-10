"""5.1.3 CryptoUtils 单元测试 — 加密/解密/兼容明文"""

from platform_mcp.common.crypto import CryptoUtils


class TestCryptoUtils:
    def test_encrypt_decrypt_roundtrip(self, crypto):
        plaintext = "hello world 测试中文"
        ciphertext = crypto.encrypt(plaintext)
        assert crypto.decrypt(ciphertext) == plaintext

    def test_encrypt_returns_gcm_prefix(self, crypto):
        ciphertext = crypto.encrypt("test")
        assert ciphertext.startswith("AES:")

    def test_decrypt_plaintext_passthrough(self, crypto):
        assert crypto.decrypt("plain_password") == "plain_password"

    def test_decrypt_empty_string(self, crypto):
        assert crypto.decrypt("") == ""

    def test_generate_key_returns_32_bytes(self):
        key = CryptoUtils.generate_key()
        assert len(key) == 32
        assert isinstance(key, bytes)

    def test_generate_key_unique_each_time(self):
        k1 = CryptoUtils.generate_key()
        k2 = CryptoUtils.generate_key()
        assert k1 != k2

    def test_init_rejects_wrong_key_length(self):
        import pytest
        with pytest.raises(ValueError, match="32 字节"):
            CryptoUtils(b"short")

    def test_decrypt_invalid_gcm_ciphertext_raises(self, crypto):
        import pytest
        with pytest.raises(Exception):
            crypto.decrypt("AES:!!invalid-base64!!")

    def test_different_keys_produce_different_ciphertexts(self, test_key):
        crypto1 = CryptoUtils(test_key)
        other_key = bytes(b ^ 0xFF for b in test_key)
        crypto2 = CryptoUtils(other_key)
        c1 = crypto1.encrypt("test")
        assert c1 != crypto2.encrypt("test")

    def test_wrong_key_decrypt_fails(self, test_key):
        crypto1 = CryptoUtils(test_key)
        ciphertext = crypto1.encrypt("secret")
        other_key = bytes(b ^ 0xFF for b in test_key)
        crypto2 = CryptoUtils(other_key)
        import pytest
        with pytest.raises(Exception):
            crypto2.decrypt(ciphertext)

    def test_encrypt_special_characters(self, crypto):
        special = "p@$$w0rd!#%^&*()_+-={}[]|\:;\"'<>,.?/~\n\t"
        ciphertext = crypto.encrypt(special)
        assert crypto.decrypt(ciphertext) == special

    def test_decrypt_cbc_兼容旧密文(self, crypto):
        """使用 AES-CBC 手动加密一段文本，然后用 decrypt 解密"""
        import base64
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        iv = b"\x00" * 16
        padder = padding.PKCS7(128).padder()
        padded = padder.update(b"cbc_test_value") + padder.finalize()
        cipher = Cipher(algorithms.AES(crypto._key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ct = encryptor.update(padded) + encryptor.finalize()
        ciphertext = f"AES-CBC:{base64.b64encode(iv + ct).decode()}"
        assert crypto.decrypt(ciphertext) == "cbc_test_value"

    def test_decrypt_cbc_无效密文报错(self, crypto):
        import pytest
        with pytest.raises(Exception):
            crypto.decrypt("AES-CBC:!!invalid!!")
