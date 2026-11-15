"""RAG 运营后台：检索 trace / 参数版本 / 审计。

Revision ID: c0ffee000049
Revises: c0ffee000048
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000049"
down_revision: str | None = "c0ffee000048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_retrieval_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=48), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("route", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("rewritten_query", sa.Text(), nullable=False, server_default=""),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("embedding_fingerprint", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("vector_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keyword_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rerank_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gated_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("keyword_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rerank_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rerank_model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("zero_result", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage_timings", sa.JSON(), nullable=True),
        sa.Column("hits", sa.JSON(), nullable=True),
        sa.Column("feedback", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id"),
    )
    op.create_index("ix_rag_trace_created", "rag_retrieval_traces", ["created_at"])
    op.create_index("ix_rag_trace_domain", "rag_retrieval_traces", ["domain"])
    op.create_index("ix_rag_trace_owner", "rag_retrieval_traces", ["owner_id"])
    op.create_index("ix_rag_trace_conv", "rag_retrieval_traces", ["conversation_id"])
    op.create_index("ix_rag_trace_zero", "rag_retrieval_traces", ["zero_result"])
    op.create_index("ix_rag_trace_error", "rag_retrieval_traces", ["is_error"])

    op.create_table(
        "rag_config_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_rag_config_version", "rag_config_versions", ["version"])

    op.create_table(
        "rag_admin_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_audit_action", "rag_admin_audit", ["action"])
    op.create_index("ix_rag_audit_operator", "rag_admin_audit", ["operator_id"])
    op.create_index("ix_rag_audit_created", "rag_admin_audit", ["created_at"])


def downgrade() -> None:
    op.drop_table("rag_admin_audit")
    op.drop_table("rag_config_versions")
    op.drop_table("rag_retrieval_traces")
