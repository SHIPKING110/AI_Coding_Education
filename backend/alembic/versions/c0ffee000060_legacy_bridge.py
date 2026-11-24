# ruff: noqa: E501
"""Compatibility bridge for the deployed pre-baseline migration marker.

The production database is already at this revision, while the historical
migration source is not retained in this repository. This marker preserves
that deployed schema and allows new migrations to run without replaying history.
"""
from collections.abc import Sequence

revision: str = "c0ffee000060"
down_revision: str | None = "c00000000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
