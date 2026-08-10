"""auth.service 单元测试 — hash_password/verify_password"""

from platform_mcp.auth.service import hash_password, verify_password


class TestPasswordHash:
    def test_hash_password_returns_string(self):
        h = hash_password("test123")
        assert isinstance(h, str)
        assert h.startswith("$2b$")

    def test_verify_correct_password(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("mypassword")
        assert verify_password("wrong", h) is False

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("pass1")
        h2 = hash_password("pass2")
        assert h1 != h2

    def test_same_password_different_hashes_bcrypt(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        assert verify_password("same", h1)
        assert verify_password("same", h2)
