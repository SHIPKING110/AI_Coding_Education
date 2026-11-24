# ruff: noqa: E501
"""题库题号归一化（修复导入题目 order_no 从 2 开始的问题）

Revision ID: c00000000000
Revises: b00000000000
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c00000000000"
down_revision: str | None = "b00000000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("question_bank_questions"):
        return
    # 先改为负数，避开 (bank_set_id, order_no) 唯一约束，再按原顺序重排为 1..N
    op.execute("UPDATE question_bank_questions SET order_no = -order_no")
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY bank_set_id ORDER BY order_no DESC) AS rn
            FROM question_bank_questions
        )
        UPDATE question_bank_questions AS q
        SET order_no = ranked.rn
        FROM ranked
        WHERE q.id = ranked.id AND q.order_no <> ranked.rn
        """
    )


def downgrade() -> None:
    # 题号归一化不可逆；保留顺序信息即可
    pass
