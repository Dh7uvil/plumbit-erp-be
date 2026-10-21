"""Add warehouses.location_type.

Revision ID: b7c8d9e0f186
Revises: a6b7c8d9e085
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f186"
down_revision: str | None = "a6b7c8d9e085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "warehouses",
        sa.Column(
            "location_type",
            sa.String(20),
            nullable=False,
            server_default="WAREHOUSE",
        ),
    )


def downgrade() -> None:
    op.drop_column("warehouses", "location_type")
