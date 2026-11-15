"""删除订单独立权限键：teacher_permissions.order_visible（订单管理并入 finance_revenue）

Revision ID: c0ffee000029
Revises: c0ffee000028
"""

from alembic import op

revision = "c0ffee000029"
down_revision = "c0ffee000028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 先把旧键的已开通状态迁移到 finance_revenue，避免升级后权限收缩
    op.execute(
        "UPDATE teacher_permissions SET finance_revenue = true WHERE order_visible = true"
    )
    op.execute("ALTER TABLE teacher_permissions DROP COLUMN IF EXISTS order_visible")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE teacher_permissions ADD COLUMN IF NOT EXISTS order_visible BOOLEAN DEFAULT false"
    )
