"""API Key 双存储机制单元测试（P0-1）

覆盖：
- generate_api_key 同时写入 key_hash（SHA-256）和 key_encrypted（AES-GCM）
- validate_api_key 正确/错误/已撤销 key 校验
- get_full_key_by_user admin reveal 明文
- revoke_api_key 撤销
- regenerate_api_key 重置
- list_user_keys 列表
"""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from platform_mcp.auth.api_key_models import PmcpApiKey
from platform_mcp.auth.api_key_service import (
    KEY_PREFIX,
    _generate_raw_key,
    _hash_key,
    _key_prefix,
    generate_api_key,
    get_full_key_by_user,
    list_user_keys,
    regenerate_api_key,
    revoke_api_key,
    validate_api_key,
)


class TestKeyGenerationHelpers:
    """密钥生成辅助函数"""

    def test_generate_raw_key_has_pmcp_prefix(self):
        raw = _generate_raw_key()
        assert raw.startswith(KEY_PREFIX)
        assert len(raw) > len(KEY_PREFIX) + 20

    def test_generate_raw_key_unique(self):
        keys = {_generate_raw_key() for _ in range(20)}
        assert len(keys) == 20

    def test_hash_key_is_sha256_64chars(self):
        h = _hash_key("pmcp_test_key")
        assert len(h) == 64
        assert h == hashlib.sha256(b"pmcp_test_key").hexdigest()

    def test_hash_key_irreversible(self):
        raw = "pmcp_secret_xxx"
        h = _hash_key(raw)
        assert h != raw
        assert h != _hash_key(raw + " ")

    def test_key_prefix_first_10_chars(self):
        raw = "pmcp_abcdefghijklmnop"
        assert _key_prefix(raw) == "pmcp_abcde"


class TestGenerateApiKey:
    """generate_api_key 服务层测试"""

    @pytest.mark.asyncio
    async def test_generate_api_key_returns_pmcp_prefixed_raw(self, mock_db, crypto):
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            raw = await generate_api_key(mock_db, user_id=1, description="test")
        assert raw.startswith(KEY_PREFIX)
        assert len(raw) > 30

    @pytest.mark.asyncio
    async def test_generate_api_key_writes_both_hash_and_encrypted(self, mock_db, crypto):
        """核心测试：双存储机制 — hash + encrypted 必须同时写入"""
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            raw = await generate_api_key(mock_db, user_id=1, description="test")

        mock_db.add.assert_called_once()
        record = mock_db.add.call_args.args[0]
        assert isinstance(record, PmcpApiKey)
        assert record.key_hash
        assert record.key_encrypted
        assert record.key_hash != record.key_encrypted

    @pytest.mark.asyncio
    async def test_generate_api_key_hash_is_sha256_of_raw(self, mock_db, crypto):
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            raw = await generate_api_key(mock_db, user_id=1)
        record = mock_db.add.call_args.args[0]
        assert record.key_hash == hashlib.sha256(raw.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_generate_api_key_encrypted_is_aes_reversible(self, mock_db, crypto):
        """核心测试：key_encrypted 是可逆加密，可解密还原 raw_key"""
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            raw = await generate_api_key(mock_db, user_id=1)
        record = mock_db.add.call_args.args[0]
        decrypted = crypto.decrypt(record.key_encrypted)
        assert decrypted == raw

    @pytest.mark.asyncio
    async def test_generate_api_key_writes_key_prefix(self, mock_db, crypto):
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            raw = await generate_api_key(mock_db, user_id=1)
        record = mock_db.add.call_args.args[0]
        assert record.key_prefix == raw[:10]

    @pytest.mark.asyncio
    async def test_generate_api_key_default_status_active(self, mock_db, crypto):
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            await generate_api_key(mock_db, user_id=1)
        record = mock_db.add.call_args.args[0]
        assert record.status == 1

    @pytest.mark.asyncio
    async def test_generate_api_key_calls_flush(self, mock_db, crypto):
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            await generate_api_key(mock_db, user_id=1)
        mock_db.flush.assert_awaited_once()


class TestValidateApiKey:
    """validate_api_key 校验逻辑测试"""

    @pytest.mark.asyncio
    async def test_validate_api_key_no_prefix_returns_none(self, mock_db):
        result = await validate_api_key(mock_db, "invalid_key_no_prefix")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_api_key_empty_string_returns_none(self, mock_db):
        result = await validate_api_key(mock_db, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_api_key_correct_key_returns_user_info(self, mock_db):
        """校验成功：返回 user_id/username/nickname/role_code"""
        raw = "pmcp_valid_test_key_xxx_12345"
        api_key_record = MagicMock(user_id=1, status=1, last_used_at=None)
        user_record = MagicMock(id=1, username="admin", nickname="admin", status=1)
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=api_key_record)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=user_record)),
                MagicMock(scalar_one_or_none=MagicMock(return_value="admin")),
            ]
        )
        result = await validate_api_key(mock_db, raw)
        assert result == {
            "user_id": 1,
            "username": "admin",
            "nickname": "admin",
            "role_code": "admin",
        }

    @pytest.mark.asyncio
    async def test_validate_api_key_hash_mismatch_returns_none(self, mock_db):
        """hash 不匹配：DB 未找到对应记录"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        result = await validate_api_key(mock_db, "pmcp_unknown_key_yyy")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_api_key_revoked_key_status_0_returns_none(self, mock_db):
        """status=0 的 key 不在查询条件内（WHERE status=1），不会被命中"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        result = await validate_api_key(mock_db, "pmcp_revoked_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_api_key_user_disabled_returns_none(self, mock_db):
        """user.status=0 时不返回"""
        api_key_record = MagicMock(user_id=1, status=1)
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=api_key_record)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            ]
        )
        result = await validate_api_key(mock_db, "pmcp_test_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_api_key_no_role_defaults_developer(self, mock_db):
        """无角色绑定时默认 developer"""
        api_key_record = MagicMock(user_id=1, status=1)
        user_record = MagicMock(id=1, username="dev", nickname="dev", status=1)
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=api_key_record)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=user_record)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            ]
        )
        result = await validate_api_key(mock_db, "pmcp_test_key")
        assert result["role_code"] == "developer"


class TestRevealApiKey:
    """get_full_key_by_user admin reveal 测试"""

    @staticmethod
    def _mock_execute_with_scalars_first(record):
        """构建 mock execute 返回值，支持 result.scalars().first() 链式调用"""
        result = MagicMock()
        result.scalars.return_value.first.return_value = record
        return AsyncMock(return_value=result)

    @pytest.mark.asyncio
    async def test_reveal_with_encrypted_returns_plaintext(self, mock_db, crypto):
        raw = "pmcp_reveal_target_key"
        encrypted = crypto.encrypt(raw)
        key_record = MagicMock(key_encrypted=encrypted, status=1)
        mock_db.execute = self._mock_execute_with_scalars_first(key_record)
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            result = await get_full_key_by_user(mock_db, user_id=1)
        assert result == raw

    @pytest.mark.asyncio
    async def test_reveal_no_active_key_returns_none(self, mock_db):
        mock_db.execute = self._mock_execute_with_scalars_first(None)
        result = await get_full_key_by_user(mock_db, user_id=999)
        assert result is None

    @pytest.mark.asyncio
    async def test_reveal_hash_only_historical_key_returns_none(self, mock_db):
        """hash-only 历史 key（key_encrypted is None）reveal 返回 None"""
        key_record = MagicMock(key_encrypted=None, status=1)
        mock_db.execute = self._mock_execute_with_scalars_first(key_record)
        result = await get_full_key_by_user(mock_db, user_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_reveal_takes_latest_by_inserted_at_desc(self, mock_db, crypto):
        """按插入时间倒序，取最新活跃 key"""
        raw_latest = "pmcp_latest_key"
        encrypted_latest = crypto.encrypt(raw_latest)
        latest = MagicMock(key_encrypted=encrypted_latest)
        # service 只调用 first()，所以只需配置 first 返回 latest
        mock_db.execute = self._mock_execute_with_scalars_first(latest)
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            result = await get_full_key_by_user(mock_db, user_id=1)
        assert result == raw_latest


class TestRevokeApiKey:
    """revoke_api_key 撤销测试"""

    @pytest.mark.asyncio
    async def test_revoke_own_key_success(self, mock_db):
        key_record = MagicMock(status=1)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=key_record))
        )
        ok = await revoke_api_key(mock_db, key_id=1, user_id=1)
        assert ok is True
        assert key_record.status == 0
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_revoke_others_key_fails(self, mock_db):
        """user_id 不匹配，查询返回 None"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        ok = await revoke_api_key(mock_db, key_id=1, user_id=999)
        assert ok is False

    @pytest.mark.asyncio
    async def test_revoke_already_revoked_fails(self, mock_db):
        """status != 1 不在查询条件内"""
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        ok = await revoke_api_key(mock_db, key_id=1, user_id=1)
        assert ok is False


class TestRegenerateApiKey:
    """regenerate_api_key 重置测试"""

    @pytest.mark.asyncio
    async def test_regenerate_revokes_old_generates_new(self, mock_db, crypto):
        old_record = MagicMock(status=1, description="old key")
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=old_record))
        )
        with patch("platform_mcp.auth.api_key_service._get_crypto_utils", return_value=crypto):
            new_raw = await regenerate_api_key(mock_db, key_id=1, user_id=1)
        assert new_raw is not None
        assert old_record.status == 0
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_regenerate_key_not_exist_returns_none(self, mock_db):
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        result = await regenerate_api_key(mock_db, key_id=999, user_id=1)
        assert result is None


class TestListUserKeys:
    """list_user_keys 列表测试"""

    @staticmethod
    def _mock_execute_with_scalars_all(keys):
        """构建 mock execute 返回值，支持 result.scalars().all() 链式调用"""
        result = MagicMock()
        result.scalars.return_value.all.return_value = keys
        return AsyncMock(return_value=result)

    @pytest.mark.asyncio
    async def test_list_user_keys_excludes_full_key(self, mock_db):
        """列表返回 key_prefix（非完整 key），无 raw_key"""
        key1 = MagicMock(
            id=1, key_prefix="pmcp_abcde", description="key1", status=1,
            last_used_at=None, expires_at=None, inserted_at=None,
        )
        key2 = MagicMock(
            id=2, key_prefix="pmcp_efgh", description="key2", status=0,
            last_used_at=None, expires_at=None, inserted_at=None,
        )
        mock_db.execute = self._mock_execute_with_scalars_all([key1, key2])
        result = await list_user_keys(mock_db, user_id=1)
        assert len(result) == 2
        assert "key" not in result[0]
        assert "key_prefix" in result[0]

    @pytest.mark.asyncio
    async def test_list_user_keys_empty(self, mock_db):
        mock_db.execute = self._mock_execute_with_scalars_all([])
        result = await list_user_keys(mock_db, user_id=999)
        assert result == []
