"""M3 季度/年度总结：reports.ppt_url 列

- 周报/季度/年度总结的 PPT 产物落盘路径（uploads/ppt/），非 PPT 类型为空
- ReportType 由代码模型扩展（daily/weekly/quarterly/yearly），列类型为
  String(enum native_enum=False)，无需列变更

Revision ID: c0ffee000004
Revises: c0ffee000003
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000004"
down_revision: str | None = "c0ffee000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("ppt_url", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "ppt_url")
