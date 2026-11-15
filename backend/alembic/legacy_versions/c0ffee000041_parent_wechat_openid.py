"""家长客服 P0：users.wechat_openid（小程序登录绑定）。

Revision ID: c0ffee000041
Revises: c0ffee000040
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0ffee000041"
down_revision: str | None = "c0ffee000040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "wechat_openid" not in cols:
        op.add_column("users", sa.Column("wechat_openid", sa.String(length=64), nullable=True))
    # 唯一约束（已存在则跳过；名按约束命名约定）
    existing = {c["name"] for c in sa.inspect(bind).get_unique_constraints("users")}
    if "uq_users_wechat_openid" not in existing:
        op.create_unique_constraint("uq_users_wechat_openid", "users", ["wechat_openid"])
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("users")}
    if "ix_users_wechat_openid" not in indexes:
        op.create_index("ix_users_wechat_openid", "users", ["wechat_openid"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("users")}
    if "ix_users_wechat_openid" in indexes:
        op.drop_index("ix_users_wechat_openid", table_name="users")
    existing = {c["name"] for c in sa.inspect(bind).get_unique_constraints("users")}
    if "uq_users_wechat_openid" in existing:
        op.drop_constraint("uq_users_wechat_openid", "users", type_="unique")
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "wechat_openid" in cols:
        op.drop_column("users", "wechat_openid")
