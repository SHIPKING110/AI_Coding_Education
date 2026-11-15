"""Agent 行为评测：评测集 / 用例 / 运行 / 结果（工具编排回归）。

幂等说明：应用启动时 schema_ensure 会先行 create_all / ADD COLUMN 兜底，
因此本迁移所有建表/加列都先探测再执行，保证「先启应用后跑迁移」也不会失败。

Revision ID: c0ffee000060
Revises: c0ffee000059
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000060"
down_revision: str | None = "c0ffee000059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def upgrade() -> None:
    # 评测会话隔离：Agent 对话增加来源标记（chat=用户对话，eval=评测驱动）
    if _has_table("agent_conversations") and not _has_column("agent_conversations", "source"):
        op.add_column(
            "agent_conversations",
            sa.Column("source", sa.String(length=16), nullable=False, server_default="chat"),
        )

    if not _has_table("agent_eval_sets"):
        op.create_table(
            "agent_eval_sets",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("agent_scope", sa.String(length=32), nullable=False, server_default="teacher"),
            sa.Column("owner_id", sa.Uuid(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_agent_eval_sets_agent_scope", "agent_eval_sets", ["agent_scope"])
        op.create_index("ix_agent_eval_sets_owner_id", "agent_eval_sets", ["owner_id"])

    if not _has_table("agent_eval_cases"):
        op.create_table(
            "agent_eval_cases",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "set_id",
                sa.Uuid(),
                sa.ForeignKey("agent_eval_sets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("messages", sa.JSON(), nullable=True),
            sa.Column("expected_tools", sa.JSON(), nullable=True),
            sa.Column("allowed_extra_tools", sa.JSON(), nullable=True),
            sa.Column("forbidden_tools", sa.JSON(), nullable=True),
            sa.Column("expect_abstain", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("expected_facts", sa.JSON(), nullable=True),
            sa.Column("split", sa.String(length=16), nullable=False, server_default="regression"),
            sa.Column("business_criticality", sa.String(length=16), nullable=False, server_default="normal"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_agent_eval_cases_set_id", "agent_eval_cases", ["set_id"])

    if not _has_table("agent_eval_runs"):
        op.create_table(
            "agent_eval_runs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "set_id",
                sa.Uuid(),
                sa.ForeignKey("agent_eval_sets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("stage", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_cases", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("agent_id", sa.String(length=64), nullable=False, server_default="assistant"),
            sa.Column("model_config_id", sa.Uuid(), nullable=True),
            sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("eval_snapshot", sa.JSON(), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=True),
            sa.Column("gate", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_agent_eval_runs_set_id", "agent_eval_runs", ["set_id"])
        op.create_index("ix_agent_eval_runs_status", "agent_eval_runs", ["status"])

    if not _has_table("agent_eval_results"):
        op.create_table(
            "agent_eval_results",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "run_id",
                sa.Uuid(),
                sa.ForeignKey("agent_eval_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("case_id", sa.Uuid(), nullable=True),
            sa.Column("query", sa.Text(), nullable=False, server_default=""),
            sa.Column("trace_run_id", sa.String(length=48), nullable=False, server_default=""),
            sa.Column("final_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("expected_tools", sa.JSON(), nullable=True),
            sa.Column("tool_calls", sa.JSON(), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("human_score", sa.Integer(), nullable=True),
            sa.Column("human_judge", sa.String(length=64), nullable=True),
            sa.Column("human_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("human_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_agent_eval_results_run_id", "agent_eval_results", ["run_id"])
        op.create_index("ix_agent_eval_results_case_id", "agent_eval_results", ["case_id"])


def downgrade() -> None:
    op.drop_table("agent_eval_results")
    op.drop_table("agent_eval_runs")
    op.drop_table("agent_eval_cases")
    op.drop_table("agent_eval_sets")
    op.drop_column("agent_conversations", "source")
