"""Allow sales returns without a sales order for invoice-only delivery notes.

Revision ID: f3a4b5c6d192
Revises: e2f3a4b5c191
Create Date: 2026-09-23 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3a4b5c6d192"
down_revision: str | None = "e2f3a4b5c191"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "sales_returns",
        "sales_order_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "sales_returns",
        "sales_order_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
