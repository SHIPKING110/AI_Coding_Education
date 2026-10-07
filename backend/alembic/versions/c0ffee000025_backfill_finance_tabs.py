"""backfill finance tab permissions from legacy finance_view master switch

Revision ID: c0ffee000025
Revises: c0ffee000024
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000025"
down_revision: str | None = "c0ffee000024"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 存量教师若有 finance_view 全开，则把细分 tab 一并打开（保持升级前行为不收缩）
    op.execute(
        "UPDATE teacher_permissions SET finance_revenue = true WHERE finance_view = true"
    )
    op.execute(
        "UPDATE teacher_permissions SET finance_records = true WHERE finance_view = true"
    )
    op.execute(
        "UPDATE teacher_permissions SET finance_salary = true WHERE finance_view = true"
    )


def downgrade() -> None:
    pass
