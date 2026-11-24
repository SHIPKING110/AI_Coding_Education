# ruff: noqa: E501
"""题库用户标记（收藏/错题本）/聚合练习表

Revision ID: c00000000001
Revises: c00000000000
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c00000000001"
down_revision: tuple[str, str] = ("c00000000000", "c0ffee000060")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("question_bank_user_marks"):
        op.create_table(
            "question_bank_user_marks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("student_id", sa.Uuid(), nullable=True),
            sa.Column("question_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["question_id"], ["question_bank_questions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "student_id", "question_id", "kind"),
        )
        op.create_index(op.f("ix_question_bank_user_marks_kind"), "question_bank_user_marks", ["kind"], unique=False)
        op.create_index(
            op.f("ix_question_bank_user_marks_user_id"),
            "question_bank_user_marks",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    if _has("question_bank_user_marks"):
        op.drop_table("question_bank_user_marks")
