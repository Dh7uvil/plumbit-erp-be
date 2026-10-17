"""Add products.pieces_per_unit.

Revision ID: a6b7c8d9e085
Revises: f5a6b7c8d084
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6b7c8d9e085"
down_revision: str | None = "f5a6b7c8d084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("pieces_per_unit", sa.Numeric(18, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "pieces_per_unit")
