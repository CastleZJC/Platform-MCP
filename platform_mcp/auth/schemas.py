"""认证 Pydantic Schema"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    nickname: str | None
    email: str | None = None
    role_code: str
    status: int
