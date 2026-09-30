# -*- coding: utf-8 -*-
"""数据库引擎与会话管理（SQLAlchemy 2.0）。"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# 会话时区钉 UTC（保险层）：即使存在残余的 server_default / DB 端 NOW()，
# 也返回 UTC 而非 MySQL 宿主机本地时间（+08:00）。
# init_command 仅对 PyMySQL 生效，非 MySQL 方言（如测试用 SQLite）不注入。
_MYSQL_CONNECT_ARGS = (
    {"init_command": "SET SESSION time_zone = '+00:00'"}
    if settings.database_url.startswith("mysql")
    else {}
)

# MySQL（PyMySQL）：pool_pre_ping 防长连接假死，pool_recycle 定时回收
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    future=True,
    connect_args=_MYSQL_CONNECT_ARGS,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """ORM 声明基类，所有模型均继承它。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：yield 一个数据库会话，请求结束（无论成败）关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
