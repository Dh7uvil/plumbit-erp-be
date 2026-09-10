"""Purchase invoices and goods-receipt qty_billed.

Revision ID: f5c9d3e1a246
Revises: e4b8c2d0f135
Create Date: 2026-09-10 20:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "f5c9d3e1a246"
down_revision: str | Sequence[str] | None = "e4b8c2d0f135"
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
        "goods_receipt_lines",
        sa.Column("qty_billed", QTY, server_default=sa.text("0"), nullable=False),
    )
    _create_purchase_invoice_tables()
    _backfill_catalog_permissions()


def _create_purchase_invoice_tables() -> None:
    op.create_table(
        "purchase_invoices",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("bill_type", sa.String(length=30), server_default=sa.text("'GOODS'"), nullable=False),
        sa.Column("supplier_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("supplier_trn", sa.String(length=50), nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("purchase_order_id", UUID, nullable=True),
        sa.Column("goods_receipt_id", UUID, nullable=True),
        sa.Column("supplier_invoice_number", sa.String(length=80), nullable=True),
        sa.Column("supplier_invoice_date", sa.Date(), nullable=True),
        sa.Column("payment_terms_id", UUID, nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("place_of_supply", sa.String(length=30), nullable=False),
        sa.Column("is_reverse_charge", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rcm_taxable_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("rcm_tax_amount", MONEY, server_default=sa.text("0"), nullable=False),
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
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("amount_paid", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount_debited", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("balance_due", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "payment_status",
            sa.String(length=30),
            server_default=sa.text("'UNPAID'"),
            nullable=False,
        ),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="SET NULL"),
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
    op.create_index("ix_purchase_invoices_tenant_id", "purchase_invoices", ["tenant_id"])
    op.create_index("ix_purchase_invoices_supplier_id", "purchase_invoices", ["supplier_id"])
    op.create_index("ix_purchase_invoices_branch_id", "purchase_invoices", ["branch_id"])
    op.create_index("ix_purchase_invoices_currency_id", "purchase_invoices", ["currency_id"])
    op.create_index(
        "ix_purchase_invoices_tenant_id_status", "purchase_invoices", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_purchase_invoices_tenant_id_invoice_date",
        "purchase_invoices",
        ["tenant_id", "invoice_date"],
    )
    op.create_index(
        "ix_purchase_invoices_tenant_id_supplier_id",
        "purchase_invoices",
        ["tenant_id", "supplier_id"],
    )
    op.create_index(
        "ix_purchase_invoices_tenant_id_purchase_order_id",
        "purchase_invoices",
        ["tenant_id", "purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_invoices_tenant_id_payment_status",
        "purchase_invoices",
        ["tenant_id", "payment_status"],
    )
    op.create_index(
        "uq_purchase_invoices_tenant_id_document_number_active",
        "purchase_invoices",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "purchase_invoice_lines",
        _pk(),
        _tenant(),
        sa.Column("purchase_invoice_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column(
            "line_type", sa.String(length=30), server_default=sa.text("'PRODUCT'"), nullable=False
        ),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", QTY, server_default=sa.text("1"), nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", MONEY, nullable=False),
        sa.Column("purchase_order_line_id", UUID, nullable=True),
        sa.Column("goods_receipt_id", UUID, nullable=True),
        sa.Column("goods_receipt_line_id", UUID, nullable=True),
        sa.Column("supplier_product_id", UUID, nullable=True),
        sa.Column("supplier_sku", sa.String(length=80), nullable=True),
        sa.Column("expense_account_id", UUID, nullable=True),
        sa.Column("expense_category", sa.String(length=30), nullable=True),
        sa.Column("discount_type", sa.String(length=30), nullable=True),
        sa.Column("discount_value", MONEY, nullable=True),
        sa.Column("discount_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("tax_rate", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("purchase_account_id", UUID, nullable=True),
        sa.Column("grn_unit_cost", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_debited", QTY, server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_id"], ["purchase_invoices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["purchase_order_line_id"], ["purchase_order_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["goods_receipt_line_id"], ["goods_receipt_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_product_id"], ["supplier_products.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["expense_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["purchase_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_invoice_id",
            "line_number",
            name="uq_purchase_invoice_lines_header_line_number",
        ),
    )
    op.create_index("ix_purchase_invoice_lines_tenant_id", "purchase_invoice_lines", ["tenant_id"])
    op.create_index(
        "ix_purchase_invoice_lines_purchase_invoice_id",
        "purchase_invoice_lines",
        ["purchase_invoice_id"],
    )
    op.create_index(
        "ix_purchase_invoice_lines_product_id", "purchase_invoice_lines", ["product_id"]
    )
    op.create_index(
        "ix_purchase_invoice_lines_purchase_order_line_id",
        "purchase_invoice_lines",
        ["purchase_order_line_id"],
    )
    op.create_index(
        "ix_purchase_invoice_lines_goods_receipt_line_id",
        "purchase_invoice_lines",
        ["goods_receipt_line_id"],
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
    op.drop_table("purchase_invoice_lines")
    op.drop_table("purchase_invoices")
    op.drop_column("goods_receipt_lines", "qty_billed")
