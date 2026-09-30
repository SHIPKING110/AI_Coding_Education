"""作业模式：classwork=课堂作业（答案收起+仅发学员账号）/ homework=课后作业

Revision ID: c0ffee000013
Revises: c0ffee000012
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000013"
down_revision: str | None = "c0ffee000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    mode_enum = ENUM("classwork", "homework", name="assignment_mode", native_enum=False, length=16)
    mode_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "assignments",
        sa.Column(
            "mode",
            mode_enum,
            nullable=False,
            server_default="homework",
        ),
    )


def downgrade() -> None:
    op.drop_column("assignments", "mode")
    ENUM(name="assignment_mode").drop(op.get_bind(), checkfirst=True)
