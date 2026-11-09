"""评测质量契约：显式可答性、数据集分层与运行快照。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000057"
down_revision: str | None = "c0ffee000056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    run_columns = _columns("rag_eval_runs")
    case_columns = _columns("rag_eval_cases")
    if "eval_snapshot" not in run_columns:
        op.add_column("rag_eval_runs", sa.Column("eval_snapshot", sa.JSON(), nullable=True))
    if "retrieval_mode" not in run_columns:
        op.add_column(
            "rag_eval_runs",
            sa.Column("retrieval_mode", sa.String(length=16), nullable=False, server_default="auto"),
        )
    if "answerability" not in case_columns:
        op.add_column(
            "rag_eval_cases",
            sa.Column("answerability", sa.String(length=16), nullable=False, server_default="unlabeled"),
        )
    if "split" not in case_columns:
        op.add_column(
            "rag_eval_cases",
            sa.Column("split", sa.String(length=16), nullable=False, server_default="regression"),
        )
    if "business_criticality" not in case_columns:
        op.add_column(
            "rag_eval_cases",
            sa.Column("business_criticality", sa.String(length=16), nullable=False, server_default="normal"),
        )
    # Preserve the old implicit contract: populated relevant labels were answerable.
    op.execute(
        sa.text(
            "UPDATE rag_eval_cases SET answerability = 'answerable' "
            "WHERE relevant IS NOT NULL AND json_array_length(relevant) > 0 "
            "AND answerability = 'unlabeled'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    run_columns = {column["name"] for column in sa.inspect(bind).get_columns("rag_eval_runs")}
    case_columns = {column["name"] for column in sa.inspect(bind).get_columns("rag_eval_cases")}
    if "retrieval_mode" in run_columns:
        op.drop_column("rag_eval_runs", "retrieval_mode")
    if "business_criticality" in case_columns:
        op.drop_column("rag_eval_cases", "business_criticality")
    if "split" in case_columns:
        op.drop_column("rag_eval_cases", "split")
    if "answerability" in case_columns:
        op.drop_column("rag_eval_cases", "answerability")
    if "eval_snapshot" in run_columns:
        op.drop_column("rag_eval_runs", "eval_snapshot")
