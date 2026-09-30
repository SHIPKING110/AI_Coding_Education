"""regen-dedup：class_ppts 新增 material_hash（素材指纹，重提炼去重用）

Revision ID: c0ffee000012
Revises: c0ffee000011
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000012"
down_revision: str | None = "c0ffee000011"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("class_ppts", sa.Column("material_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("class_ppts", "material_hash")
