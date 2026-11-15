"""create users table

Revision ID: 0001
Revises:
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

roles = sa.Enum("admin", "staff", "teacher", "parent", "student", name="role")
statuses = sa.Enum("active", "disabled", name="userstatus")


def upgrade() -> None:
    roles.create(op.get_bind(), checkfirst=True)
    statuses.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False, index=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("phone", sa.String(20), nullable=True, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
    statuses.drop(op.get_bind(), checkfirst=True)
    roles.drop(op.get_bind(), checkfirst=True)
