"""Winsoft parity: customer credit hold flag.

Revision ID: g3b4c5d6e709
Revises: f2a3b4c5d608
Create Date: 2026-09-29 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g3b4c5d6e709"
down_revision: str | None = "f2a3b4c5d608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "credit_hold",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("customers", "credit_hold")
