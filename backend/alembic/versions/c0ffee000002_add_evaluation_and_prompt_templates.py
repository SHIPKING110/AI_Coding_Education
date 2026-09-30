"""M3 反馈增强2：课堂评价字段 + 提示词模板表

- feedbacks 新增 evaluation 列（课堂评价，AI 草稿写入的位置）
- 新建 prompt_templates 表（系统默认/个人自定义/管理员发布 三档）
- seed 3 套系统默认模板（scope=system）

Revision ID: c0ffee000002
Revises: c0ffee000001
Create Date: 2026-08-30

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000002"
down_revision: str | None = "c0ffee000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 3 套系统默认提示词模板（占位符由后端替换：{student_name} {class_name} {subject}
# {topic} {content} {performance} {homework} {evaluation}）
DEFAULT_TEMPLATES = [
    {
        "id": UUID("10000000-0000-4000-8000-000000000001"),
        "name": "通用鼓励型",
        "content": (
            "请为学员撰写一段课堂评价，要求：语气亲切、以鼓励为主，"
            "先肯定本节课的进步与亮点，再温和指出 1-2 个可提升点，最后给出鼓励性收尾。"
            "结合以下信息，不要编造不存在的内容：\n"
            "学员：{student_name}｜班级：{class_name}｜科目：{subject}\n"
            "课题：{topic}\n课程内容：{content}\n课堂表现：{performance}\n今日作业：{homework}"
        ),
    },
    {
        "id": UUID("10000000-0000-4000-8000-000000000002"),
        "name": "问题引导型",
        "content": (
            "请为学员撰写一段课堂评价，重点聚焦「可提升之处」，要求：客观具体地指出本节课"
            "暴露的问题或薄弱环节，并给出可执行的改进建议（如练习方法、课堂习惯），"
            "同时兼顾鼓励，避免打击孩子信心。结合以下信息，不要编造不存在的内容：\n"
            "学员：{student_name}｜班级：{class_name}｜科目：{subject}\n"
            "课题：{topic}\n课程内容：{content}\n课堂表现：{performance}\n今日作业：{homework}"
        ),
    },
    {
        "id": UUID("10000000-0000-4000-8000-000000000003"),
        "name": "亮点详述型",
        "content": (
            "请为学员撰写一段课堂评价，重点详述本节课的亮点与精彩表现，要求：抓住具体细节"
            "（如独立完成某道题、主动提问、帮助同学、专注时间长等）展开描述，让家长能清晰"
            "看到孩子的成长；若有作业，说明完成情况。结合以下信息，不要编造不存在的内容：\n"
            "学员：{student_name}｜班级：{class_name}｜科目：{subject}\n"
            "课题：{topic}\n课程内容：{content}\n课堂表现：{performance}\n今日作业：{homework}"
        ),
    },
]


def upgrade() -> None:
    # 1) feedbacks.evaluation（课堂评价）
    op.add_column("feedbacks", sa.Column("evaluation", sa.Text(), nullable=True))

    # 2) prompt_templates 表
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "system", "personal", "published",
                name="prompt_scope", native_enum=False, length=16,
            ),
            nullable=False,
            server_default="personal",
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 3) seed 系统默认模板
    prompt_templates = sa.table(
        "prompt_templates",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(100)),
        sa.column("content", sa.Text()),
        sa.column("scope", sa.String(16)),
        sa.column("owner_id", sa.Uuid()),
        sa.column("created_by", sa.Uuid()),
    )
    op.bulk_insert(
        prompt_templates,
        [
            {
                "id": t["id"],
                "name": t["name"],
                "content": t["content"],
                "scope": "system",
            }
            for t in DEFAULT_TEMPLATES
        ],
    )


def downgrade() -> None:
    op.drop_table("prompt_templates")
    op.drop_column("feedbacks", "evaluation")
