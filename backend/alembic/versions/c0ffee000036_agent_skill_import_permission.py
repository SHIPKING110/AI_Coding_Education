"""权限管理新增开关：teacher_permissions.agent_skill_import（Agent 工作台·导入 ZIP 技能包）。

Revision ID: c0ffee000036
Revises: c0ffee000035
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee000036"
down_revision: str | None = "c0ffee000035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("teacher_permissions")]
    if "agent_skill_import" not in cols:
        # 默认 true：保持升级前的既有行为（默认允许导入）
        op.add_column(
            "teacher_permissions",
            sa.Column(
                "agent_skill_import",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    op.drop_column("teacher_permissions", "agent_skill_import")