"""作业自定义分组：assignment_folders 表 + assignments.folder_id

Revision ID: c0ffee000015
Revises: c0ffee000014
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000015"
down_revision: str | None = "c0ffee000014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignment_folders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("sort_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "assignments",
        sa.Column("folder_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignments_folder_id",
        "assignments",
        "assignment_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_assignments_folder_id"), "assignments", ["folder_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assignments_folder_id"), table_name="assignments")
    op.drop_constraint("fk_assignments_folder_id", "assignments", type_="foreignkey")
    op.drop_column("assignments", "folder_id")
    op.drop_table("assignment_folders")
