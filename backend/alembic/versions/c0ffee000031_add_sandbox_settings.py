"""add sandbox_settings for skill remote sandbox (aliyun fc)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c0ffee000031"
down_revision: str | None = "c0ffee000030"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "sandbox_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True, index=True),
        sa.Column("provider", sa.String(16), nullable=False, server_default="local"),
        sa.Column("endpoint", sa.String(512), nullable=False, server_default=""),
        sa.Column("token", sa.String(256), nullable=False, server_default=""),
        sa.Column("timeout_s", sa.Integer, nullable=False, server_default="25"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sandbox_settings")
