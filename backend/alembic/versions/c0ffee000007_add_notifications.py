"""M5 客户端：通知系统（notifications 表）

- 站内通知（FR-CL-03 提醒通知：应用内 + 微信推送预留）
- 通知类型：上课提醒/低余量/订单到账/反馈发布/作业发布/批改完成
- 所有角色均可接收通知

Revision ID: c0ffee000007
Revises: c0ffee000006
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000007"
down_revision: str | None = "c0ffee000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column(
            "type",
            sa.Enum(
                "schedule_reminder",
                "low_balance",
                "order_confirmed",
                "feedback_published",
                "assignment_published",
                "submission_graded",
                name="notification_type",
                native_enum=False,
                length=32,
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data", JSONB(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("notifications")
