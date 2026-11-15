"""权限管理新增开关：teacher_permissions.agent_doc_upload（Agent 工作台·上传知识库文档）。

Revision ID: c0ffee000037
Revises: c0ffee000036
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000037"
down_revision: str | None = "c0ffee000036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("teacher_permissions")]
    if "agent_doc_upload" not in cols:
        op.add_column(
            "teacher_permissions",
            sa.Column(
                "agent_doc_upload",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    op.drop_column("teacher_permissions", "agent_doc_upload")