# -*- coding: utf-8 -*-
r"""一次性脚本：创建（或重置）首个管理员账号。

PC 管理端不提供管理员自助注册，故用本脚本预置管理员。

用法（在仓库根执行）::

    .venv\Scripts\python.exe scripts\seed_admin.py --username admin --password "Admin@123456" --nickname 管理员

说明：若同名用户已存在，则把其 ``role`` 置为 admin 并重置密码。
"""
import argparse
import sys
from pathlib import Path

# 把 backend 目录加入 sys.path，保证可 import app 包
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> int:
    """解析参数并创建/更新管理员账号。"""
    parser = argparse.ArgumentParser(description="创建或重置管理员账号")
    parser.add_argument("--username", required=True, help="管理员登录名")
    parser.add_argument("--password", required=True, help="管理员密码（明文，脚本内哈希）")
    parser.add_argument("--nickname", default=None, help="昵称，缺省取用户名")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            user = User(
                username=args.username,
                password_hash=hash_password(args.password),
                nickname=args.nickname or args.username,
                role="admin",
                status=1,
            )
            db.add(user)
            action = "创建"
        else:
            user.password_hash = hash_password(args.password)
            user.role = "admin"
            if args.nickname:
                user.nickname = args.nickname
            action = "更新"
        db.commit()
        db.refresh(user)
        print(f"已{action}管理员：id={user.id} username={user.username} role={user.role}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
