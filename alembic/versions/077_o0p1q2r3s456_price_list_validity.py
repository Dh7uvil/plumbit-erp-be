"""Price list validity date columns.

Revision ID: o0p1q2r3s456
Revises: n0i1j2k3l456
Create Date: 2026-09-29 23:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "o0p1q2r3s456"
down_revision: str | None = "n0i1j2k3l456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("price_lists", sa.Column("valid_from", sa.Date(), nullable=True))
    op.add_column("price_lists", sa.Column("valid_to", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("price_lists", "valid_to")
    op.drop_column("price_lists", "valid_from")
