"""MCP 广场：agent_mcps.visibility（发布/下架）+ 收录关系表。

Revision ID: c0ffee000034
Revises: c0ffee000033
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000034"
down_revision: str | None = "c0ffee000033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 幂等：Base.metadata.create_all 可能已建表（无 alembic 版本记录），逐项补齐
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "visibility" not in [c["name"] for c in insp.get_columns("agent_mcps")]:
        op.add_column(
            "agent_mcps",
            sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        )
    if "ix_agent_mcps_visibility" not in [i["name"] for i in insp.get_indexes("agent_mcps")]:
        op.create_index("ix_agent_mcps_visibility", "agent_mcps", ["visibility"])
    if "agent_mcp_collections" not in insp.get_table_names():
        op.create_table(
            "agent_mcp_collections",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("mcp_id", PG_UUID(as_uuid=True), sa.ForeignKey("agent_mcps.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("agent_mcp_collections")
    op.drop_index("ix_agent_mcps_visibility", table_name="agent_mcps")
    op.drop_column("agent_mcps", "visibility")
