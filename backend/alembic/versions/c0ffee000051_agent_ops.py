"""Agent 任务观测 + PPT 任务契约。

Revision ID: c0ffee000051
Revises: c0ffee000050
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000051"
down_revision: str | None = "c0ffee000050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table: str, name: str, cols: list[str] | None = None) -> bool:
    for i in sa.inspect(op.get_bind()).get_indexes(table):
        if i.get("name") == name:
            return True
        if cols and list(i.get("column_names") or []) == cols:
            return True
    return False


def _cols(table: str) -> set[str]:
    return {c.get("name") for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table("agent_run_traces"):
        op.create_table(
            "agent_run_traces",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.String(length=48), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), nullable=True),
            sa.Column("message_id", sa.Uuid(), nullable=True),
            sa.Column("agent_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("owner_id", sa.Uuid(), nullable=True),
            sa.Column("domain", sa.String(length=32), nullable=False, server_default="agent_teacher"),
            sa.Column("intent", sa.String(length=32), nullable=False, server_default="unknown"),
            sa.Column("intent_confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("intent_source", sa.String(length=16), nullable=False, server_default="rule"),
            sa.Column("needs_rag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("rag_decision", sa.String(length=32), nullable=False, server_default="not_applicable"),
            sa.Column("rag_skip_reason", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("retrieval_trace_id", sa.String(length=48), nullable=True),
            sa.Column("task_kind", sa.String(length=32), nullable=False, server_default="chat"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("first_token_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rag_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mcp_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skill_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_estimate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("ppt_target_pages", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ppt_current_pages", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ppt_aligned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("ppt_project_key", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("artifact_url", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("error_code", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("attributes", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id"),
        )
    if _has_table("agent_run_traces"):
        existing = _cols("agent_run_traces")
        for col, ddl in (
            ("ppt_target_pages", sa.Column("ppt_target_pages", sa.Integer(), nullable=False, server_default="0")),
            ("ppt_current_pages", sa.Column("ppt_current_pages", sa.Integer(), nullable=False, server_default="0")),
            ("ppt_aligned", sa.Column("ppt_aligned", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
            ("ppt_project_key", sa.Column("ppt_project_key", sa.String(length=512), nullable=False, server_default="")),
            ("artifact_url", sa.Column("artifact_url", sa.String(length=512), nullable=False, server_default="")),
        ):
            if col not in existing:
                op.add_column("agent_run_traces", ddl)
    for name, cols in (
        ("ix_agent_run_run_id", ["run_id"]),
        ("ix_agent_run_conv", ["conversation_id"]),
        ("ix_agent_run_msg", ["message_id"]),
        ("ix_agent_run_agent", ["agent_id"]),
        ("ix_agent_run_user", ["user_id"]),
        ("ix_agent_run_owner", ["owner_id"]),
        ("ix_agent_run_domain", ["domain"]),
        ("ix_agent_run_intent", ["intent"]),
        ("ix_agent_run_needs_rag", ["needs_rag"]),
        ("ix_agent_run_rag_decision", ["rag_decision"]),
        ("ix_agent_run_retrieval", ["retrieval_trace_id"]),
        ("ix_agent_run_task_kind", ["task_kind"]),
        ("ix_agent_run_status", ["status"]),
        ("ix_agent_run_created", ["created_at"]),
    ):
        if _has_table("agent_run_traces") and not _has_index("agent_run_traces", name):
            op.create_index(name, "agent_run_traces", cols)

    if not _has_table("agent_run_spans"):
        op.create_table(
            "agent_run_spans",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.String(length=48), nullable=False),
            sa.Column("span_id", sa.String(length=48), nullable=False),
            sa.Column("parent_span_id", sa.String(length=48), nullable=True),
            sa.Column("span_type", sa.String(length=24), nullable=False, server_default="tool"),
            sa.Column("name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_estimate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("attributes", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("span_id"),
        )
    for name, cols in (
        ("ix_agent_span_run", ["run_id"]),
        ("ix_agent_span_span_id", ["span_id"]),
        ("ix_agent_span_parent", ["parent_span_id"]),
        ("ix_agent_span_type", ["span_type"]),
        ("ix_agent_span_status", ["status"]),
        ("ix_agent_span_created", ["created_at"]),
    ):
        if _has_table("agent_run_spans") and not _has_index("agent_run_spans", name):
            op.create_index(name, "agent_run_spans", cols)

    if not _has_table("agent_ppt_tasks"):
        op.create_table(
            "agent_ppt_tasks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), nullable=False),
            sa.Column("owner_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.String(length=64), nullable=False, server_default="assistant"),
            sa.Column("skill_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("skill_name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("project_key", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("theme", sa.String(length=32), nullable=False, server_default="brand"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="outline"),
            sa.Column("target_page_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_page_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("outline", sa.JSON(), nullable=True),
            sa.Column("current_pptx_url", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("last_build_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in (
        ("ix_agent_ppt_conv", ["conversation_id"]),
        ("ix_agent_ppt_owner", ["owner_id"]),
        ("ix_agent_ppt_agent", ["agent_id"]),
        ("ix_agent_ppt_status", ["status"]),
    ):
        if _has_table("agent_ppt_tasks") and not _has_index("agent_ppt_tasks", name):
            op.create_index(name, "agent_ppt_tasks", cols)

    if not _has_table("agent_ppt_task_events"):
        op.create_table(
            "agent_ppt_task_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("action", sa.String(length=48), nullable=False, server_default=""),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in (
        ("ix_agent_ppt_event_task", ["task_id"]),
        ("ix_agent_ppt_event_action", ["action"]),
        ("ix_agent_ppt_event_created", ["created_at"]),
    ):
        if _has_table("agent_ppt_task_events") and not _has_index("agent_ppt_task_events", name):
            op.create_index(name, "agent_ppt_task_events", cols)


def downgrade() -> None:
    if _has_table("agent_ppt_task_events"):
        op.drop_table("agent_ppt_task_events")
    if _has_table("agent_ppt_tasks"):
        op.drop_table("agent_ppt_tasks")
    if _has_table("agent_run_spans"):
        op.drop_table("agent_run_spans")
    if _has_table("agent_run_traces"):
        op.drop_table("agent_run_traces")
