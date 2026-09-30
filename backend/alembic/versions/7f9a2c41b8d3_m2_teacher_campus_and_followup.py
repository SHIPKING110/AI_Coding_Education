"""M2 补强：users.campus（多校区标签）+ students 催缴跟进状态

Revision ID: 7f9a2c41b8d3
Revises: 42f77290cf0f
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f9a2c41b8d3"
down_revision: str | None = "42f77290cf0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 教师所属校区标签（多校区，如 一校/二校/三校，可自定义）
    op.add_column("users", sa.Column("campus", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_users_campus"), "users", ["campus"], unique=False)

    # 催缴跟进状态（课时 <= 10 自动进入待跟进；续费/停课后保留记录）
    op.add_column(
        "students",
        sa.Column(
            "follow_up_status",
            sa.Enum(
                "PENDING",
                "RENEWED",
                "STOPPED",
                name="followupstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.create_index(
        op.f("ix_students_follow_up_status"), "students", ["follow_up_status"], unique=False
    )
    op.add_column("students", sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("students", sa.Column("follow_up_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "follow_up_note")
    op.drop_column("students", "follow_up_at")
    op.drop_index(op.f("ix_students_follow_up_status"), table_name="students")
    op.drop_column("students", "follow_up_status")
    op.drop_index(op.f("ix_users_campus"), table_name="users")
    op.drop_column("users", "campus")
