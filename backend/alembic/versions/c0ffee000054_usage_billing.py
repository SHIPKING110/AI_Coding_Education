"""Token 计量与成本记账（用量与成本仪表盘）。

Revision ID: c0ffee000054
Revises: c0ffee000053
Create Date: 2026-11-04

- 新表：llm_model_prices（版本化价格）/ llm_usage_events（记账行）/ llm_usage_monthly（月汇总）/
  llm_usage_reconciliations（月度对账）
- system_settings 补：llm_monthly_budget / llm_budget_alert_ratio（预算告警）
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000054"
down_revision: str | None = "c0ffee000053"
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
    if not _has_table("llm_model_prices"):
        op.create_table(
            "llm_model_prices",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("provider_host", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("model_pattern", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
            sa.Column("input_per_1m", sa.Float(), nullable=False, server_default="0"),
            sa.Column("output_per_1m", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cache_read_per_1m", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cache_write_per_1m", sa.Float(), nullable=False, server_default="0"),
            sa.Column("tiers", sa.JSON(), nullable=True),
            sa.Column("time_windows", sa.JSON(), nullable=True),
            sa.Column(
                "effective_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("source_note", sa.String(length=256), nullable=False, server_default=""),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in (
        ("ix_llm_price_host", ["provider_host"]),
        ("ix_llm_price_model", ["model_pattern"]),
        ("ix_llm_price_effective", ["effective_from"]),
    ):
        if _has_table("llm_model_prices") and not _has_index("llm_model_prices", name):
            op.create_index(name, "llm_model_prices", cols)

    if not _has_table("llm_usage_events"):
        op.create_table(
            "llm_usage_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("run_id", sa.String(length=48), nullable=True),
            sa.Column("span_id", sa.String(length=48), nullable=True),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="chat"),
            sa.Column("module", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("owner_id", sa.Uuid(), nullable=True),
            sa.Column("config_id", sa.Uuid(), nullable=True),
            sa.Column("is_platform", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("provider_host", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(length=12), nullable=False, server_default="provider"),
            sa.Column("price_id", sa.Uuid(), nullable=True),
            sa.Column("price_snapshot", sa.JSON(), nullable=True),
            sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
            sa.Column("priced_status", sa.String(length=16), nullable=False, server_default="priced"),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in (
        ("ix_llm_usage_created", ["created_at"]),
        ("ix_llm_usage_run", ["run_id"]),
        ("ix_llm_usage_span", ["span_id"]),
        ("ix_llm_usage_kind", ["kind"]),
        ("ix_llm_usage_module", ["module"]),
        ("ix_llm_usage_owner", ["owner_id"]),
        ("ix_llm_usage_platform", ["is_platform"]),
        ("ix_llm_usage_host", ["provider_host"]),
        ("ix_llm_usage_model", ["model"]),
        ("ix_llm_usage_source", ["source"]),
        ("ix_llm_usage_priced", ["priced_status"]),
        ("ix_llm_usage_status", ["status"]),
    ):
        if _has_table("llm_usage_events") and not _has_index("llm_usage_events", name):
            op.create_index(name, "llm_usage_events", cols)

    if not _has_table("llm_usage_monthly"):
        op.create_table(
            "llm_usage_monthly",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("month", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
            sa.Column("events", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_total", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cost_platform", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cost_teacher", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unpriced_events", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("month", "currency", name="uq_llm_usage_month_currency"),
        )
    if _has_table("llm_usage_monthly") and not _has_index("llm_usage_monthly", "ix_llm_usage_monthly_month"):
        op.create_index("ix_llm_usage_monthly_month", "llm_usage_monthly", ["month"])

    if not _has_table("llm_usage_reconciliations"):
        op.create_table(
            "llm_usage_reconciliations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("month", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("billed_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
            sa.Column("note", sa.String(length=256), nullable=False, server_default=""),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("month", "provider", name="uq_llm_usage_recon_month"),
        )
    if _has_table("llm_usage_reconciliations") and not _has_index(
        "llm_usage_reconciliations", "ix_llm_usage_recon_month"
    ):
        op.create_index(
            "ix_llm_usage_recon_month", "llm_usage_reconciliations", ["month"]
        )

    if _has_table("system_settings"):
        existing = _cols("system_settings")
        for col, ddl in (
            (
                "llm_monthly_budget",
                sa.Column("llm_monthly_budget", sa.Float(), nullable=False, server_default="0"),
            ),
            (
                "llm_budget_alert_ratio",
                sa.Column("llm_budget_alert_ratio", sa.Float(), nullable=False, server_default="0.8"),
            ),
        ):
            if col not in existing:
                op.add_column("system_settings", ddl)


def downgrade() -> None:
    if _has_table("llm_usage_reconciliations"):
        op.drop_table("llm_usage_reconciliations")
    if _has_table("llm_usage_monthly"):
        op.drop_table("llm_usage_monthly")
    if _has_table("llm_usage_events"):
        op.drop_table("llm_usage_events")
    if _has_table("llm_model_prices"):
        op.drop_table("llm_model_prices")
    if _has_table("system_settings"):
        existing = _cols("system_settings")
        for col in ("llm_budget_alert_ratio", "llm_monthly_budget"):
            if col in existing:
                op.drop_column("system_settings", col)
