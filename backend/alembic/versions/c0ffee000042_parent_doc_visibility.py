"""家长客服 P0：knowledge_documents.visible_to_parents（家长版白名单，默认隐藏）。

Revision ID: c0ffee000042
Revises: c0ffee000041
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000042"
down_revision: str | None = "c0ffee000041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("knowledge_documents")}
    if "visible_to_parents" not in cols:
        op.add_column(
            "knowledge_documents",
            sa.Column("visible_to_parents", sa.Boolean(), server_default="false", nullable=False),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("knowledge_documents")}
    if "ix_knowledge_documents_visible_to_parents" not in indexes:
        op.create_index(
            "ix_knowledge_documents_visible_to_parents", "knowledge_documents", ["visible_to_parents"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("knowledge_documents")}
    if "ix_knowledge_documents_visible_to_parents" in indexes:
        op.drop_index("ix_knowledge_documents_visible_to_parents", table_name="knowledge_documents")
    cols = {c["name"] for c in sa.inspect(bind).get_columns("knowledge_documents")}
    if "visible_to_parents" in cols:
        op.drop_column("knowledge_documents", "visible_to_parents")
