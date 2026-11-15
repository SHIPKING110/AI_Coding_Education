"""家长客服 P0：system_settings 配额/词表列 + teacher_permissions 教学服务两键。

Revision ID: c0ffee000045
Revises: c0ffee000044
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000045"
down_revision: str | None = "c0ffee000044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RISK_DEFAULT = '["退费", "收费", "价格", "安全", "受伤", "事故", "投诉", "报警", "律师", "骨折", "过敏"]'


def _add_bool(bind, table: str, name: str, default_true: bool = True) -> None:
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    if name not in cols:
        op.add_column(
            table,
            sa.Column(
                name, sa.Boolean(), nullable=False,
                server_default=sa.text("true" if default_true else "false"),
            ),
        )


def upgrade() -> None:
    bind = op.get_bind()
    # system_settings：配额与词表（单例行 id=1 沿用；_ensure_columns 另有兼容，此处为正迁移）
    cols = {c["name"] for c in sa.inspect(bind).get_columns("system_settings")}
    if "parent_anon_daily_limit" not in cols:
        op.add_column(
            "system_settings",
            sa.Column("parent_anon_daily_limit", sa.Integer(), nullable=False, server_default="3"),
        )
    if "parent_daily_limit" not in cols:
        op.add_column(
            "system_settings",
            sa.Column("parent_daily_limit", sa.Integer(), nullable=False, server_default="50"),
        )
    if "parent_risk_words" not in cols:
        op.add_column(
            "system_settings",
            sa.Column("parent_risk_words", sa.Text(), nullable=False, server_default=RISK_DEFAULT),
        )
    if "parent_quick_replies" not in cols:
        op.add_column(
            "system_settings",
            sa.Column("parent_quick_replies", sa.Text(), nullable=False, server_default="[]"),
        )
    # teacher_permissions：教学服务两键
    _add_bool(bind, "teacher_permissions", "nav_service", True)
    _add_bool(bind, "teacher_permissions", "service_reply", True)


def downgrade() -> None:
    for col in ("parent_quick_replies", "parent_risk_words", "parent_daily_limit", "parent_anon_daily_limit"):
        op.drop_column("system_settings", col)
    op.drop_column("teacher_permissions", "service_reply")
    op.drop_column("teacher_permissions", "nav_service")
