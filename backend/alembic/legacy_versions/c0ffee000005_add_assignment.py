"""M4 AI 习题：assignments / questions / submissions 三表

- assignments：作业（教师出题 → 发布到班级；deadline 可选完成时间）
- questions：题目（题型 single_choice/multiple_choice/judgement/code_fill/programming，
  答案 JSONB + 编程题自动判题用例 test_cases）
- submissions：作业提交（学员维度，M5 客户端作答使用，M4 建表预留）

Revision ID: c0ffee000005
Revises: c0ffee000004
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000005"
down_revision: str | None = "c0ffee000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("classes.id"), nullable=True, index=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "published", name="assignment_status", native_enum=False, length=16),
            nullable=False,
            server_default="draft",
            index=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("order_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "type",
            sa.Enum(
                "single_choice",
                "multiple_choice",
                "judgement",
                "code_fill",
                "programming",
                name="question_type",
                native_enum=False,
                length=24,
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", JSONB(), nullable=True),
        sa.Column("answer", JSONB(), nullable=True),
        sa.Column("analysis", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("test_cases", JSONB(), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "student_id", sa.Uuid(), sa.ForeignKey("students.id"), nullable=False, index=True
        ),
        sa.Column("answers", JSONB(), nullable=True),
        sa.Column("judge_results", JSONB(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "not_submitted", "submitted", "graded", name="submission_status",
                native_enum=False, length=24,
            ),
            nullable=False,
            server_default="not_submitted",
            index=True,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("submissions")
    op.drop_table("questions")
    op.drop_table("assignments")
