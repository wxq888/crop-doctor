# -*- coding: utf-8 -*-
"""安全工具：bcrypt 密码哈希 与 JWT 签发/校验。

说明：JWT 签名密钥复用 ``APP_SECRET_KEY``，不新增环境变量。
"""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# passlib 1.7.4 + bcrypt 4.x：显式关闭 72 字节截断报错（保留 bcrypt 默认截断行为）
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=False,
)


def hash_password(password: str) -> str:
    """生成 bcrypt 密码哈希。"""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配；哈希格式异常时返回 False。"""
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(
    subject: str | int,
    role: str,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    """签发 JWT。

    Args:
        subject: 用户 id（写入 ``sub``）。
        role: 用户角色（写入 ``role``）。
        expires_minutes: 自定义有效期（分钟），缺省读配置。

    Returns:
        ``(token, expires_in_seconds)``。
    """
    minutes = expires_minutes if expires_minutes is not None else settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    token = jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)
    return token, minutes * 60


def decode_access_token(token: str) -> dict:
    """校验并解析 JWT；失败抛出 ``jose.JWTError``。"""
    return jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])


__all__ = [
    "JWTError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
]
