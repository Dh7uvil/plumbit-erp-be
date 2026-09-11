"""add tenant logo storage key

Revision ID: a9f2d6e3b718
Revises: c3d9e8f1a204
Create Date: 2026-08-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9f2d6e3b718"
down_revision: str | Sequence[str] | None = "c3d9e8f1a204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the object key for the current tenant logo."""

    op.add_column("tenants", sa.Column("logo_storage_key", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Drop the tenant logo object key."""

    op.drop_column("tenants", "logo_storage_key")
