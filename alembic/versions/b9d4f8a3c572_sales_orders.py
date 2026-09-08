"""Sales orders and sales order lines.

Revision ID: b9d4f8a3c572
Revises: a8c3e7f2b461
Create Date: 2026-09-08 18:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b9d4f8a3c572"
down_revision: str | Sequence[str] | None = "a8c3e7f2b461"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _pk() -> sa.Column:
    return sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", UUID, nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _soft_delete() -> sa.Column:
    return sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)


def _audit_users() -> list[sa.Column]:
    return [
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
    ]


def upgrade() -> None:
    """Create sales_orders and sales_order_lines."""

    op.create_table(
        "sales_orders",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("reference_number", sa.String(length=60), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_shipment_date", sa.Date(), nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("warehouse_id", UUID, nullable=True),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("customer_trn", sa.String(length=50), nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("place_of_supply", sa.String(length=30), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_list_id", UUID, nullable=True),
        sa.Column("payment_terms_id", UUID, nullable=True),
        sa.Column("salesperson_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms_and_conditions", sa.Text(), nullable=True),
        sa.Column("bill_to_snapshot", sa.Text(), nullable=True),
        sa.Column("ship_to_snapshot", sa.Text(), nullable=True),
        sa.Column("discount_type", sa.String(length=30), nullable=True),
        sa.Column("discount_value", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "discount_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "shipping_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "adjustment_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("subtotal", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("grand_total", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("foreign_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("base_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "fulfillment_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_DELIVERED'"),
            nullable=False,
        ),
        sa.Column(
            "billing_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_INVOICED'"),
            nullable=False,
        ),
        sa.Column("source_quotation_id", UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", UUID, nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_terms_id"], ["payment_terms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_quotation_id"], ["quotations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_orders_tenant_id", "sales_orders", ["tenant_id"])
    op.create_index("ix_sales_orders_branch_id", "sales_orders", ["branch_id"])
    op.create_index("ix_sales_orders_warehouse_id", "sales_orders", ["warehouse_id"])
    op.create_index("ix_sales_orders_customer_id", "sales_orders", ["customer_id"])
    op.create_index("ix_sales_orders_contact_id", "sales_orders", ["contact_id"])
    op.create_index("ix_sales_orders_currency_id", "sales_orders", ["currency_id"])
    op.create_index("ix_sales_orders_source_quotation_id", "sales_orders", ["source_quotation_id"])
    op.create_index("ix_sales_orders_tenant_id_status", "sales_orders", ["tenant_id", "status"])
    op.create_index(
        "ix_sales_orders_tenant_id_order_date", "sales_orders", ["tenant_id", "order_date"]
    )
    op.create_index(
        "ix_sales_orders_tenant_id_customer_id", "sales_orders", ["tenant_id", "customer_id"]
    )
    op.create_index(
        "uq_sales_orders_tenant_id_document_number_active",
        "sales_orders",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "sales_order_lines",
        _pk(),
        _tenant(),
        sa.Column("sales_order_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", sa.Numeric(18, 4), nullable=False),
        sa.Column("discount_type", sa.String(length=30), nullable=True),
        sa.Column("discount_value", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "discount_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("tax_rate", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("qty_delivered", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("qty_invoiced", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("source_quotation_line_id", UUID, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_quotation_line_id"], ["quotation_lines.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sales_order_id",
            "line_number",
            name="uq_sales_order_lines_header_line_number",
        ),
    )
    op.create_index("ix_sales_order_lines_tenant_id", "sales_order_lines", ["tenant_id"])
    op.create_index("ix_sales_order_lines_sales_order_id", "sales_order_lines", ["sales_order_id"])
    op.create_index("ix_sales_order_lines_product_id", "sales_order_lines", ["product_id"])


def downgrade() -> None:
    """Drop sales order tables."""

    op.drop_table("sales_order_lines")
    op.drop_table("sales_orders")
