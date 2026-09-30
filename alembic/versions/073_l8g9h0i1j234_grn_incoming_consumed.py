"""Add goods_receipt_lines.incoming_consumed for PO incoming restore.

Revision ID: l8g9h0i1j234
Revises: k7f8g9h0i123
Create Date: 2026-09-29 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l8g9h0i1j234"
down_revision: str | None = "k7f8g9h0i123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QTY = sa.Numeric(18, 6)


def upgrade() -> None:
    op.add_column(
        "goods_receipt_lines",
        sa.Column("incoming_consumed", _QTY, server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("goods_receipt_lines", "incoming_consumed")
