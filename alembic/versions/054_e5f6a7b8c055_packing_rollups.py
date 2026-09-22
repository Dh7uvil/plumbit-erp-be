"""Sales order packing fields and package/shipment CBM rollups.

Revision ID: e5f6a7b8c055
Revises: d4e5f6a7b044
Create Date: 2026-09-22 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c055"
down_revision: str | None = "d4e5f6a7b044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QTY = sa.Numeric(18, 6)


def upgrade() -> None:
    op.add_column("sales_order_lines", sa.Column("carton_qty", _QTY, nullable=True))
    op.add_column("sales_order_lines", sa.Column("packing_unit", sa.String(40), nullable=True))
    op.add_column("sales_order_lines", sa.Column("cbm", _QTY, nullable=True))
    op.add_column("sales_order_lines", sa.Column("weight", _QTY, nullable=True))
    op.add_column("sales_order_lines", sa.Column("item_code", sa.String(80), nullable=True))
    op.add_column("packages", sa.Column("total_cbm", _QTY, nullable=True))
    op.add_column("shipments", sa.Column("total_cbm", _QTY, nullable=True))


def downgrade() -> None:
    op.drop_column("shipments", "total_cbm")
    op.drop_column("packages", "total_cbm")
    op.drop_column("sales_order_lines", "item_code")
    op.drop_column("sales_order_lines", "weight")
    op.drop_column("sales_order_lines", "cbm")
    op.drop_column("sales_order_lines", "packing_unit")
    op.drop_column("sales_order_lines", "carton_qty")
