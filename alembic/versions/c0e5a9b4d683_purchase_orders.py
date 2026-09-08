"""Purchase orders and purchase order lines.

Revision ID: c0e5a9b4d683
Revises: b9d4f8a3c572
Create Date: 2026-09-08 18:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0e5a9b4d683"
down_revision: str | Sequence[str] | None = "b9d4f8a3c572"
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
    """Create purchase_orders and purchase_order_lines."""

    op.create_table(
        "purchase_orders",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("reference_number", sa.String(length=60), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("warehouse_id", UUID, nullable=True),
        sa.Column("supplier_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("supplier_trn", sa.String(length=50), nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("place_of_supply", sa.String(length=30), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("payment_terms_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms_and_conditions", sa.Text(), nullable=True),
        sa.Column("supplier_address_snapshot", sa.Text(), nullable=True),
        sa.Column("deliver_to_snapshot", sa.Text(), nullable=True),
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
            "receipt_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_RECEIVED'"),
            nullable=False,
        ),
        sa.Column(
            "billing_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_INVOICED'"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", UUID, nullable=True),
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
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_terms_id"], ["payment_terms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_orders_tenant_id", "purchase_orders", ["tenant_id"])
    op.create_index("ix_purchase_orders_branch_id", "purchase_orders", ["branch_id"])
    op.create_index("ix_purchase_orders_warehouse_id", "purchase_orders", ["warehouse_id"])
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_contact_id", "purchase_orders", ["contact_id"])
    op.create_index("ix_purchase_orders_currency_id", "purchase_orders", ["currency_id"])
    op.create_index(
        "ix_purchase_orders_tenant_id_status", "purchase_orders", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_purchase_orders_tenant_id_order_date", "purchase_orders", ["tenant_id", "order_date"]
    )
    op.create_index(
        "ix_purchase_orders_tenant_id_supplier_id",
        "purchase_orders",
        ["tenant_id", "supplier_id"],
    )
    op.create_index(
        "uq_purchase_orders_tenant_id_document_number_active",
        "purchase_orders",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "purchase_order_lines",
        _pk(),
        _tenant(),
        sa.Column("purchase_order_id", UUID, nullable=False),
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
        sa.Column("qty_received", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("qty_billed", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_order_id",
            "line_number",
            name="uq_purchase_order_lines_header_line_number",
        ),
    )
    op.create_index("ix_purchase_order_lines_tenant_id", "purchase_order_lines", ["tenant_id"])
    op.create_index(
        "ix_purchase_order_lines_purchase_order_id",
        "purchase_order_lines",
        ["purchase_order_id"],
    )
    op.create_index("ix_purchase_order_lines_product_id", "purchase_order_lines", ["product_id"])


def downgrade() -> None:
    """Drop purchase order tables."""

    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
