"""M5 体验与账务完善：学员校区 / 订单退费 / 作业分值与达标线 / 补练定向

- students.campus：学员所属校区（订单按校区筛选、流水账单区分）
- orders.refund_amount/refund_note/refund_detail/refunded_at：退费结果回写订单
- assignments.type_scores/passing_score：题型分值配置与达标线
- assignment_students：补练作业 → 定向学员（仅这些学员可见）

Revision ID: c0ffee000009
Revises: c0ffee000008
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000009"
down_revision: str | None = "c0ffee000008"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 学员所属校区
    op.add_column("students", sa.Column("campus", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_students_campus"), "students", ["campus"], unique=False)

    # 订单退费字段
    op.add_column("orders", sa.Column("refund_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("orders", sa.Column("refund_note", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("refund_detail", sa.JSON(), nullable=True))
    op.add_column("orders", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))

    # 作业题型分值配置 + 达标线
    op.add_column("assignments", sa.Column("type_scores", sa.JSON(), nullable=True))
    op.add_column("assignments", sa.Column("passing_score", sa.Integer(), nullable=True))

    # 补练作业 → 定向学员
    op.create_table(
        "assignment_students",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "student_id"),
    )
    op.create_index(
        op.f("ix_assignment_students_assignment_id"),
        "assignment_students",
        ["assignment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assignment_students_student_id"),
        "assignment_students",
        ["student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assignment_students_student_id"), table_name="assignment_students")
    op.drop_index(op.f("ix_assignment_students_assignment_id"), table_name="assignment_students")
    op.drop_table("assignment_students")

    op.drop_column("assignments", "passing_score")
    op.drop_column("assignments", "type_scores")

    op.drop_column("orders", "refunded_at")
    op.drop_column("orders", "refund_detail")
    op.drop_column("orders", "refund_note")
    op.drop_column("orders", "refund_amount")

    op.drop_index(op.f("ix_students_campus"), table_name="students")
    op.drop_column("students", "campus")