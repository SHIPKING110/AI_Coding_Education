"""Add question_bank_ai_tasks table for persistent AI batch task progress.

Revision ID: c00000000006
Revises: c00000000005
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c00000000006"
down_revision: str | None = "c00000000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "question_bank_ai_tasks" in inspector.get_table_names():
        return
    op.create_table(
        "question_bank_ai_tasks",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_question_bank_ai_tasks_user_id", "question_bank_ai_tasks", ["user_id"])
    op.create_index("ix_question_bank_ai_tasks_kind", "question_bank_ai_tasks", ["kind"])
    op.create_index("ix_question_bank_ai_tasks_status", "question_bank_ai_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_question_bank_ai_tasks_status", table_name="question_bank_ai_tasks")
    op.drop_index("ix_question_bank_ai_tasks_kind", table_name="question_bank_ai_tasks")
    op.drop_index("ix_question_bank_ai_tasks_user_id", table_name="question_bank_ai_tasks")
    op.drop_table("question_bank_ai_tasks")
