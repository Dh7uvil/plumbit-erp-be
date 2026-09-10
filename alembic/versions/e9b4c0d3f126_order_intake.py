"""Sales order customer PO, PFI source, and back-to-back purchase order links.

Revision ID: e9b4c0d3f126
Revises: d8a3b9c2e015
Create Date: 2026-09-09 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e9b4c0d3f126"
down_revision: str | Sequence[str] | None = "d8a3b9c2e015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    """Add order-intake columns to sales and purchase orders."""

    op.add_column("sales_orders", sa.Column("source_proforma_invoice_id", UUID, nullable=True))
    op.add_column(
        "sales_orders", sa.Column("customer_po_number", sa.String(length=60), nullable=True)
    )
    op.add_column("sales_orders", sa.Column("customer_po_date", sa.Date(), nullable=True))
    op.add_column(
        "sales_orders", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sales_orders", sa.Column("acknowledged_by", UUID, nullable=True))
    op.create_foreign_key(
        "fk_sales_orders_source_proforma_invoice_id",
        "sales_orders",
        "proforma_invoices",
        ["source_proforma_invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sales_orders_acknowledged_by",
        "sales_orders",
        "users",
        ["acknowledged_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sales_orders_source_proforma_invoice_id",
        "sales_orders",
        ["source_proforma_invoice_id"],
    )
    op.create_index(
        "ix_sales_orders_tenant_id_customer_id_customer_po_number",
        "sales_orders",
        ["tenant_id", "customer_id", "customer_po_number"],
    )

    op.add_column(
        "sales_order_lines",
        sa.Column("source_proforma_invoice_line_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_order_lines_source_proforma_invoice_line_id",
        "sales_order_lines",
        "proforma_invoice_lines",
        ["source_proforma_invoice_line_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("purchase_orders", sa.Column("source_sales_order_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_purchase_orders_source_sales_order_id",
        "purchase_orders",
        "sales_orders",
        ["source_sales_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_purchase_orders_source_sales_order_id",
        "purchase_orders",
        ["source_sales_order_id"],
    )
    op.create_index(
        "ix_purchase_orders_tenant_id_source_sales_order_id",
        "purchase_orders",
        ["tenant_id", "source_sales_order_id"],
    )

    op.add_column(
        "purchase_order_lines",
        sa.Column("source_sales_order_line_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_order_lines_source_sales_order_line_id",
        "purchase_order_lines",
        "sales_order_lines",
        ["source_sales_order_line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_purchase_order_lines_source_sales_order_line_id",
        "purchase_order_lines",
        ["source_sales_order_line_id"],
    )


def downgrade() -> None:
    """Drop order-intake columns."""

    op.drop_index(
        "ix_purchase_order_lines_source_sales_order_line_id",
        table_name="purchase_order_lines",
    )
    op.drop_constraint(
        "fk_purchase_order_lines_source_sales_order_line_id",
        "purchase_order_lines",
        type_="foreignkey",
    )
    op.drop_column("purchase_order_lines", "source_sales_order_line_id")

    op.drop_index(
        "ix_purchase_orders_tenant_id_source_sales_order_id",
        table_name="purchase_orders",
    )
    op.drop_index("ix_purchase_orders_source_sales_order_id", table_name="purchase_orders")
    op.drop_constraint(
        "fk_purchase_orders_source_sales_order_id",
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_column("purchase_orders", "source_sales_order_id")

    op.drop_constraint(
        "fk_sales_order_lines_source_proforma_invoice_line_id",
        "sales_order_lines",
        type_="foreignkey",
    )
    op.drop_column("sales_order_lines", "source_proforma_invoice_line_id")

    op.drop_index(
        "ix_sales_orders_tenant_id_customer_id_customer_po_number",
        table_name="sales_orders",
    )
    op.drop_index("ix_sales_orders_source_proforma_invoice_id", table_name="sales_orders")
    op.drop_constraint("fk_sales_orders_acknowledged_by", "sales_orders", type_="foreignkey")
    op.drop_constraint(
        "fk_sales_orders_source_proforma_invoice_id",
        "sales_orders",
        type_="foreignkey",
    )
    op.drop_column("sales_orders", "acknowledged_by")
    op.drop_column("sales_orders", "acknowledged_at")
    op.drop_column("sales_orders", "customer_po_date")
    op.drop_column("sales_orders", "customer_po_number")
    op.drop_column("sales_orders", "source_proforma_invoice_id")
