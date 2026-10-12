"""用户性别字段：users.gender（male/female/空=未填写）

Revision ID: c0ffee000028
Revises: c0ffee000027
"""

from alembic import op

revision = "c0ffee000028"
down_revision = "c0ffee000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(16)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS gender")
