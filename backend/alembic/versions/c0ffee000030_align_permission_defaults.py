"""align teacher_permissions server defaults with KEY_DEFAULTS (finance/nav)

Revision ID: c0ffee000030
Revises: c0ffee000029
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000030"
down_revision: str | None = "c0ffee000029"
branch_labels: str | None = None
depends_on: str | None = None

# 列名 → 应有的 server_default（与 KEY_DEFAULTS 一致）
_FIX_DEFAULTS: list[tuple[str, str]] = [
    ("finance_view", "true"),
    ("finance_revenue", "true"),
    ("nav_finance", "true"),
]

_PREV_DEFAULTS: dict[str, str] = {
    "finance_view": "false",
    "finance_revenue": "false",
    "nav_finance": "false",
}


def upgrade() -> None:
    for name, default in _FIX_DEFAULTS:
        op.alter_column("teacher_permissions", name, server_default=default)


def downgrade() -> None:
    for name in [n for n, _ in _FIX_DEFAULTS]:
        op.alter_column("teacher_permissions", name, server_default=_PREV_DEFAULTS[name])
