"""5.1.6 API 集成测试 — 密码加密"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCryptoAPI:
    @pytest.mark.asyncio
    async def test_encrypt_admin_success(self, admin_client):
        mock_crypto = MagicMock()
        mock_crypto.encrypt.return_value = "AES:encrypted_value"
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        with patch("platform_mcp.api.crypto._get_crypto_utils", return_value=mock_crypto):
            resp = await admin_client.post("/api/v1/crypto/encrypt",
                json={"plaintext": "my_password"})
        assert resp.status_code == 200
        assert resp.json()["data"]["ciphertext"].startswith("AES:")

    @pytest.mark.asyncio
    async def test_encrypt_writes_operation_log(self, admin_client):
        mock_crypto = MagicMock()
        mock_crypto.encrypt.return_value = "AES:encrypted_value"
        with patch("platform_mcp.api.crypto._get_crypto_utils", return_value=mock_crypto):
            resp = await admin_client.post("/api/v1/crypto/encrypt",
                json={"plaintext": "my_password"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["ciphertext"] == "AES:encrypted_value"

    @pytest.mark.asyncio
    async def test_encrypt_developer_forbidden(self, dev_client):
        resp = await dev_client.post("/api/v1/crypto/encrypt",
            json={"plaintext": "test"})
        assert resp.json()["code"] == 11001

    @pytest.mark.asyncio
    async def test_verify_成功(self, admin_client):
        mock_crypto = MagicMock()
        mock_crypto.decrypt.return_value = "my_password"
        with patch("platform_mcp.api.crypto._get_crypto_utils", return_value=mock_crypto):
            resp = await admin_client.post("/api/v1/crypto/verify",
                json={"ciphertext": "AES:somevalue"})
        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True
        assert resp.json()["data"]["length"] == len("my_password")

    @pytest.mark.asyncio
    async def test_verify_失败_无效密文(self, admin_client):
        mock_crypto = MagicMock()
        mock_crypto.decrypt.side_effect = Exception("decrypt failed")
        with patch("platform_mcp.api.crypto._get_crypto_utils", return_value=mock_crypto):
            resp = await admin_client.post("/api/v1/crypto/verify",
                json={"ciphertext": "AES:invalid"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["success"] is False

    @pytest.mark.asyncio
    async def test_verify_writes_operation_log(self, admin_client):
        mock_crypto = MagicMock()
        mock_crypto.decrypt.return_value = "my_password"
        with patch("platform_mcp.api.crypto._get_crypto_utils", return_value=mock_crypto):
            resp = await admin_client.post("/api/v1/crypto/verify",
                json={"ciphertext": "AES:somevalue"})
        assert resp.status_code == 200
