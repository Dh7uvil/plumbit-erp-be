"""Partial conversion remaining qty and source document links.

Revision ID: b1c7e3a8d024
Revises: a6d0e4f2b357
Create Date: 2026-09-10 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b1c7e3a8d024"
down_revision: str | Sequence[str] | None = "a6d0e4f2b357"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(18, 6)


def upgrade() -> None:
    op.add_column(
        "quotation_lines",
        sa.Column("qty_converted", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "proforma_invoice_lines",
        sa.Column("qty_converted", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "proforma_invoices",
        sa.Column("source_sales_order_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_proforma_invoices_source_sales_order_id",
        "proforma_invoices",
        "sales_orders",
        ["source_sales_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_proforma_invoices_tenant_id_source_sales_order_id",
        "proforma_invoices",
        ["tenant_id", "source_sales_order_id"],
    )
    op.add_column(
        "proforma_invoice_lines",
        sa.Column("source_sales_order_line_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_proforma_invoice_lines_source_sales_order_line_id",
        "proforma_invoice_lines",
        "sales_order_lines",
        ["source_sales_order_line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "sales_order_lines",
        sa.Column("qty_converted", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "sales_invoices",
        sa.Column("source_quotation_id", UUID, nullable=True),
    )
    op.add_column(
        "sales_invoices",
        sa.Column("source_proforma_invoice_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_invoices_source_quotation_id",
        "sales_invoices",
        "quotations",
        ["source_quotation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sales_invoices_source_proforma_invoice_id",
        "sales_invoices",
        "proforma_invoices",
        ["source_proforma_invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sales_invoices_tenant_id_source_quotation_id",
        "sales_invoices",
        ["tenant_id", "source_quotation_id"],
    )
    op.create_index(
        "ix_sales_invoices_tenant_id_source_proforma_invoice_id",
        "sales_invoices",
        ["tenant_id", "source_proforma_invoice_id"],
    )
    op.add_column(
        "sales_invoice_lines",
        sa.Column("source_quotation_line_id", UUID, nullable=True),
    )
    op.add_column(
        "sales_invoice_lines",
        sa.Column("source_proforma_invoice_line_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_invoice_lines_source_quotation_line_id",
        "sales_invoice_lines",
        "quotation_lines",
        ["source_quotation_line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sales_invoice_lines_source_proforma_invoice_line_id",
        "sales_invoice_lines",
        "proforma_invoice_lines",
        ["source_proforma_invoice_line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sales_invoice_lines_source_quotation_line_id",
        "sales_invoice_lines",
        ["source_quotation_line_id"],
    )
    op.create_index(
        "ix_sales_invoice_lines_source_proforma_invoice_line_id",
        "sales_invoice_lines",
        ["source_proforma_invoice_line_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sales_invoice_lines_source_proforma_invoice_line_id",
        table_name="sales_invoice_lines",
    )
    op.drop_index(
        "ix_sales_invoice_lines_source_quotation_line_id",
        table_name="sales_invoice_lines",
    )
    op.drop_constraint(
        "fk_sales_invoice_lines_source_proforma_invoice_line_id",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_sales_invoice_lines_source_quotation_line_id",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("sales_invoice_lines", "source_proforma_invoice_line_id")
    op.drop_column("sales_invoice_lines", "source_quotation_line_id")
    op.drop_index(
        "ix_sales_invoices_tenant_id_source_proforma_invoice_id",
        table_name="sales_invoices",
    )
    op.drop_index(
        "ix_sales_invoices_tenant_id_source_quotation_id",
        table_name="sales_invoices",
    )
    op.drop_constraint(
        "fk_sales_invoices_source_proforma_invoice_id",
        "sales_invoices",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_sales_invoices_source_quotation_id",
        "sales_invoices",
        type_="foreignkey",
    )
    op.drop_column("sales_invoices", "source_proforma_invoice_id")
    op.drop_column("sales_invoices", "source_quotation_id")
    op.drop_column("sales_order_lines", "qty_converted")
    op.drop_constraint(
        "fk_proforma_invoice_lines_source_sales_order_line_id",
        "proforma_invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("proforma_invoice_lines", "source_sales_order_line_id")
    op.drop_index(
        "ix_proforma_invoices_tenant_id_source_sales_order_id",
        table_name="proforma_invoices",
    )
    op.drop_constraint(
        "fk_proforma_invoices_source_sales_order_id",
        "proforma_invoices",
        type_="foreignkey",
    )
    op.drop_column("proforma_invoices", "source_sales_order_id")
    op.drop_column("proforma_invoice_lines", "qty_converted")
    op.drop_column("quotation_lines", "qty_converted")
