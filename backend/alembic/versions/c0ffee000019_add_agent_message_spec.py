"""Agent 消息 PPT 规格：agent_messages.spec（outline/sections/theme）

Revision ID: c0ffee000019
Revises: c0ffee000018
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000019"
down_revision: str | None = "c0ffee000018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_messages", sa.Column("spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_messages", "spec")
