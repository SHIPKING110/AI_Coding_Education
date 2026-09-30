"""M3 报告：reports 表（日报/周报）

- 日报（daily）：教师每日工作记录（work/courses/problems/plan）
- 周报（weekly）：统计指标快照（上课人次/出勤率/缺课/新增学员）+ 文字总结
- 同一教师同类型同周期仅一份（幂等创建=更新）

Revision ID: c0ffee000003
Revises: c0ffee000002
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000003"
down_revision: str | None = "c0ffee000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "type",
            sa.Enum("daily", "weekly", name="report_type", native_enum=False, length=16),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "teacher_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("content", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "published", name="report_status", native_enum=False, length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "type", "teacher_id", "period_start", "period_end", name="uq_report_period"
        ),
    )


def downgrade() -> None:
    op.drop_table("reports")
