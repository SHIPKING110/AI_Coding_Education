# ruff: noqa: E501
"""question bank（题库模块 P1：来源/套卷/题目/蓝图/练习记录）

Revision ID: b00000000000
Revises: a00000000000
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b00000000000"
down_revision: str | None = "a00000000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("question_bank_sources"):
        op.create_table(
            "question_bank_sources",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("storage_path", sa.String(length=500), nullable=False),
            sa.Column("file_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("uploaded_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_question_bank_sources_file_hash"), "question_bank_sources", ["file_hash"], unique=False)
        op.create_index(op.f("ix_question_bank_sources_status"), "question_bank_sources", ["status"], unique=False)
        op.create_index(op.f("ix_question_bank_sources_uploaded_by"), "question_bank_sources", ["uploaded_by"], unique=False)

    if not _has("question_bank_sets"):
        op.create_table(
            "question_bank_sets",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("institution", sa.String(length=120), nullable=True),
            sa.Column("exam_year", sa.Integer(), nullable=True),
            sa.Column("subject", sa.String(length=80), nullable=True),
            sa.Column("level", sa.String(length=40), nullable=True),
            sa.Column("total_score", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("import_meta", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["source_id"], ["question_bank_sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id"),
        )
        for col in ("source_id", "institution", "exam_year", "subject", "level", "status"):
            op.create_index(op.f(f"ix_question_bank_sets_{col}"), "question_bank_sets", [col], unique=False)

    if not _has("question_bank_questions"):
        op.create_table(
            "question_bank_questions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("bank_set_id", sa.Uuid(), nullable=False),
            sa.Column("order_no", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=24), nullable=False),
            sa.Column("stem", sa.Text(), nullable=False),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("answer", sa.JSON(), nullable=True),
            sa.Column("analysis", sa.Text(), nullable=True),
            sa.Column("difficulty", sa.Integer(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=True),
            sa.Column("reference_code", sa.Text(), nullable=True),
            sa.Column("test_cases", sa.JSON(), nullable=True),
            sa.Column("media", sa.JSON(), nullable=True),
            sa.Column("knowledge_points", sa.JSON(), nullable=True),
            sa.Column("source_excerpt", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("reviewed_by", sa.Uuid(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["bank_set_id"], ["question_bank_sets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("bank_set_id", "order_no"),
        )
        for col in ("bank_set_id", "order_no", "type", "status"):
            op.create_index(op.f(f"ix_question_bank_questions_{col}"), "question_bank_questions", [col], unique=False)


    if not _has("question_bank_blueprints"):
        op.create_table(
            "question_bank_blueprints",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("subject", sa.String(length=80), nullable=True),
            sa.Column("level", sa.String(length=40), nullable=True),
            sa.Column("rules", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for col in ("subject", "level", "created_by"):
            op.create_index(op.f(f"ix_question_bank_blueprints_{col}"), "question_bank_blueprints", [col], unique=False)

    if not _has("question_bank_attempts"):
        op.create_table(
            "question_bank_attempts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("student_id", sa.Uuid(), nullable=False),
            sa.Column("bank_set_id", sa.Uuid(), nullable=True),
            sa.Column("mode", sa.String(length=12), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("question_snapshot", sa.JSON(), nullable=False),
            sa.Column("answers", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("total_score", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["bank_set_id"], ["question_bank_sets.id"]),
            sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for col in ("student_id", "bank_set_id", "status"):
            op.create_index(op.f(f"ix_question_bank_attempts_{col}"), "question_bank_attempts", [col], unique=False)


def downgrade() -> None:
    for table in (
        "question_bank_attempts",
        "question_bank_blueprints",
        "question_bank_questions",
        "question_bank_sets",
        "question_bank_sources",
    ):
        if _has(table):
            op.drop_table(table)

