"""自定义异常体系"""


class BaseError(Exception):
    def __init__(self, message: str, error_code: int = 15001):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class BusinessError(BaseError):
    def __init__(self, message: str, error_code: int = 15001):
        super().__init__(message, error_code)


class AuthError(BaseError):
    def __init__(self, message: str = "认证失败", error_code: int = 11001):
        super().__init__(message, error_code)


class DataSourceError(BaseError):
    def __init__(self, message: str, error_code: int = 12001):
        super().__init__(message, error_code)


class SkillError(BaseError):
    def __init__(self, message: str, error_code: int = 10001):
        super().__init__(message, error_code)


class PathSecurityError(BaseError):
    def __init__(self, message: str = "路径不安全", error_code: int = 16001):
        super().__init__(message, error_code)
