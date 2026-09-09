"""Proforma invoices, lines, and payment milestones.

Revision ID: d8a3b9c2e015
Revises: c7f2a8e1b904
Create Date: 2026-09-09 16:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d8a3b9c2e015"
down_revision: str | Sequence[str] | None = "c7f2a8e1b904"
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
    """Create proforma invoice tables."""

    op.create_table(
        "proforma_invoices",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("proforma_date", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
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
        sa.Column("source_quotation_id", UUID, nullable=True),
        sa.Column("incoterm", sa.String(length=20), nullable=True),
        sa.Column("incoterm_place", sa.String(length=120), nullable=True),
        sa.Column("port_of_loading", sa.String(length=120), nullable=True),
        sa.Column("port_of_discharge", sa.String(length=120), nullable=True),
        sa.Column("country_of_origin", sa.String(length=2), nullable=True),
        sa.Column("country_of_final_destination", sa.String(length=2), nullable=True),
        sa.Column("expected_shipment_date", sa.Date(), nullable=True),
        sa.Column(
            "partial_shipment_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "transhipment_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("bank_details_snapshot", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_by", UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", UUID, nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_by", UUID, nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_document_type", sa.String(length=30), nullable=True),
        sa.Column("converted_document_id", UUID, nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_terms_id"], ["payment_terms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_quotation_id"], ["quotations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["declined_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_proforma_invoices_tenant_id", "proforma_invoices", ["tenant_id"])
    op.create_index("ix_proforma_invoices_branch_id", "proforma_invoices", ["branch_id"])
    op.create_index("ix_proforma_invoices_customer_id", "proforma_invoices", ["customer_id"])
    op.create_index("ix_proforma_invoices_contact_id", "proforma_invoices", ["contact_id"])
    op.create_index("ix_proforma_invoices_currency_id", "proforma_invoices", ["currency_id"])
    op.create_index(
        "ix_proforma_invoices_tenant_id_status", "proforma_invoices", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_proforma_invoices_tenant_id_proforma_date",
        "proforma_invoices",
        ["tenant_id", "proforma_date"],
    )
    op.create_index(
        "ix_proforma_invoices_tenant_id_customer_id",
        "proforma_invoices",
        ["tenant_id", "customer_id"],
    )
    op.create_index(
        "ix_proforma_invoices_tenant_id_source_quotation_id",
        "proforma_invoices",
        ["tenant_id", "source_quotation_id"],
    )
    op.create_index(
        "uq_proforma_invoices_tenant_id_document_number_active",
        "proforma_invoices",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "proforma_invoice_lines",
        _pk(),
        _tenant(),
        sa.Column("proforma_invoice_id", UUID, nullable=False),
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
        sa.Column("source_quotation_line_id", UUID, nullable=True),
        sa.Column("hs_code", sa.String(length=20), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["proforma_invoice_id"], ["proforma_invoices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_quotation_line_id"], ["quotation_lines.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proforma_invoice_id",
            "line_number",
            name="uq_proforma_invoice_lines_header_line_number",
        ),
    )
    op.create_index(
        "ix_proforma_invoice_lines_tenant_id", "proforma_invoice_lines", ["tenant_id"]
    )
    op.create_index(
        "ix_proforma_invoice_lines_proforma_invoice_id",
        "proforma_invoice_lines",
        ["proforma_invoice_id"],
    )
    op.create_index(
        "ix_proforma_invoice_lines_product_id", "proforma_invoice_lines", ["product_id"]
    )

    op.create_table(
        "proforma_invoice_milestones",
        _pk(),
        _tenant(),
        sa.Column("proforma_invoice_id", UUID, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("net_days", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "computed_amount", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["proforma_invoice_id"], ["proforma_invoices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proforma_invoice_id",
            "sequence",
            name="uq_proforma_invoice_milestones_header_sequence",
        ),
    )
    op.create_index(
        "ix_proforma_invoice_milestones_tenant_id",
        "proforma_invoice_milestones",
        ["tenant_id"],
    )
    op.create_index(
        "ix_proforma_invoice_milestones_proforma_invoice_id",
        "proforma_invoice_milestones",
        ["proforma_invoice_id"],
    )


def downgrade() -> None:
    """Drop proforma invoice tables."""

    op.drop_index(
        "ix_proforma_invoice_milestones_proforma_invoice_id",
        table_name="proforma_invoice_milestones",
    )
    op.drop_index(
        "ix_proforma_invoice_milestones_tenant_id",
        table_name="proforma_invoice_milestones",
    )
    op.drop_table("proforma_invoice_milestones")
    op.drop_index(
        "ix_proforma_invoice_lines_product_id", table_name="proforma_invoice_lines"
    )
    op.drop_index(
        "ix_proforma_invoice_lines_proforma_invoice_id",
        table_name="proforma_invoice_lines",
    )
    op.drop_index("ix_proforma_invoice_lines_tenant_id", table_name="proforma_invoice_lines")
    op.drop_table("proforma_invoice_lines")
    op.drop_index(
        "uq_proforma_invoices_tenant_id_document_number_active",
        table_name="proforma_invoices",
    )
    op.drop_index(
        "ix_proforma_invoices_tenant_id_source_quotation_id",
        table_name="proforma_invoices",
    )
    op.drop_index(
        "ix_proforma_invoices_tenant_id_customer_id", table_name="proforma_invoices"
    )
    op.drop_index(
        "ix_proforma_invoices_tenant_id_proforma_date", table_name="proforma_invoices"
    )
    op.drop_index("ix_proforma_invoices_tenant_id_status", table_name="proforma_invoices")
    op.drop_index("ix_proforma_invoices_currency_id", table_name="proforma_invoices")
    op.drop_index("ix_proforma_invoices_contact_id", table_name="proforma_invoices")
    op.drop_index("ix_proforma_invoices_customer_id", table_name="proforma_invoices")
    op.drop_index("ix_proforma_invoices_branch_id", table_name="proforma_invoices")
    op.drop_index("ix_proforma_invoices_tenant_id", table_name="proforma_invoices")
    op.drop_table("proforma_invoices")
