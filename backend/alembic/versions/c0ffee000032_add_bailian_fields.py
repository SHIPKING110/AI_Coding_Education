"""add bailian sandbox fields to sandbox_settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000032"
down_revision: str | None = "c0ffee000031"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("sandbox_settings", sa.Column("workspace_id", sa.String(64), nullable=False, server_default=""))
    op.add_column("sandbox_settings", sa.Column("region", sa.String(32), nullable=False, server_default="cn-beijing"))
    op.add_column("sandbox_settings", sa.Column("template_code", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("sandbox_settings", "template_code")
    op.drop_column("sandbox_settings", "region")
    op.drop_column("sandbox_settings", "workspace_id")
