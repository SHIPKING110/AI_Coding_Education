"""Repair attempt columns omitted from the production c00000000004 schema.

Revision ID: c00000000005
Revises: c00000000004
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c00000000005"
down_revision: str | None = "c00000000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("question_bank_attempts")}
    if "user_id" not in columns:
        op.add_column("question_bank_attempts", sa.Column("user_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_question_bank_attempts_user_id_users",
            "question_bank_attempts",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if "student_id" in columns and next(
        column for column in inspector.get_columns("question_bank_attempts") if column["name"] == "student_id"
    )["nullable"] is False:
        op.alter_column("question_bank_attempts", "student_id", existing_type=sa.UUID(), nullable=True)
    if "kind" not in columns:
        op.add_column(
            "question_bank_attempts",
            sa.Column("kind", sa.String(length=24), nullable=False, server_default="set_practice"),
        )
    if "paper_title" not in columns:
        op.add_column("question_bank_attempts", sa.Column("paper_title", sa.String(length=200), nullable=True))
    if "paper_meta" not in columns:
        op.add_column("question_bank_attempts", sa.Column("paper_meta", sa.JSON(), nullable=True))
    if "question_results" not in columns:
        op.add_column(
            "question_bank_attempts",
            sa.Column("question_results", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        )
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("question_bank_attempts")}
    if "ix_question_bank_attempts_user_id" not in indexes:
        op.create_index("ix_question_bank_attempts_user_id", "question_bank_attempts", ["user_id"])
    if "ix_question_bank_attempts_kind" not in indexes:
        op.create_index("ix_question_bank_attempts_kind", "question_bank_attempts", ["kind"])
    op.execute(
        """
        UPDATE question_bank_attempts a
           SET user_id = COALESCE(s.student_user_id, s.parent_user_id)
          FROM students s
         WHERE a.student_id = s.id AND a.user_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_question_bank_attempts_kind", table_name="question_bank_attempts")
    op.drop_index("ix_question_bank_attempts_user_id", table_name="question_bank_attempts")
    op.drop_column("question_bank_attempts", "question_results")
    op.drop_column("question_bank_attempts", "paper_meta")
    op.drop_column("question_bank_attempts", "paper_title")
    op.drop_column("question_bank_attempts", "kind")
    op.drop_constraint("fk_question_bank_attempts_user_id_users", "question_bank_attempts", type_="foreignkey")
    op.drop_column("question_bank_attempts", "user_id")
    op.alter_column("question_bank_attempts", "student_id", existing_type=sa.UUID(), nullable=False)
