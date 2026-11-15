"""家长客服 P0：会话账本 parent_service_threads。

Revision ID: c0ffee000043
Revises: c0ffee000042
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000043"
down_revision: str | None = "c0ffee000042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "parent_service_threads" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "parent_service_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("anon_key", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("risk_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parent_service_threads_parent_id", "parent_service_threads", ["parent_id"])
    op.create_index("ix_parent_service_threads_anon_key", "parent_service_threads", ["anon_key"])
    op.create_index("ix_parent_service_threads_status", "parent_service_threads", ["status"])


def downgrade() -> None:
    op.drop_index("ix_parent_service_threads_status", table_name="parent_service_threads")
    op.drop_index("ix_parent_service_threads_anon_key", table_name="parent_service_threads")
    op.drop_index("ix_parent_service_threads_parent_id", table_name="parent_service_threads")
    op.drop_table("parent_service_threads")
