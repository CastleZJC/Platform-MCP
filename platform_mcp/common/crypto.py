"""加解密工具类 — AES-256-GCM 为主，CBC 兼容解密历史密文"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoUtils:
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
            return self._decrypt_gcm(ciphertext[len(self.PREFIX_GCM) :])
        elif ciphertext.startswith(self.PREFIX_CBC):
            return self._decrypt_cbc(ciphertext[len(self.PREFIX_CBC) :])
        return ciphertext

    def _decrypt_gcm(self, encoded: str) -> str:
        raw = base64.b64decode(encoded)
        nonce, ciphertext = raw[:12], raw[12:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")

    def _decrypt_cbc(self, encoded: str) -> str:
        raw = base64.b64decode(encoded)
        iv, ciphertext = raw[:16], raw[16:]
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded) + unpadder.finalize()
        return data.decode("utf-8")

    @staticmethod
    def generate_key() -> bytes:
        """生成 32 字节随机密钥"""
        return os.urandom(32)
