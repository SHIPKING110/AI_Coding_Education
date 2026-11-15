"""作业批改模式 review_mode：auto=提交即公布 / teacher_confirm=教师确认后公布

Revision ID: c0ffee000014
Revises: c0ffee000013
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000014"
down_revision: str | None = "c0ffee000013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    review_enum = ENUM(
        "auto", "teacher_confirm", name="assignment_review_mode", native_enum=False, length=16
    )
    review_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "assignments",
        sa.Column(
            "review_mode",
            review_enum,
            nullable=False,
            server_default="auto",
        ),
    )


def downgrade() -> None:
    op.drop_column("assignments", "review_mode")
    ENUM(name="assignment_review_mode").drop(op.get_bind(), checkfirst=True)
