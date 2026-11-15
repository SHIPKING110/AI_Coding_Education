"""会话分享链接：agent_conversations.share_token（公开只读分享页）

Revision ID: c0ffee000022
Revises: c0ffee000021
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000022"
down_revision: str | None = "c0ffee000021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_conversations", sa.Column("share_token", sa.String(64), nullable=True))
    op.create_index(
        "ix_agent_conversations_share_token", "agent_conversations", ["share_token"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_agent_conversations_share_token", table_name="agent_conversations")
    op.drop_column("agent_conversations", "share_token")
