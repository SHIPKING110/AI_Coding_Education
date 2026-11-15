"""Agent 记忆生命周期字段：category/importance/confidence/use_count/last_used_at。

支撑长期记忆的写入-强化-压缩-删除闭环与检索排序（相关度+强度+时间衰减）。

Revision ID: c0ffee000039
Revises: c0ffee000038
Create Date: 2026-10-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000039"
down_revision: str | None = "c0ffee000038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("agent_memories")}
    if "category" not in cols:
        op.add_column("agent_memories", sa.Column("category", sa.String(length=16), nullable=False, server_default="preference"))
    if "importance" not in cols:
        op.add_column("agent_memories", sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"))
    if "confidence" not in cols:
        op.add_column("agent_memories", sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"))
    if "use_count" not in cols:
        op.add_column("agent_memories", sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"))
    if "last_used_at" not in cols:
        op.add_column("agent_memories", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for c in ("last_used_at", "use_count", "confidence", "importance", "category"):
        op.drop_column("agent_memories", c)