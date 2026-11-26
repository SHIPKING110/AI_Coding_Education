"""题库做题会话归属、AI 校准审计、知识点词表与能力评语缓存

Revision ID: c00000000004
Revises: c00000000003
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c00000000004"
down_revision: str | None = "c00000000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # —— 做题会话：支持教师/管理员本人记录、练习/考试细分来源、反馈回放 ——
    op.add_column("question_bank_attempts", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_index("ix_question_bank_attempts_user_id", "question_bank_attempts", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_question_bank_attempts_user_id_users",
        "question_bank_attempts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("question_bank_attempts", "student_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(
        "question_bank_attempts",
        sa.Column("kind", sa.String(length=24), nullable=False, server_default="set_practice"),
    )
    op.create_index("ix_question_bank_attempts_kind", "question_bank_attempts", ["kind"], unique=False)
    op.add_column("question_bank_attempts", sa.Column("paper_title", sa.String(length=200), nullable=True))
    op.add_column("question_bank_attempts", sa.Column("paper_meta", sa.JSON(), nullable=True))
    op.add_column(
        "question_bank_attempts",
        sa.Column("question_results", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )

    # 历史数据回填：优先学员账号，其次家长账号
    op.execute(
        """
        UPDATE question_bank_attempts a
           SET user_id = COALESCE(s.student_user_id, s.parent_user_id)
          FROM students s
         WHERE a.student_id = s.id AND a.user_id IS NULL
        """
    )

    # —— AI 校准/打标审计 ——
    op.create_table(
        "question_bank_ai_reviews",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("question_id", sa.UUID(), sa.ForeignKey("question_bank_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="suggested"),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qb_ai_reviews_question_id", "question_bank_ai_reviews", ["question_id"], unique=False)
    op.create_index("ix_qb_ai_reviews_kind", "question_bank_ai_reviews", ["kind"], unique=False)
    op.create_index("ix_qb_ai_reviews_content_hash", "question_bank_ai_reviews", ["content_hash"], unique=False)
    op.create_index("ix_qb_ai_reviews_status", "question_bank_ai_reviews", ["status"], unique=False)

    # —— 知识点受控词表 ——
    op.create_table(
        "question_bank_kp_taxonomy",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("subject", sa.String(length=80), nullable=False),
        sa.Column("level", sa.String(length=40), nullable=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("parent", sa.String(length=120), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subject", "level", "code", name="uq_qb_kp_subject_level_code"),
    )
    op.create_index("ix_qb_kp_subject", "question_bank_kp_taxonomy", ["subject"], unique=False)
    op.create_index("ix_qb_kp_level", "question_bank_kp_taxonomy", ["level"], unique=False)
    op.create_index("ix_qb_kp_status", "question_bank_kp_taxonomy", ["status"], unique=False)

    # —— 能力评语缓存 ——
    op.create_table(
        "practice_ability_reports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.UUID(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=True),
        sa.Column("stats_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_par_user_id", "practice_ability_reports", ["user_id"], unique=False)
    op.create_index("ix_par_student_id", "practice_ability_reports", ["student_id"], unique=False)
    op.create_index("ix_par_stats_hash", "practice_ability_reports", ["stats_hash"], unique=False)


def downgrade() -> None:
    op.drop_table("practice_ability_reports")
    op.drop_table("question_bank_kp_taxonomy")
    op.drop_table("question_bank_ai_reviews")
    op.drop_index("ix_question_bank_attempts_kind", table_name="question_bank_attempts")
    op.drop_column("question_bank_attempts", "kind")
    op.drop_column("question_bank_attempts", "question_results")
    op.drop_column("question_bank_attempts", "paper_meta")
    op.drop_column("question_bank_attempts", "paper_title")
    op.drop_constraint("fk_question_bank_attempts_user_id_users", "question_bank_attempts", type_="foreignkey")
    op.drop_index("ix_question_bank_attempts_user_id", table_name="question_bank_attempts")
    op.drop_column("question_bank_attempts", "user_id")
    op.alter_column("question_bank_attempts", "student_id", existing_type=sa.UUID(), nullable=False)
