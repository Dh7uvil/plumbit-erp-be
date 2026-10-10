"""Winsoft legacy parity: masters and commercial header fields.

Revision ID: a1b2c3d4e080
Revises: q2r3s4t5u678
Create Date: 2026-10-10 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e080"
down_revision: str | None = "q2r3s4t5u678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_MONEY = sa.Numeric(18, 4)
_QTY = sa.Numeric(18, 6)

_COMMERCIAL = (
    "sales_invoices",
    "purchase_invoices",
    "credit_notes",
    "debit_notes",
    "quotations",
    "sales_orders",
    "purchase_orders",
)
# Created in 011 (sales orders) and 012 (purchase orders).
_HAS_REFERENCE_NUMBER = frozenset({"sales_orders", "purchase_orders"})


def upgrade() -> None:
    op.create_table(
        "financial_categories",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("account_subtype", sa.String(30), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_financial_categories_tenant_name"),
    )
    op.create_index("ix_financial_categories_tenant_id", "financial_categories", ["tenant_id"])

    op.add_column("accounts", sa.Column("default_tax_id", UUID, nullable=True))
    op.add_column("accounts", sa.Column("financial_category_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_accounts_default_tax_id",
        "accounts",
        "taxes",
        ["default_tax_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_accounts_financial_category_id",
        "accounts",
        "financial_categories",
        ["financial_category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("products", sa.Column("brand", sa.String(120), nullable=True))
    op.add_column("products", sa.Column("origin_country_code", sa.String(2), nullable=True))
    op.add_column("products", sa.Column("engine", sa.String(80), nullable=True))
    op.add_column("products", sa.Column("alias_2", sa.String(80), nullable=True))
    op.add_column("products", sa.Column("alias_3", sa.String(80), nullable=True))
    op.add_column("products", sa.Column("alias_4", sa.String(80), nullable=True))
    op.add_column("products", sa.Column("rem", sa.String(200), nullable=True))
    op.add_column("products", sa.Column("remarks", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("max_level", _QTY, nullable=True))
    op.add_column("products", sa.Column("default_reorder_level", _QTY, nullable=True))
    op.add_column("products", sa.Column("net_weight", _QTY, nullable=True))
    op.add_column("products", sa.Column("gross_weight", _QTY, nullable=True))
    op.add_column(
        "products",
        sa.Column("price_1", _MONEY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("price_2", _MONEY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "products",
        sa.Column(
            "stock_input_disabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("products", sa.Column("secondary_unit_id", UUID, nullable=True))
    op.add_column("products", sa.Column("secondary_unit_factor", _QTY, nullable=True))
    op.create_foreign_key(
        "fk_products_secondary_unit_id",
        "products",
        "units",
        ["secondary_unit_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("addresses", sa.Column("address_line_3", sa.String(200), nullable=True))
    op.add_column("customers", sa.Column("fax", sa.String(40), nullable=True))
    op.add_column("customers", sa.Column("email", sa.String(200), nullable=True))
    op.add_column("customers", sa.Column("phone", sa.String(40), nullable=True))
    op.add_column(
        "customers",
        sa.Column(
            "invoice_type",
            sa.String(20),
            server_default=sa.text("'ALL'"),
            nullable=False,
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "supplier_origin",
            sa.String(20),
            server_default=sa.text("'LOCAL'"),
            nullable=False,
        ),
    )

    op.create_table(
        "sales_targets",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "employee_id",
            UUID,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("amount", _MONEY, server_default=sa.text("0"), nullable=False),
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
        sa.UniqueConstraint(
            "tenant_id",
            "employee_id",
            "fiscal_year",
            "period",
            name="uq_sales_targets_employee_period",
        ),
    )

    op.add_column(
        "tenants",
        sa.Column(
            "round_off_rule",
            sa.String(10),
            server_default=sa.text("'NONE'"),
            nullable=False,
        ),
    )

    for table in _COMMERCIAL:
        op.add_column(
            table,
            sa.Column(
                "payment_mode",
                sa.String(20),
                server_default=sa.text("'CREDIT'"),
                nullable=False,
            ),
        )
        if table not in _HAS_REFERENCE_NUMBER:
            op.add_column(table, sa.Column("reference_number", sa.String(80), nullable=True))
        op.add_column(table, sa.Column("reference_date", sa.Date(), nullable=True))
        op.add_column(table, sa.Column("marks", sa.String(500), nullable=True))
        op.add_column(table, sa.Column("discount_account_id", UUID, nullable=True))
        op.add_column(table, sa.Column("freight_account_id", UUID, nullable=True))

    for table in ("sales_invoices", "purchase_invoices", "credit_notes", "debit_notes"):
        op.add_column(
            table,
            sa.Column(
                "auto_stock_document",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "is_printed",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )

    op.add_column("sales_invoices", sa.Column("supply_date", sa.Date(), nullable=True))
    op.add_column(
        "quotations",
        sa.Column(
            "price_basis",
            sa.String(20),
            server_default=sa.text("'DEFAULT'"),
            nullable=False,
        ),
    )
    op.add_column(
        "sales_orders",
        sa.Column(
            "price_basis",
            sa.String(20),
            server_default=sa.text("'DEFAULT'"),
            nullable=False,
        ),
    )
    op.add_column("purchase_orders", sa.Column("order_type", sa.String(20), server_default=sa.text("'LOCAL'"), nullable=False))
    op.add_column("purchase_orders", sa.Column("ship_date", sa.Date(), nullable=True))
    op.add_column("purchase_invoices", sa.Column("source_of_supply_country", sa.String(2), nullable=True))
    op.add_column("purchase_invoices", sa.Column("import_doc_number", sa.String(80), nullable=True))
    op.add_column("purchase_invoices", sa.Column("import_doc_date", sa.Date(), nullable=True))
    op.add_column("purchase_invoices", sa.Column("boe_number", sa.String(80), nullable=True))
    op.add_column("purchase_invoices", sa.Column("cargo_permit_number", sa.String(80), nullable=True))
    op.add_column("purchase_invoices", sa.Column("credit_account_id", UUID, nullable=True))

    op.add_column(
        "cost_sheets",
        sa.Column(
            "sheet_mode",
            sa.String(20),
            server_default=sa.text("'PLANNING'"),
            nullable=False,
        ),
    )
    op.add_column("cost_sheets", sa.Column("purchase_invoice_id", UUID, nullable=True))
    op.add_column("cost_sheets", sa.Column("imp_reference", sa.String(80), nullable=True))

    op.create_table(
        "entry_books",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voucher_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("series_prefix", sa.String(20), nullable=False),
        sa.Column("default_account_id", UUID, nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("tenant_id", "voucher_type", name="uq_entry_books_tenant_type"),
    )


def downgrade() -> None:
    op.drop_table("entry_books")
    op.drop_column("cost_sheets", "imp_reference")
    op.drop_column("cost_sheets", "purchase_invoice_id")
    op.drop_column("cost_sheets", "sheet_mode")
    op.drop_column("purchase_invoices", "credit_account_id")
    op.drop_column("purchase_invoices", "cargo_permit_number")
    op.drop_column("purchase_invoices", "boe_number")
    op.drop_column("purchase_invoices", "import_doc_date")
    op.drop_column("purchase_invoices", "import_doc_number")
    op.drop_column("purchase_invoices", "source_of_supply_country")
    op.drop_column("purchase_orders", "ship_date")
    op.drop_column("purchase_orders", "order_type")
    op.drop_column("sales_orders", "price_basis")
    op.drop_column("quotations", "price_basis")
    op.drop_column("sales_invoices", "supply_date")
    for table in ("sales_invoices", "purchase_invoices", "credit_notes", "debit_notes"):
        op.drop_column(table, "is_printed")
        op.drop_column(table, "auto_stock_document")
    for table in reversed(_COMMERCIAL):
        op.drop_column(table, "freight_account_id")
        op.drop_column(table, "discount_account_id")
        op.drop_column(table, "marks")
        op.drop_column(table, "reference_date")
        if table not in _HAS_REFERENCE_NUMBER:
            op.drop_column(table, "reference_number")
        op.drop_column(table, "payment_mode")
    op.drop_column("tenants", "round_off_rule")
    op.drop_table("sales_targets")
    op.drop_column("customers", "supplier_origin")
    op.drop_column("customers", "invoice_type")
    op.drop_column("customers", "phone")
    op.drop_column("customers", "email")
    op.drop_column("customers", "fax")
    op.drop_column("addresses", "address_line_3")
    op.drop_constraint("fk_products_secondary_unit_id", "products", type_="foreignkey")
    op.drop_column("products", "secondary_unit_factor")
    op.drop_column("products", "secondary_unit_id")
    op.drop_column("products", "stock_input_disabled")
    op.drop_column("products", "price_2")
    op.drop_column("products", "price_1")
    op.drop_column("products", "gross_weight")
    op.drop_column("products", "net_weight")
    op.drop_column("products", "default_reorder_level")
    op.drop_column("products", "max_level")
    op.drop_column("products", "remarks")
    op.drop_column("products", "rem")
    op.drop_column("products", "alias_4")
    op.drop_column("products", "alias_3")
    op.drop_column("products", "alias_2")
    op.drop_column("products", "engine")
    op.drop_column("products", "origin_country_code")
    op.drop_column("products", "brand")
    op.drop_constraint("fk_accounts_financial_category_id", "accounts", type_="foreignkey")
    op.drop_constraint("fk_accounts_default_tax_id", "accounts", type_="foreignkey")
    op.drop_column("accounts", "financial_category_id")
    op.drop_column("accounts", "default_tax_id")
    op.drop_table("financial_categories")
