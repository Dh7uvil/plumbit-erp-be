"""Customer receipts, supplier payments, allocations, and credit-control flags.

Revision ID: c8f1a4d6e209
Revises: b1c7e3a8d024
Create Date: 2026-09-11 11:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "c8f1a4d6e209"
down_revision: str | Sequence[str] | None = "b1c7e3a8d024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
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
    _add_tenant_flags()
    _create_customer_payment_table()
    _create_supplier_payment_table()
    _create_payment_allocation_table()
    _backfill_catalog_permissions()


def _add_tenant_flags() -> None:
    op.add_column(
        "tenants",
        sa.Column("vat_on_advances", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "auto_apply_advances_on_invoice",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "credit_limit_policy",
            sa.String(length=30),
            server_default=sa.text("'WARN'"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "credit_limit_include_open_orders",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def _create_customer_payment_table() -> None:
    op.create_table(
        "customer_payments",
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
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, nullable=False),
        sa.Column("amount_received", MONEY, nullable=False),
        sa.Column("bank_charges", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount_unapplied", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount_refunded", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("payment_account_id", UUID, nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("proforma_invoice_id", UUID, nullable=True),
        sa.Column("sales_order_id", UUID, nullable=True),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("refund_journal_entry_id", UUID, nullable=True),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("tax_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_by", UUID, nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["proforma_invoice_id"], ["proforma_invoices.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["refund_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["refunded_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_payments_tenant_id", "customer_payments", ["tenant_id"])
    op.create_index("ix_customer_payments_customer_id", "customer_payments", ["customer_id"])
    op.create_index("ix_customer_payments_currency_id", "customer_payments", ["currency_id"])
    op.create_index(
        "ix_customer_payments_tenant_id_status", "customer_payments", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_customer_payments_tenant_id_payment_date",
        "customer_payments",
        ["tenant_id", "payment_date"],
    )
    op.create_index(
        "ix_customer_payments_tenant_id_customer_id",
        "customer_payments",
        ["tenant_id", "customer_id"],
    )
    op.create_index(
        "ix_customer_payments_tenant_id_proforma_invoice_id",
        "customer_payments",
        ["tenant_id", "proforma_invoice_id"],
    )
    op.create_index(
        "ix_customer_payments_tenant_id_sales_order_id",
        "customer_payments",
        ["tenant_id", "sales_order_id"],
    )
    op.create_index(
        "uq_customer_payments_tenant_id_document_number_active",
        "customer_payments",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def _create_supplier_payment_table() -> None:
    op.create_table(
        "supplier_payments",
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
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("supplier_id", UUID, nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, nullable=False),
        sa.Column("amount_paid", MONEY, nullable=False),
        sa.Column("bank_charges", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount_unapplied", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("amount_refunded", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("payment_account_id", UUID, nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("purchase_order_id", UUID, nullable=True),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("refund_journal_entry_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_by", UUID, nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["refund_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["refunded_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplier_payments_tenant_id", "supplier_payments", ["tenant_id"])
    op.create_index("ix_supplier_payments_supplier_id", "supplier_payments", ["supplier_id"])
    op.create_index("ix_supplier_payments_currency_id", "supplier_payments", ["currency_id"])
    op.create_index(
        "ix_supplier_payments_tenant_id_status", "supplier_payments", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_supplier_payments_tenant_id_payment_date",
        "supplier_payments",
        ["tenant_id", "payment_date"],
    )
    op.create_index(
        "ix_supplier_payments_tenant_id_supplier_id",
        "supplier_payments",
        ["tenant_id", "supplier_id"],
    )
    op.create_index(
        "ix_supplier_payments_tenant_id_purchase_order_id",
        "supplier_payments",
        ["tenant_id", "purchase_order_id"],
    )
    op.create_index(
        "uq_supplier_payments_tenant_id_document_number_active",
        "supplier_payments",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def _create_payment_allocation_table() -> None:
    op.create_table(
        "payment_allocations",
        _pk(),
        _tenant(),
        sa.Column("payment_type", sa.String(length=40), nullable=False),
        sa.Column("payment_id", UUID, nullable=False),
        sa.Column("item_type", sa.String(length=40), nullable=False),
        sa.Column("item_id", UUID, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_allocations_tenant_id", "payment_allocations", ["tenant_id"])
    op.create_index(
        "ix_payment_allocations_tenant_payment",
        "payment_allocations",
        ["tenant_id", "payment_type", "payment_id"],
    )
    op.create_index(
        "ix_payment_allocations_tenant_item",
        "payment_allocations",
        ["tenant_id", "item_type", "item_id"],
    )
    op.create_index(
        "uq_payment_allocations_live_match",
        "payment_allocations",
        ["tenant_id", "payment_type", "payment_id", "item_type", "item_id"],
        unique=True,
        postgresql_where=sa.text("reversed_at IS NULL"),
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
    op.drop_table("payment_allocations")
    op.drop_table("supplier_payments")
    op.drop_table("customer_payments")
    op.drop_column("tenants", "credit_limit_include_open_orders")
    op.drop_column("tenants", "credit_limit_policy")
    op.drop_column("tenants", "auto_apply_advances_on_invoice")
    op.drop_column("tenants", "vat_on_advances")
