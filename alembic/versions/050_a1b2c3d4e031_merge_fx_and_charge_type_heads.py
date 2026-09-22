"""Merge document FX and charge-type migration branches.

Revision ID: a1b2c3d4e031
Revises: b8c1d4e7f020, c9f2a5b3d021
Create Date: 2026-09-22 14:00:00.000000
"""

from collections.abc import Sequence

revision: str = "a1b2c3d4e031"
down_revision: str | tuple[str, ...] | None = ("b8c1d4e7f020", "c9f2a5b3d021")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
