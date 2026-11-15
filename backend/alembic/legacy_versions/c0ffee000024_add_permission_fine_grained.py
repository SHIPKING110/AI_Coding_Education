"""add fine-grained permission columns (invitation/schedule-cancel/settings-tabs/package-edit/assignment/finance)

Revision ID: c0ffee000024
Revises: c0ffee000023
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000024"
down_revision: str | None = "c0ffee000023"
branch_labels: str | None = None
depends_on: str | None = None

_NEW_COLUMNS: list[tuple[str, str]] = [
    ("schedule_cancel", "false"),
    ("invitation_create", "true"),
    ("package_edit", "false"),
    ("assignment_ai", "true"),
    ("assignment_create", "true"),
    ("settings_tab_personalize", "false"),
    ("settings_tab_model", "false"),
    ("settings_tab_business", "false"),
    ("finance_revenue", "false"),
    ("finance_records", "false"),
    ("finance_salary", "false"),
    ("finance_salary_all", "false"),
]


def upgrade() -> None:
    for name, default in _NEW_COLUMNS:
        op.add_column(
            "teacher_permissions",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=default),
        )


def downgrade() -> None:
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("teacher_permissions", name)
