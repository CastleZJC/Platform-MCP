"""exceptions 单元测试 — 异常层级与错误码"""

from platform_mcp.common.exceptions import (
    BaseError, BusinessError, AuthError, DataSourceError, SkillError, PathSecurityError,
)


class TestExceptions:
    def test_base_error_defaults(self):
        e = BaseError("test")
        assert e.message == "test"
        assert e.error_code == 15001

    def test_business_error_custom_code(self):
        e = BusinessError("biz error", error_code=20001)
        assert e.error_code == 20001

    def test_auth_error_default_code(self):
        e = AuthError()
        assert e.error_code == 11001
        assert e.message == "认证失败"

    def test_auth_error_custom_message(self):
        e = AuthError("未登录")
        assert e.message == "未登录"
        assert e.error_code == 11001

    def test_datasource_error(self):
        e = DataSourceError("数据源不存在")
        assert e.error_code == 12001

    def test_skill_error(self):
        e = SkillError("Skill 异常")
        assert e.error_code == 10001

    def test_path_security_error(self):
        e = PathSecurityError()
        assert e.error_code == 16001
        assert e.message == "路径不安全"

    def test_inheritance_chain(self):
        assert issubclass(AuthError, BaseError)
        assert issubclass(DataSourceError, BaseError)
        assert issubclass(SkillError, BaseError)
        assert issubclass(PathSecurityError, BaseError)
        assert issubclass(BusinessError, BaseError)

    def test_can_be_caught_as_base_error(self):
        try:
            raise AuthError("test")
        except BaseError as e:
            assert e.error_code == 11001
