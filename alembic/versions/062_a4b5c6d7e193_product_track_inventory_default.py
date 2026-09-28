"""Default new products to track inventory.

Revision ID: a4b5c6d7e193
Revises: f3a4b5c6d192
Create Date: 2026-09-28 17:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e193"
down_revision: str | None = "f3a4b5c6d192"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "track_inventory",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "track_inventory",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
        existing_nullable=False,
    )
