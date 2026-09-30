"""Winsoft parity: overdue-days credit policy threshold.

Revision ID: h4c5d6e7f810
Revises: g3b4c5d6e709
Create Date: 2026-09-29 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h4c5d6e7f810"
down_revision: str | None = "g3b4c5d6e709"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("overdue_days_threshold", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "overdue_days_threshold")
