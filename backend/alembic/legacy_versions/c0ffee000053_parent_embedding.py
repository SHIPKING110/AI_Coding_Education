"""家长客服专属 Embedding 配置（单例）。

Revision ID: c0ffee000053
Revises: c0ffee000052
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000053"
down_revision: str | None = "c0ffee000052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("system_parent_embedding_config"):
        return
    op.create_table(
        "system_parent_embedding_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False, server_default="remote"),
        sa.Column("base_url", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("api_key_enc", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("model_path", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    if _has_table("system_parent_embedding_config"):
        op.drop_table("system_parent_embedding_config")
