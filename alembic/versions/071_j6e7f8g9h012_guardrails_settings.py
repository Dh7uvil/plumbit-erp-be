"""Add tenant commercial guardrail settings.

Revision ID: j6e7f8g9h012
Revises: i5d6e7f8g911
Create Date: 2026-09-29 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j6e7f8g9h012"
down_revision: str | None = "i5d6e7f8g911"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "invoice_policy",
            sa.String(length=30),
            server_default=sa.text("'bill_ahead'"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "returns_reopen_delivery",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "returns_reopen_delivery")
    op.drop_column("tenants", "invoice_policy")
