"""MCP 收录改为「复制模板」：agent_mcps.source_mcp_id（记录模板来源）。

背景：发布到广场的 MCP 不得携带作者自己的 endpoint/API。收录时复制为
收录者名下的私有 MCP，endpoint/config 留空由收录者自行填写，避免泄露与盗用。

Revision ID: c0ffee000035
Revises: c0ffee000034
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000035"
down_revision: str | None = "c0ffee000034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "source_mcp_id" not in [c["name"] for c in insp.get_columns("agent_mcps")]:
        op.add_column("agent_mcps", sa.Column("source_mcp_id", PG_UUID(as_uuid=True), nullable=True))
    if "ix_agent_mcps_source_mcp_id" not in [i["name"] for i in insp.get_indexes("agent_mcps")]:
        op.create_index("ix_agent_mcps_source_mcp_id", "agent_mcps", ["source_mcp_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_mcps_source_mcp_id", table_name="agent_mcps")
    op.drop_column("agent_mcps", "source_mcp_id")
