# -*- coding: utf-8 -*-
"""公共依赖注入（FastAPI ``Depends``）。"""
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import CODE_FORBIDDEN, CODE_UNAUTHORIZED, BusinessError
from app.core.security import decode_access_token
from app.models.user import User

# auto_error=False：无 token 时不由框架抛 403，改由业务统一返回 1003
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """解析 Bearer token → 校验 JWT → 查 users → 校验 status。

    任一环节失败均抛 ``1003``（未登录 / Token 无效或过期）。
    """
    if credentials is None or not credentials.credentials:
        raise BusinessError(CODE_UNAUTHORIZED, "未登录或 Token 无效", http_status=401)
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise BusinessError(CODE_UNAUTHORIZED, "未登录或 Token 无效", http_status=401)

    user = db.get(User, user_id)
    if user is None or user.status != 1:
        raise BusinessError(CODE_UNAUTHORIZED, "未登录或 Token 无效", http_status=401)
    return user


def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """要求管理员角色，否则抛 ``1004``。"""
    if current_user.role != "admin":
        raise BusinessError(CODE_FORBIDDEN, "权限不足（需管理员）", http_status=403)
    return current_user


__all__ = ["bearer_scheme", "get_current_user", "get_current_admin"]
