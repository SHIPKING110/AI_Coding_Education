"""生产首个管理员账号初始化。

用法（容器内）：
    docker compose exec backend python scripts/seed_admin.py
凭据来源（按优先级）：命令行参数 > 环境变量 SEED_ADMIN_*。
已存在同名用户则跳过（幂等，可重复执行）。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.crud import user as user_crud  # noqa: E402
from app.models.user import Role  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="创建首个管理员账号（幂等）")
    parser.add_argument("--username", default=os.getenv("SEED_ADMIN_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("SEED_ADMIN_PASSWORD", ""))
    parser.add_argument("--name", default=os.getenv("SEED_ADMIN_NAME", "管理员"))
    args = parser.parse_args()
    if not args.password:
        print("拒绝执行：请通过 --password 或 SEED_ADMIN_PASSWORD 提供密码", file=sys.stderr)
        sys.exit(2)
    db = SessionLocal()
    try:
        existing = user_crud.get_by_username(db, args.username)
        if existing is not None:
            print(f"跳过：用户 {args.username} 已存在")
            return
        user = user_crud.create_user(
            db, role=Role.ADMIN, username=args.username, password=args.password, name=args.name
        )
        print(f"已创建管理员：{user.username}（{user.name}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
