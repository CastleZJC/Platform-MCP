"""skills.server.transfer 单元测试 — BUG20260814163941（BUG-3/5）

覆盖：transfer_id 校验、文件名安全、stage_path 越界拒绝、
任务目录隔离清理、TTL 兜底、防误删铁律。
"""

import os
import time
import uuid
from unittest.mock import patch

import pytest

from platform_mcp.common.exceptions import PathSecurityError
from platform_mcp.skills.server import transfer


@pytest.fixture
def exchange(tmp_path):
    """隔离的中转目录：patch 配置 + 重置缓存，测试后恢复"""
    exchange_dir = tmp_path / "exchange"
    transfer.reset_exchange_dir_cache()
    with patch("platform_mcp.config.get_settings") as gs:
        gs.return_value.datasource.sftp_exchange_dir = str(exchange_dir)
        base = transfer.get_exchange_dir()
        yield base
    transfer.reset_exchange_dir_cache()


class TestTransferIdValidation:
    def test_valid_uuid4_accepted(self):
        assert transfer.is_valid_transfer_id(str(uuid.uuid4())) is True

    def test_non_uuid_rejected(self):
        for bad in ("", "abc", "../../etc", "not-a-uuid", str(uuid.uuid1())):
            assert transfer.is_valid_transfer_id(bad) is False

    def test_uppercase_rejected(self):
        assert transfer.is_valid_transfer_id(str(uuid.uuid4()).upper()) is False

    def test_uppercase_variant_rejected(self):
        # uuid4 的 variant 位必须是 89ab；构造非法 variant
        good = str(uuid.uuid4())
        chars = list(good)
        chars[19] = "c"  # variant 段首位非法
        assert transfer.is_valid_transfer_id("".join(chars)) is False


class TestSafeFilename:
    def test_normal_filenames_accepted(self):
        for name in ("x.zip", "数据报表.xlsx", "pkg-2026.tar.gz", "a b.txt"):
            assert transfer.is_safe_filename(name) is True

    def test_traversal_rejected(self):
        for name in ("..", ".", "../x", "a/b", "a\\b", "x\x00y", "", "x" * 256):
            assert transfer.is_safe_filename(name) is False


class TestStagePath:
    def test_valid_path_under_exchange(self, exchange):
        tid = transfer.new_transfer_id()
        p = transfer.stage_path(tid, "x.zip")
        assert p.parent.name == tid
        assert p.parent.parent == exchange.resolve()

    def test_invalid_transfer_id_raises(self, exchange):
        with pytest.raises(PathSecurityError):
            transfer.stage_path("../evil", "x.zip")

    def test_unsafe_filename_raises(self, exchange):
        tid = transfer.new_transfer_id()
        with pytest.raises(PathSecurityError):
            transfer.stage_path(tid, "../escape.txt")
        with pytest.raises(PathSecurityError):
            transfer.stage_path(tid, "")

    def test_absolute_filename_rejected(self, exchange):
        # Windows 绝对路径含分隔符，直接被文件名校验拦截
        tid = transfer.new_transfer_id()
        with pytest.raises(PathSecurityError):
            transfer.stage_path(tid, "C:\\Windows\\evil.dll")


class TestCleanupIsolation:
    """BUG-5：多人同名文件互不干扰，各自清理各自的"""

    def test_cleanup_only_own_directory(self, exchange):
        tid_a, tid_b = transfer.new_transfer_id(), transfer.new_transfer_id()
        for tid in (tid_a, tid_b):
            d = exchange / tid
            d.mkdir()
            (d / "111.xlsx").write_bytes(b"A" if tid == tid_a else b"B")
        assert transfer.cleanup_transfer(tid_a) is True
        assert not (exchange / tid_a).exists()
        assert (exchange / tid_b / "111.xlsx").read_bytes() == b"B"  # B 的文件完好

    def test_cleanup_invalid_or_missing_returns_false(self, exchange):
        assert transfer.cleanup_transfer("../evil") is False
        assert transfer.cleanup_transfer(transfer.new_transfer_id()) is False

    def test_exchange_root_never_deleted(self, exchange):
        (exchange / transfer.new_transfer_id()).mkdir()
        transfer.cleanup_expired_transfers()
        assert exchange.exists()

    def test_non_uuid_entries_untouched(self, exchange):
        stray = exchange / "not-a-uuid"
        stray.mkdir()
        transfer.cleanup_expired_transfers()
        assert stray.exists()


class TestStagedDetection:
    def test_staged_path_detected(self, exchange):
        tid = transfer.new_transfer_id()
        staged = exchange / tid / "x.zip"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"x")
        assert transfer.staged_transfer_id(str(staged)) == tid

    def test_outside_path_not_detected(self, exchange, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_bytes(b"x")
        assert transfer.staged_transfer_id(str(f)) is None

    def test_maybe_cleanup_staged_only_removes_staged(self, exchange, tmp_path):
        tid = transfer.new_transfer_id()
        staged = exchange / tid / "x.zip"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"x")
        plain = tmp_path / "plain.txt"
        plain.write_bytes(b"x")
        transfer.maybe_cleanup_staged(str(staged))
        transfer.maybe_cleanup_staged(str(plain))
        assert not staged.parent.exists()
        assert plain.exists()


class TestTtlCleanup:
    def test_expired_directory_removed(self, exchange):
        tid = transfer.new_transfer_id()
        d = exchange / tid
        d.mkdir()
        (d / "x.zip").write_bytes(b"x")
        old = time.time() - transfer.TRANSFER_TTL_SECONDS - 60
        os.utime(d, (old, old))
        removed = transfer.cleanup_expired_transfers()
        assert removed == 1
        assert not d.exists()

    def test_fresh_directory_kept(self, exchange):
        tid = transfer.new_transfer_id()
        d = exchange / tid
        d.mkdir()
        (d / "x.zip").write_bytes(b"x")
        assert transfer.cleanup_expired_transfers() == 0
        assert d.exists()


class TestExchangeDirResolution:
    def test_configured_dir_used(self, tmp_path):
        transfer.reset_exchange_dir_cache()
        configured = tmp_path / "custom_exchange"
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.datasource.sftp_exchange_dir = str(configured)
            assert transfer.get_exchange_dir() == configured.resolve()
        transfer.reset_exchange_dir_cache()

    def test_default_dir_created_when_unconfigured(self, tmp_path):
        transfer.reset_exchange_dir_cache()
        with patch("platform_mcp.config.get_settings") as gs:
            gs.return_value.datasource.sftp_exchange_dir = ""
            base = transfer.get_exchange_dir()
            assert base.name == "sftp_exchange"
            assert base.exists()
        transfer.reset_exchange_dir_cache()
