"""Sales invoices and delivery-note qty_invoiced.

Revision ID: e4b8c2d0f135
Revises: d2e5f9b7c013
Create Date: 2026-09-10 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "e4b8c2d0f135"
down_revision: str | Sequence[str] | None = "d2e5f9b7c013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(18, 6)
MONEY = sa.Numeric(18, 4)
RATE = sa.Numeric(18, 6)


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
    """Apply this revision."""
    op.add_column(
        "delivery_note_lines",
        sa.Column("qty_invoiced", QTY, server_default=sa.text("0"), nullable=False),
    )
    _create_sales_invoice_tables()
    _backfill_catalog_permissions()


def _create_sales_invoice_tables() -> None:
    op.create_table(
        "sales_invoices",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("customer_trn", sa.String(length=50), nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("salesperson_id", UUID, nullable=True),
        sa.Column("sales_order_id", UUID, nullable=True),
        sa.Column("payment_terms_id", UUID, nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("place_of_supply", sa.String(length=30), nullable=False),
        sa.Column("is_export", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, nullable=False),
        sa.Column("discount_type", sa.String(length=30), nullable=True),
        sa.Column("discount_value", MONEY, nullable=True),
        sa.Column("discount_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("shipping_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("adjustment_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("subtotal", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("round_off_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("grand_total", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("foreign_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("base_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("bill_to_snapshot", sa.Text(), nullable=True),
        sa.Column("ship_to_snapshot", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms_and_conditions", sa.Text(), nullable=True),
        sa.Column("amount_paid", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount_credited", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("balance_due", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "payment_status",
            sa.String(length=30),
            server_default=sa.text("'UNPAID'"),
            nullable=False,
        ),
        sa.Column("cogs_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cogs_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_APPLICABLE'"),
            nullable=False,
        ),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("export_evidence_ok", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("export_evidence_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_terms_id"], ["payment_terms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_invoices_tenant_id", "sales_invoices", ["tenant_id"])
    op.create_index("ix_sales_invoices_customer_id", "sales_invoices", ["customer_id"])
    op.create_index("ix_sales_invoices_contact_id", "sales_invoices", ["contact_id"])
    op.create_index("ix_sales_invoices_branch_id", "sales_invoices", ["branch_id"])
    op.create_index("ix_sales_invoices_currency_id", "sales_invoices", ["currency_id"])
    op.create_index("ix_sales_invoices_tenant_id_status", "sales_invoices", ["tenant_id", "status"])
    op.create_index(
        "ix_sales_invoices_tenant_id_invoice_date",
        "sales_invoices",
        ["tenant_id", "invoice_date"],
    )
    op.create_index(
        "ix_sales_invoices_tenant_id_customer_id",
        "sales_invoices",
        ["tenant_id", "customer_id"],
    )
    op.create_index(
        "ix_sales_invoices_tenant_id_sales_order_id",
        "sales_invoices",
        ["tenant_id", "sales_order_id"],
    )
    op.create_index(
        "ix_sales_invoices_tenant_id_payment_status",
        "sales_invoices",
        ["tenant_id", "payment_status"],
    )
    op.create_index(
        "uq_sales_invoices_tenant_id_document_number_active",
        "sales_invoices",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "sales_invoice_lines",
        _pk(),
        _tenant(),
        sa.Column("sales_invoice_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", MONEY, nullable=False),
        sa.Column("sales_order_line_id", UUID, nullable=True),
        sa.Column("delivery_note_id", UUID, nullable=True),
        sa.Column("delivery_note_line_id", UUID, nullable=True),
        sa.Column("discount_type", sa.String(length=30), nullable=True),
        sa.Column("discount_value", MONEY, nullable=True),
        sa.Column("discount_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("tax_rate", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("income_account_id", UUID, nullable=True),
        sa.Column("cogs_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cogs_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_APPLICABLE'"),
            nullable=False,
        ),
        sa.Column("qty_credited", QTY, server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_invoice_id"], ["sales_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["sales_order_line_id"], ["sales_order_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["delivery_note_id"], ["delivery_notes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["delivery_note_line_id"], ["delivery_note_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["income_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sales_invoice_id",
            "line_number",
            name="uq_sales_invoice_lines_header_line_number",
        ),
    )
    op.create_index("ix_sales_invoice_lines_tenant_id", "sales_invoice_lines", ["tenant_id"])
    op.create_index(
        "ix_sales_invoice_lines_sales_invoice_id",
        "sales_invoice_lines",
        ["sales_invoice_id"],
    )
    op.create_index("ix_sales_invoice_lines_product_id", "sales_invoice_lines", ["product_id"])
    op.create_index(
        "ix_sales_invoice_lines_sales_order_line_id",
        "sales_invoice_lines",
        ["sales_order_line_id"],
    )
    op.create_index(
        "ix_sales_invoice_lines_delivery_note_line_id",
        "sales_invoice_lines",
        ["delivery_note_line_id"],
    )


def _backfill_catalog_permissions() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_catalog_permissions()

    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for parsed in catalog:
            key = (parsed.module, parsed.resource, parsed.action)
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, :module, :resource, :action)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "module": parsed.module,
                    "resource": parsed.resource,
                    "action": parsed.action,
                },
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND is_system_role = true
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if admin is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                    SELECT :tenant_id, :role_id, p.id
                    FROM permissions p
                    WHERE p.tenant_id = :tenant_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM role_permissions rp
                        WHERE rp.tenant_id = :tenant_id
                          AND rp.role_id = :role_id
                          AND rp.permission_id = p.id
                      )
                    """
                ),
                {"tenant_id": tenant_id, "role_id": admin.id},
            )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_table("sales_invoice_lines")
    op.drop_table("sales_invoices")
    op.drop_column("delivery_note_lines", "qty_invoiced")
