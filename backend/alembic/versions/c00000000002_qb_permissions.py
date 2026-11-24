"""题库操作权限：上传/审核/发布/作业草稿/组卷/归档

Revision ID: c00000000002
Revises: c00000000001
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c00000000002"
down_revision: str | None = "c00000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "question_bank_import",
    "question_bank_review",
    "question_bank_publish",
    "question_bank_assignment",
    "question_bank_blueprint",
    "question_bank_archive",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "teacher_permissions",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("teacher_permissions", name)
