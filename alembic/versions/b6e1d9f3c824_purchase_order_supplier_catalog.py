"""Snapshot supplier catalog references onto purchase order lines.

Revision ID: b6e1d9f3c824
Revises: a5d8c2e7b410
Create Date: 2026-09-09 14:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b6e1d9f3c824"
down_revision: str | Sequence[str] | None = "a5d8c2e7b410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    """Add supplier_product_id and supplier_sku snapshots on purchase order lines."""

    op.add_column(
        "purchase_order_lines",
        sa.Column("supplier_product_id", UUID, nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("supplier_sku", sa.String(length=80), nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_order_lines_supplier_product_id",
        "purchase_order_lines",
        "supplier_products",
        ["supplier_product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_purchase_order_lines_supplier_product_id",
        "purchase_order_lines",
        ["supplier_product_id"],
    )


def downgrade() -> None:
    """Drop catalog snapshots from purchase order lines."""

    op.drop_index(
        "ix_purchase_order_lines_supplier_product_id",
        table_name="purchase_order_lines",
    )
    op.drop_constraint(
        "fk_purchase_order_lines_supplier_product_id",
        "purchase_order_lines",
        type_="foreignkey",
    )
    op.drop_column("purchase_order_lines", "supplier_sku")
    op.drop_column("purchase_order_lines", "supplier_product_id")
