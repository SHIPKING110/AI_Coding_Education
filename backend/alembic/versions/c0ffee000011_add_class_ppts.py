"""M6 班级家长会 PPT 记录表：class_ppts（文案落库，支持预览/编辑/秒级重排版）

- AI 提炼的班级汇报文案 + 班级素材快照（stats/averages/honor_roll）落库
- 同一班级同一周期仅一份（重新生成 = 覆盖更新）
- 编辑文案后用快照直接重排版，不再调用 LLM

Revision ID: c0ffee000011
Revises: c0ffee000010
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000011"
down_revision: str | None = "c0ffee000010"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class_ppts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("classes.id"), nullable=False, index=True),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("content", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column("averages", JSONB(), nullable=True),
        sa.Column("honor_roll", JSONB(), nullable=True),
        sa.Column("ppt_url", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("class_id", "period_start", "period_end", name="uq_class_ppt_period"),
    )


def downgrade() -> None:
    op.drop_table("class_ppts")
