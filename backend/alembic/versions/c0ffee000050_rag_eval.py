"""RAG 评测：评测集 / 用例 / 运行 / 结果。

Revision ID: c0ffee000050
Revises: c0ffee000049
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000050"
down_revision: str | None = "c0ffee000049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_eval_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("domain", sa.String(length=32), nullable=False, server_default="agent_teacher"),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_eval_set_owner", "rag_eval_sets", ["owner_id"])

    op.create_table(
        "rag_eval_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("relevant", sa.JSON(), nullable=True),
        sa.Column("gt_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("gt_keywords", sa.JSON(), nullable=True),
        sa.Column("query_type", sa.String(length=32), nullable=False, server_default="fact"),
        sa.Column("difficulty", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["rag_eval_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_eval_case_set", "rag_eval_cases", ["set_id"])

    op.create_table(
        "rag_eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("rerank", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("answer_eval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("config_version", sa.Integer(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("compare", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["set_id"], ["rag_eval_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_eval_run_set", "rag_eval_runs", ["set_id"])
    op.create_index("ix_rag_eval_run_status", "rag_eval_runs", ["status"])
    op.create_index("ix_rag_eval_run_owner", "rag_eval_runs", ["owner_id"])

    op.create_table(
        "rag_eval_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("ranked", sa.JSON(), nullable=True),
        sa.Column("relevant", sa.JSON(), nullable=True),
        sa.Column("hits", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("retrieval_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("bad_case_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["rag_eval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_eval_result_run", "rag_eval_results", ["run_id"])
    op.create_index("ix_rag_eval_result_case", "rag_eval_results", ["case_id"])


def downgrade() -> None:
    op.drop_table("rag_eval_results")
    op.drop_table("rag_eval_runs")
    op.drop_table("rag_eval_cases")
    op.drop_table("rag_eval_sets")
