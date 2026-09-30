"""Add is_blocked to accounts.

Revision ID: d0e1f2a3b406
Revises: c9d0e1f2a305
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b406"
down_revision: str | None = "c9d0e1f2a305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "is_blocked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "is_blocked")
