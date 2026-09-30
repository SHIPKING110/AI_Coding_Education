"""职务标签 + 职务预设 + 全局个性化：users.title、job_titles、system_settings

Revision ID: c0ffee000023
Revises: c0ffee000022
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000023"
down_revision: str | None = "c0ffee000022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("title", sa.String(64), nullable=True))
    op.create_index("ix_users_title", "users", ["title"])
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_titles (
            id UUID PRIMARY KEY,
            name VARCHAR(64) NOT NULL UNIQUE,
            permissions JSON NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_titles_name ON job_titles (name)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY,
            login_theme VARCHAR(32) NOT NULL DEFAULT 'default',
            desktop_bg VARCHAR(512) NOT NULL DEFAULT 'default',
            ui_theme VARCHAR(32) NOT NULL DEFAULT 'default',
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        "INSERT INTO system_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_table("job_titles")
    op.drop_index("ix_users_title", table_name="users")
    op.drop_column("users", "title")
