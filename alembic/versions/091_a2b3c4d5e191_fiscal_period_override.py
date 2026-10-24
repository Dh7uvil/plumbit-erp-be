"""Optional fiscal period override on vouchers and cost sheets.

Revision ID: a2b3c4d5e191
Revises: f1a2b3c4d190
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e191"
down_revision: str | None = "f1a2b3c4d190"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vouchers",
        sa.Column("fiscal_period", sa.Integer(), nullable=True),
    )
    op.add_column(
        "cost_sheets",
        sa.Column("fiscal_period", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cost_sheets", "fiscal_period")
    op.drop_column("vouchers", "fiscal_period")
