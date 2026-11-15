"""评测结果人工评分：用于 LLM 裁判与人工一致性（Cohen's Kappa）校准。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000058"
down_revision: str | None = "c0ffee000057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    case_columns = _columns("rag_eval_results")
    for col, sa_type in (
        ("human_score", sa.Integer()),
        ("human_judge", sa.String(length=64)),
        ("human_at", sa.DateTime(timezone=True)),
        ("human_reason", sa.Text()),
    ):
        if col not in case_columns:
            op.add_column("rag_eval_results", sa.Column(col, sa_type, nullable=True))
    op.create_index(
        "ix_rag_eval_results_human_score", "rag_eval_results", ["human_score"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    case_columns = {column["name"] for column in sa.inspect(bind).get_columns("rag_eval_results")}
    if "human_score" in case_columns:
        op.drop_index("ix_rag_eval_results_human_score", table_name="rag_eval_results")
    for col in ("human_reason", "human_at", "human_judge", "human_score"):
        if col in case_columns:
            op.drop_column("rag_eval_results", col)
