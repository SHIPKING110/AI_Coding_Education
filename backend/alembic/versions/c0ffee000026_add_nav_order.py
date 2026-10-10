"""侧边栏模块排序：system_settings.nav_order（个性化设置可调顺序）

Revision ID: c0ffee000026
Revises: c0ffee000025
"""

from alembic import op
import sqlalchemy as sa

revision = "c0ffee000026"
down_revision = "c0ffee000025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS nav_order TEXT DEFAULT '[]'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS nav_order")
