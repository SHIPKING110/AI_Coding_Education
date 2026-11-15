"""M2 补强2：students.stop_note（学员停课备注）+ 学员状态支持 stopped

Revision ID: a1b2c3d4e5f6
Revises: 7f9a2c41b8d3
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7f9a2c41b8d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 学员停课备注：status=stopped 时必填，供教务与家长沟通恢复复课使用
    op.add_column("students", sa.Column("stop_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "stop_note")
