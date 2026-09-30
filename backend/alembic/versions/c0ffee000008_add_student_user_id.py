"""M5 客户端：Student 增加 student_user_id 字段（学员本人登录账号绑定）

- student_user_id: FK users.id, nullable
- 家长账号通过 parent_user_id 绑定（已有），学员账号通过 student_user_id 绑定
- 一个学员可同时被家长账号和学员账号访问
- 唯一约束：一个学员账号只能绑定一个学员（student_user_id 唯一）

Revision ID: c0ffee000008
Revises: c0ffee000007
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000008"
down_revision: str | None = "c0ffee000007"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 学员本人登录账号（学员角色 user.id，可空；一个学员账号只能绑定一个学员）
    op.add_column(
        "students",
        sa.Column(
            "student_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            nullable=True,
            index=True,
            unique=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("students", "student_user_id")
