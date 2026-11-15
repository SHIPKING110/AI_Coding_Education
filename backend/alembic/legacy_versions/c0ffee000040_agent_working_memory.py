"""跨会话工作记忆：agent_working_memories。

Revision ID: c0ffee000040
Revises: c0ffee000039
Create Date: 2026-10-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000040"
down_revision: str | None = "c0ffee000039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "agent_working_memories" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "agent_working_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_working_memories_owner_id", "agent_working_memories", ["owner_id"])
    op.create_index("ix_agent_working_memories_agent_id", "agent_working_memories", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_working_memories_agent_id", table_name="agent_working_memories")
    op.drop_index("ix_agent_working_memories_owner_id", table_name="agent_working_memories")
    op.drop_table("agent_working_memories")
