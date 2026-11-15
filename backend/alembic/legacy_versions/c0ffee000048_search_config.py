"""联网搜索配置（system_search_config）：系统级单例，管理员配置 Tavily Key。

Revision ID: c0ffee000048
Revises: c0ffee000047
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000048"
down_revision: str | None = "c0ffee000047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_search_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False, server_default="tavily"),
        sa.Column("base_url", sa.String(length=256), nullable=False, server_default="https://api.tavily.com"),
        sa.Column("api_key_enc", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("search_depth", sa.String(length=16), nullable=False, server_default="basic"),
        sa.Column("max_results", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="zh"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("system_search_config")
