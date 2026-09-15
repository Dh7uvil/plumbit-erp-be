"""Default tenants to Asia/Dubai timezone.

Revision ID: c4f8a0d2e135
Revises: b3e7f9c1d024
Create Date: 2026-09-15 13:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f8a0d2e135"
down_revision: str | None = "b3e7f9c1d024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN timezone SET DEFAULT 'Asia/Dubai'")
    op.execute("UPDATE tenants SET timezone = 'Asia/Dubai' WHERE timezone = 'UTC'")


def downgrade() -> None:
    op.execute("UPDATE tenants SET timezone = 'UTC' WHERE timezone = 'Asia/Dubai'")
    op.execute("ALTER TABLE tenants ALTER COLUMN timezone SET DEFAULT 'UTC'")
