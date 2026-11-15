"""认证硬化：强制改密标记（must_change_password）。

幂等说明：应用启动时 schema_ensure 会先行 ADD COLUMN 兜底，
本迁移先探测再执行，保证「先启应用后跑迁移」也不会失败。

Revision ID: c0ffee000061
Revises: c0ffee000060
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000061"
down_revision: str | None = "c0ffee000060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    # 管理员代建账号 / 重置密码后置 TRUE：登录后仅可访问改密接口直至完成改密
    if not _has_column("users", "must_change_password"):
        op.add_column(
            "users",
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _has_column("users", "must_change_password"):
        op.drop_column("users", "must_change_password")
