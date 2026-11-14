"""评测运行进度字段。

Revision ID: c0ffee000056
Revises: c0ffee000055
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000056"
down_revision: str | None = "c0ffee000055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("rag_eval_runs")}
    if "total_cases" not in existing:
        op.add_column(
            "rag_eval_runs",
            sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        )
    if "processed_cases" not in existing:
        op.add_column(
            "rag_eval_runs",
            sa.Column("processed_cases", sa.Integer(), nullable=False, server_default="0"),
        )
    if "stage" not in existing:
        op.add_column(
            "rag_eval_runs",
            sa.Column("stage", sa.String(length=32), nullable=False, server_default="pending"),
        )
    if "progress" not in existing:
        op.add_column(
            "rag_eval_runs",
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("rag_eval_runs")}
    for name in ("progress", "stage", "processed_cases", "total_cases"):
        if name in existing:
            op.drop_column("rag_eval_runs", name)
