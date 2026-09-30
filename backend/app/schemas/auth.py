# -*- coding: utf-8 -*-
"""认证相关 Schema。"""
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class RegisterRequest(BaseModel):
    """注册入参。"""

    username: str = Field(min_length=3, max_length=50, description="登录名")
    password: str = Field(min_length=6, max_length=72, description="密码（bcrypt 上限 72 字节）")
    nickname: str | None = Field(default=None, max_length=50, description="昵称，缺省取用户名")
    phone: str | None = Field(default=None, max_length=20, description="手机号（预留）")


class LoginRequest(BaseModel):
    """登录入参。"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    """用户信息出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    role: str
    avatar: str | None = None
    phone: str | None = None
    status: int
    created_at: UtcDatetime


class RegisterOut(BaseModel):
    """注册成功出参。"""

    id: int
    username: str
    role: str


class TokenOut(BaseModel):
    """登录成功出参。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProfileUpdateRequest(BaseModel):
    """资料更新入参。"""

    nickname: str | None = Field(default=None, max_length=50)
    avatar: str | None = Field(default=None, max_length=255)


class PasswordChangeRequest(BaseModel):
    """改密入参。"""

    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "UserOut",
    "RegisterOut",
    "TokenOut",
    "ProfileUpdateRequest",
    "PasswordChangeRequest",
]
