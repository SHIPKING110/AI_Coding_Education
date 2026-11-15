"""家长客服 P1：会话自动关闭阈值（system_settings 两列）。

Revision ID: c0ffee000047
Revises: c0ffee000046
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000047"
down_revision: str | None = "c0ffee000046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("system_settings")}
    if "parent_open_idle_hours" not in cols:
        op.add_column(
            "system_settings",
            sa.Column("parent_open_idle_hours", sa.Integer(), nullable=False, server_default="24"),
        )
    if "parent_escalated_idle_hours" not in cols:
        op.add_column(
            "system_settings",
            sa.Column("parent_escalated_idle_hours", sa.Integer(), nullable=False, server_default="48"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("system_settings")}
    if "parent_escalated_idle_hours" in cols:
        op.drop_column("system_settings", "parent_escalated_idle_hours")
    if "parent_open_idle_hours" in cols:
        op.drop_column("system_settings", "parent_open_idle_hours")
