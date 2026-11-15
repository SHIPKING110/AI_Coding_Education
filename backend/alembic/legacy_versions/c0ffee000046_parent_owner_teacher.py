"""家长客服 P0+：threads.owner_teacher_id（归属教师：模块映射+Rerank 生效）。

Revision ID: c0ffee000046
Revises: c0ffee000045
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000046"
down_revision: str | None = "c0ffee000045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("parent_service_threads")}
    if "owner_teacher_id" not in cols:
        op.add_column(
            "parent_service_threads",
            sa.Column("owner_teacher_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_parent_threads_owner_teacher", "parent_service_threads",
            "users", ["owner_teacher_id"], ["id"], ondelete="SET NULL",
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("parent_service_threads")}
    if "ix_parent_service_threads_owner_teacher_id" not in indexes:
        op.create_index(
            "ix_parent_service_threads_owner_teacher_id",
            "parent_service_threads", ["owner_teacher_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("parent_service_threads")}
    if "ix_parent_service_threads_owner_teacher_id" in indexes:
        op.drop_index("ix_parent_service_threads_owner_teacher_id", table_name="parent_service_threads")
    try:
        op.drop_constraint("fk_parent_threads_owner_teacher", "parent_service_threads", type_="foreignkey")
    except Exception:
        pass
    cols = {c["name"] for c in sa.inspect(bind).get_columns("parent_service_threads")}
    if "owner_teacher_id" in cols:
        op.drop_column("parent_service_threads", "owner_teacher_id")
