"""题库套卷增加年月筛选字段

Revision ID: c00000000003
Revises: c00000000002
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c00000000003"
down_revision: str | None = "c00000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("question_bank_sets", sa.Column("exam_month", sa.String(length=7), nullable=True))
    op.create_index(
        "ix_question_bank_sets_exam_month",
        "question_bank_sets",
        ["exam_month"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_question_bank_sets_exam_month", table_name="question_bank_sets")
    op.drop_column("question_bank_sets", "exam_month")
