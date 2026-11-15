"""评测运行增加 parent_mode：可指定评测是否走家长专属集合（与生产家长客服一致）。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000059"
down_revision: str | None = "c0ffee000058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "parent_mode" not in _columns("rag_eval_runs"):
        op.add_column(
            "rag_eval_runs",
            sa.Column("parent_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if "parent_mode" in _columns("rag_eval_runs"):
        op.drop_column("rag_eval_runs", "parent_mode")
