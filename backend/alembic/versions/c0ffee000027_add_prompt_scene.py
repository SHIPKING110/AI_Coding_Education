"""提示词模板使用场景：prompt_templates.scene（feedback/report/evaluation）

Revision ID: c0ffee000027
Revises: c0ffee000026
"""

from alembic import op

revision = "c0ffee000027"
down_revision = "c0ffee000026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS scene VARCHAR(32) DEFAULT 'feedback'"
    )
    op.execute(
        "UPDATE prompt_templates SET scene='report' "
        "WHERE (scene IS NULL OR scene='') AND name LIKE '【报告%'"
    )
    op.execute(
        "UPDATE prompt_templates SET scene='evaluation' "
        "WHERE (scene IS NULL OR scene='') AND name LIKE '【评估%'"
    )
    op.execute(
        "UPDATE prompt_templates SET scene='feedback' WHERE scene IS NULL OR scene=''"
    )
    op.execute(
        "UPDATE prompt_templates SET name='【报告·季度总结】复盘成长型' "
        "WHERE scope='system' AND name='【报告·季度总结】复盘 growth 型'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE prompt_templates DROP COLUMN IF EXISTS scene")
