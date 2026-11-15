"""会话置顶：agent_conversations.pinned（置顶优先排序）

Revision ID: c0ffee000021
Revises: c0ffee000020
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000021"
down_revision: str | None = "c0ffee000020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_conversations", "pinned")
