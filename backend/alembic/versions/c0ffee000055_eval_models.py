"""评测运行：生成模型与评测模型分离。

Revision ID: c0ffee000055
Revises: c0ffee000054
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000055"
down_revision: str | None = "c0ffee000054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rag_eval_runs", sa.Column("generation_config_id", sa.Uuid(), nullable=True))
    op.add_column("rag_eval_runs", sa.Column("judge_config_id", sa.Uuid(), nullable=True))
    op.add_column(
        "rag_eval_runs",
        sa.Column("generation_model", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "rag_eval_runs",
        sa.Column("judge_model", sa.String(length=128), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("rag_eval_runs", "judge_model")
    op.drop_column("rag_eval_runs", "generation_model")
    op.drop_column("rag_eval_runs", "judge_config_id")
    op.drop_column("rag_eval_runs", "generation_config_id")
