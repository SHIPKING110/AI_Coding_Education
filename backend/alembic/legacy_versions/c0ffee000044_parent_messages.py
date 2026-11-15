"""家长客服 P0：消息账本 parent_service_messages（含 tokens + retrieval_diag）。

Revision ID: c0ffee000044
Revises: c0ffee000043
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000044"
down_revision: str | None = "c0ffee000043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "parent_service_messages" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "parent_service_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("retrieval_diag", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["parent_service_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parent_service_messages_thread_id", "parent_service_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_parent_service_messages_thread_id", table_name="parent_service_messages")
    op.drop_table("parent_service_messages")
