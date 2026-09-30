"""知识库检索开关：knowledge_documents.enabled（关闭即不参与 RAG 检索）

Revision ID: c0ffee000020
Revises: c0ffee000019
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000020"
down_revision: str | None = "c0ffee000019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_knowledge_documents_enabled", "knowledge_documents", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_enabled", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "enabled")
