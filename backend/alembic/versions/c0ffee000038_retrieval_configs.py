"""检索模型配置：系统级 Embedding（单例）+ 教师级 Rerank。

embedding 收敛为系统级的原因：单一向量集合不能混存不同 embedding 的向量
（不同向量空间会跨教师串味、维度不同会查询失败）。指纹变化即落到新集合。

Revision ID: c0ffee000038
Revises: c0ffee000037
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000038"
down_revision: str | None = "c0ffee000037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "system_embedding_config" not in insp.get_table_names():
        op.create_table(
            "system_embedding_config",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=16), nullable=False, server_default="remote"),
            sa.Column("base_url", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("api_key_enc", sa.Text(), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("model_path", sa.String(length=256), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "teacher_rerank_configs" not in insp.get_table_names():
        op.create_table(
            "teacher_rerank_configs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("owner_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=16), nullable=False, server_default="remote"),
            sa.Column("base_url", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("api_key_enc", sa.Text(), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("model_path", sa.String(length=256), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_teacher_rerank_configs_owner_id", "teacher_rerank_configs", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_teacher_rerank_configs_owner_id", table_name="teacher_rerank_configs")
    op.drop_table("teacher_rerank_configs")
    op.drop_table("system_embedding_config")