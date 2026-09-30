"""M6 学员评估表：evaluations 表（家长会场景，FR-EV-01~05）

- 每学期/季度家长会前，教师基于学员近 3 个月课后反馈自动生成综合评估表
- content 结构化：{summary, strengths, progress, improvements, suggestions, subjects}
- status: draft → published（BR-05 草稿→人工审核→发布）
- 唯一约束：同一学员同一评估周期仅一份（幂等创建 = 更新）
- ai_draft：AI 生成原始草稿快照（含 model/素材摘要），供审计与回填

Revision ID: c0ffee000010
Revises: c0ffee000009
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000010"
down_revision: str | None = "c0ffee000009"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("students.id"), nullable=False, index=True),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("content", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column("ai_draft", JSONB(), nullable=True),
        sa.Column("ppt_url", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "published", name="evaluation_status", native_enum=False, length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("student_id", "period_start", "period_end", name="uq_evaluation_period"),
    )


def downgrade() -> None:
    op.drop_table("evaluations")
