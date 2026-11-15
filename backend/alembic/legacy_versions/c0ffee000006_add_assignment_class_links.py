"""M4.1 多班级发布：assignment_class_links 作业→班级 发布关联表

- 一份作业可同时发布到多个班级；同一 (assignment_id, class_id) 唯一（已发布班级不可重复发布）
- 撤回作业时级联清空该关联（重新发布时可再选班级）
- 已有已发布作业的 class_id 回填为第一条发布记录

Revision ID: c0ffee000006
Revises: c0ffee000005
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000006"
down_revision: str | None = "c0ffee000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignment_class_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "class_id", sa.Uuid(), sa.ForeignKey("classes.id"), nullable=False, index=True
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("assignment_id", "class_id", name="uq_assignment_class"),
    )

    # 回填：既有已发布作业的主班级作为发布记录，保证后续「已发布班级不可重复选」一致
    op.execute(
        """
        INSERT INTO assignment_class_links (assignment_id, class_id)
        SELECT id, class_id
        FROM assignments
        WHERE status = 'published' AND class_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("assignment_class_links")
