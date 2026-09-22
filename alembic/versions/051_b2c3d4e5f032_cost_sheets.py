"""Import/export cost sheet tables.

Revision ID: b2c3d4e5f032
Revises: a1b2c3d4e031
Create Date: 2026-09-22 14:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2c3d4e5f032"
down_revision: str | None = "a1b2c3d4e031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_QTY = sa.Numeric(18, 6)
_MONEY = sa.Numeric(18, 4)
_RATE = sa.Numeric(18, 6)


def upgrade() -> None:
    op.create_table(
        "cost_sheets",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("document_number", sa.String(40), nullable=False),
        sa.Column("sheet_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("purchase_order_id", UUID, nullable=True),
        sa.Column("supplier_id", UUID, nullable=True),
        sa.Column("customer_id", UUID, nullable=True),
        sa.Column("proforma_invoice_id", UUID, nullable=True),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", _RATE, nullable=False),
        sa.Column("incoterm", sa.String(10), nullable=True),
        sa.Column("port_of_loading", sa.String(120), nullable=True),
        sa.Column("port_of_discharge", sa.String(120), nullable=True),
        sa.Column("allocation_method", sa.String(20), server_default=sa.text("'VALUE'"), nullable=False),
        sa.Column("landed_cost_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["landed_cost_id"], ["landed_costs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proforma_invoice_id"], ["proforma_invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cost_sheets_tenant_id_document_date",
        "cost_sheets",
        ["tenant_id", "document_date"],
    )
    op.create_index("ix_cost_sheets_tenant_id_sheet_type", "cost_sheets", ["tenant_id", "sheet_type"])
    op.create_index("ix_cost_sheets_tenant_id_status", "cost_sheets", ["tenant_id", "status"])
    op.create_index(
        "uq_cost_sheets_tenant_id_document_number_active",
        "cost_sheets",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "cost_sheet_lines",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cost_sheet_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("unit_id", UUID, nullable=False),
        sa.Column("quantity", _QTY, nullable=False),
        sa.Column("base_rate", _MONEY, nullable=False),
        sa.Column("target_selling_price", _MONEY, nullable=True),
        sa.Column("goods_receipt_line_id", UUID, nullable=True),
        sa.ForeignKeyConstraint(["cost_sheet_id"], ["cost_sheets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goods_receipt_line_id"], ["goods_receipt_lines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cost_sheet_id", "line_number", name="uq_cost_sheet_lines_header_line"),
    )
    op.create_index("ix_cost_sheet_lines_cost_sheet_id", "cost_sheet_lines", ["cost_sheet_id"])

    op.create_table(
        "cost_sheet_charges",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cost_sheet_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("charge_type_id", UUID, nullable=False),
        sa.Column("estimated_amount", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("actual_amount", _MONEY, nullable=True),
        sa.Column("allocation_basis", sa.String(20), nullable=True),
        sa.Column("purchase_invoice_id", UUID, nullable=True),
        sa.Column("purchase_invoice_line_id", UUID, nullable=True),
        sa.ForeignKeyConstraint(["charge_type_id"], ["charge_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cost_sheet_id"], ["cost_sheets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_invoice_id"], ["purchase_invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_line_id"], ["purchase_invoice_lines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cost_sheet_id", "line_number", name="uq_cost_sheet_charges_header_line"),
    )
    op.create_index("ix_cost_sheet_charges_charge_type_id", "cost_sheet_charges", ["charge_type_id"])
    op.create_index("ix_cost_sheet_charges_cost_sheet_id", "cost_sheet_charges", ["cost_sheet_id"])

    op.execute(
        """
        INSERT INTO document_sequences (
            id, tenant_id, document_type, series, fiscal_year, prefix, next_number, padding, is_active, created_at, updated_at
        )
        SELECT gen_random_uuid(), t.id, dt.document_type, dt.series, EXTRACT(YEAR FROM CURRENT_DATE)::int, dt.series, 1, 6, true, now(), now()
        FROM tenants t
        CROSS JOIN (
            VALUES ('COST_SHEET_IMPORT', 'CSI'), ('COST_SHEET_EXPORT', 'CSE')
        ) AS dt(document_type, series)
        WHERE NOT EXISTS (
            SELECT 1 FROM document_sequences ds
            WHERE ds.tenant_id = t.id AND ds.document_type = dt.document_type AND ds.deleted_at IS NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_table("cost_sheet_charges")
    op.drop_table("cost_sheet_lines")
    op.drop_table("cost_sheets")
