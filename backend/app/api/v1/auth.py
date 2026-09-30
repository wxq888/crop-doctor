# -*- coding: utf-8 -*-
"""认证接口：注册 / 登录 / 资料 / 改密。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import (
    CODE_BAD_CREDENTIALS,
    CODE_OLD_PASSWORD_WRONG,
    CODE_USERNAME_EXISTS,
    BusinessError,
)
from app.core.response import ok
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RegisterOut,
    RegisterRequest,
    TokenOut,
    UserOut,
)

router = APIRouter()


@router.post("/register", summary="用户注册")
def register(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """注册普通用户；用户名唯一，密码 bcrypt 哈希，默认 role=user。"""
    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists is not None:
        raise BusinessError(CODE_USERNAME_EXISTS, "用户名已存在", http_status=400)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname or payload.username,
        role="user",
        phone=payload.phone,
        status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(RegisterOut(id=user.id, username=user.username, role=user.role))


@router.post("/login", summary="用户登录")
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """校验用户名/密码并签发 JWT。"""
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or user.status != 1 or not verify_password(payload.password, user.password_hash):
        raise BusinessError(CODE_BAD_CREDENTIALS, "用户名或密码错误", http_status=401)

    token, expires_in = create_access_token(user.id, user.role)
    return ok(
        TokenOut(
            access_token=token,
            expires_in=expires_in,
            user=UserOut.model_validate(user),
        )
    )


@router.get("/profile", summary="获取当前用户资料")
def get_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """返回当前登录用户信息。"""
    return ok(UserOut.model_validate(current_user))


@router.put("/profile", summary="更新当前用户资料")
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """更新昵称 / 头像。"""
    if payload.nickname is not None:
        current_user.nickname = payload.nickname
    if payload.avatar is not None:
        current_user.avatar = payload.avatar
    db.commit()
    db.refresh(current_user)
    return ok(UserOut.model_validate(current_user))


@router.put("/password", summary="修改密码")
def change_password(
    payload: PasswordChangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """校验原密码后修改为新密码（旧密码随即失效）。"""
    if not verify_password(payload.old_password, current_user.password_hash):
        raise BusinessError(CODE_OLD_PASSWORD_WRONG, "原密码错误", http_status=400)
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return ok(None)
