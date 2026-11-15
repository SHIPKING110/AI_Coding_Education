"""Agent 会话阶段与消息 options：conversations.stage / messages.options

Revision ID: c0ffee000018
Revises: c0ffee000017
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000018"
down_revision: str | None = "c0ffee000017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("stage", sa.String(32), server_default="data", nullable=False),
    )
    op.add_column("agent_messages", sa.Column("options", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_messages", "options")
    op.drop_column("agent_conversations", "stage")
