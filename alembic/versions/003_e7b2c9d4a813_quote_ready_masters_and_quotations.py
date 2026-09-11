"""quote ready masters and quotations

Revision ID: e7b2c9d4a813
Revises: a1f3c8e2b704
Create Date: 2026-08-27 08:30:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "e7b2c9d4a813"
down_revision: str | Sequence[str] | None = "a1f3c8e2b704"
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


def _is_active() -> sa.Column:
    return sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False)


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "currencies",
        _pk(),
        _tenant(),
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("decimal_places", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("is_base", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_currencies_tenant_id", "currencies", ["tenant_id"])
    op.create_index(
        "uq_currencies_tenant_id_code_active",
        "currencies",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_currencies_tenant_id_base_active",
        "currencies",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_base IS TRUE AND deleted_at IS NULL"),
    )

    op.create_foreign_key(
        "fk_tenants_default_currency_id_currencies",
        "tenants",
        "currencies",
        ["default_currency_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_branches_default_currency_id_currencies",
        "branches",
        "currencies",
        ["default_currency_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "exchange_rates",
        _pk(),
        _tenant(),
        sa.Column("from_currency_id", UUID, nullable=False),
        sa.Column("to_currency_id", UUID, nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        *_timestamps(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["from_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "from_currency_id",
            "to_currency_id",
            "effective_date",
            name="uq_exchange_rates_tenant_pair_date",
        ),
    )
    op.create_index("ix_exchange_rates_tenant_id", "exchange_rates", ["tenant_id"])
    op.create_index("ix_exchange_rates_from_currency_id", "exchange_rates", ["from_currency_id"])
    op.create_index("ix_exchange_rates_to_currency_id", "exchange_rates", ["to_currency_id"])
    op.create_index("ix_exchange_rates_effective_date", "exchange_rates", ["effective_date"])

    op.create_table(
        "taxes",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("tax_category", sa.String(length=30), nullable=False),
        sa.Column("rate", sa.Numeric(18, 4), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_taxes_tenant_id", "taxes", ["tenant_id"])
    op.create_index(
        "uq_taxes_tenant_id_name_active",
        "taxes",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_taxes_tenant_id_default_active",
        "taxes",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE AND deleted_at IS NULL"),
    )

    op.create_table(
        "payment_terms",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_terms_tenant_id", "payment_terms", ["tenant_id"])
    op.create_index(
        "uq_payment_terms_tenant_id_name_active",
        "payment_terms",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "terms_templates",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_terms_templates_tenant_id", "terms_templates", ["tenant_id"])
    op.create_index(
        "uq_terms_templates_tenant_id_name_active",
        "terms_templates",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_terms_templates_tenant_id_default_active",
        "terms_templates",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE AND deleted_at IS NULL"),
    )

    op.create_table(
        "document_sequences",
        _pk(),
        _tenant(),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column("series", sa.String(length=20), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("next_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("padding", sa.Integer(), server_default=sa.text("6"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_sequences_tenant_id", "document_sequences", ["tenant_id"])
    op.create_index(
        "uq_document_sequences_tenant_type_series_year_active",
        "document_sequences",
        ["tenant_id", "document_type", "series", "fiscal_year"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "units",
        _pk(),
        _tenant(),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_units_tenant_id", "units", ["tenant_id"])
    op.create_index(
        "uq_units_tenant_id_code_active",
        "units",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "categories",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("parent_id", UUID, nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_categories_tenant_id", "categories", ["tenant_id"])
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])
    op.create_index(
        "uq_categories_tenant_id_code_active",
        "categories",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "products",
        _pk(),
        _tenant(),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sales_description", sa.Text(), nullable=True),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("category_id", UUID, nullable=True),
        sa.Column("selling_rate", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("hs_code", sa.String(length=20), nullable=True),
        sa.Column("track_inventory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("ix_products_unit_id", "products", ["unit_id"])
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index("ix_products_tax_id", "products", ["tax_id"])
    op.create_index(
        "uq_products_tenant_id_sku_active",
        "products",
        ["tenant_id", "sku"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "price_lists",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("list_type", sa.String(length=30), nullable=False),
        sa.Column("percent", sa.Numeric(18, 4), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_lists_tenant_id", "price_lists", ["tenant_id"])
    op.create_index("ix_price_lists_currency_id", "price_lists", ["currency_id"])
    op.create_index(
        "uq_price_lists_tenant_id_name_active",
        "price_lists",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "price_list_items",
        _pk(),
        _tenant(),
        sa.Column("price_list_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("rate", sa.Numeric(18, 4), nullable=False),
        *_timestamps(),
        _soft_delete(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "price_list_id",
            "product_id",
            name="uq_price_list_items_tenant_list_product",
        ),
    )
    op.create_index("ix_price_list_items_tenant_id", "price_list_items", ["tenant_id"])
    op.create_index("ix_price_list_items_price_list_id", "price_list_items", ["price_list_id"])
    op.create_index("ix_price_list_items_product_id", "price_list_items", ["product_id"])

    op.create_table(
        "customers",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column(
            "company_type",
            sa.String(length=30),
            server_default=sa.text("'CUSTOMER'"),
            nullable=False,
        ),
        sa.Column("trn", sa.String(length=50), nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("default_price_list_id", UUID, nullable=True),
        sa.Column("payment_terms_id", UUID, nullable=True),
        sa.Column("credit_limit", sa.Numeric(18, 4), nullable=True),
        sa.Column("salesperson_id", UUID, nullable=True),
        sa.Column("billing_address_id", UUID, nullable=True),
        sa.Column("shipping_address_id", UUID, nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["default_price_list_id"], ["price_lists.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_terms_id"], ["payment_terms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["billing_address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipping_address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.create_index("ix_customers_currency_id", "customers", ["currency_id"])
    op.create_index("ix_customers_default_price_list_id", "customers", ["default_price_list_id"])
    op.create_index("ix_customers_payment_terms_id", "customers", ["payment_terms_id"])
    op.create_index("ix_customers_salesperson_id", "customers", ["salesperson_id"])
    op.create_index("ix_customers_billing_address_id", "customers", ["billing_address_id"])
    op.create_index("ix_customers_shipping_address_id", "customers", ["shipping_address_id"])
    op.create_index(
        "uq_customers_tenant_id_code_active",
        "customers",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "customer_addresses",
        _pk(),
        _tenant(),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("address_id", UUID, nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column(
            "is_default_billing", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "is_default_shipping", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        *_timestamps(),
        _soft_delete(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "customer_id",
            "address_id",
            name="uq_customer_addresses_tenant_customer_address",
        ),
    )
    op.create_index("ix_customer_addresses_tenant_id", "customer_addresses", ["tenant_id"])
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])
    op.create_index("ix_customer_addresses_address_id", "customer_addresses", ["address_id"])

    op.create_table(
        "contacts",
        _pk(),
        _tenant(),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])
    op.create_index("ix_contacts_customer_id", "contacts", ["customer_id"])
    op.create_index(
        "uq_contacts_tenant_id_customer_primary_active",
        "contacts",
        ["tenant_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("is_primary IS TRUE AND deleted_at IS NULL"),
    )

    op.create_table(
        "quotations",
        _pk(),
        _tenant(),
        sa.Column("quote_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("quote_date", sa.Date(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quotations_tenant_id", "quotations", ["tenant_id"])
    op.create_index("ix_quotations_branch_id", "quotations", ["branch_id"])
    op.create_index("ix_quotations_customer_id", "quotations", ["customer_id"])
    op.create_index("ix_quotations_contact_id", "quotations", ["contact_id"])
    op.create_index("ix_quotations_currency_id", "quotations", ["currency_id"])
    op.create_index("ix_quotations_tenant_id_status", "quotations", ["tenant_id", "status"])
    op.create_index("ix_quotations_tenant_id_quote_date", "quotations", ["tenant_id", "quote_date"])
    op.create_index(
        "uq_quotations_tenant_id_quote_number_active",
        "quotations",
        ["tenant_id", "quote_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "quotation_lines",
        _pk(),
        _tenant(),
        sa.Column("quotation_id", UUID, nullable=False),
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
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quotation_id"], ["quotations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quotation_lines_tenant_id", "quotation_lines", ["tenant_id"])
    op.create_index("ix_quotation_lines_quotation_id", "quotation_lines", ["quotation_id"])
    op.create_index("ix_quotation_lines_product_id", "quotation_lines", ["product_id"])

    op.create_table(
        "attachments",
        _pk(),
        _tenant(),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachments_tenant_id", "attachments", ["tenant_id"])
    op.create_index(
        "ix_attachments_tenant_entity",
        "attachments",
        ["tenant_id", "entity_type", "entity_id"],
    )

    _backfill_catalog_and_masters()


def _backfill_catalog_and_masters() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_catalog_permissions()
    year = datetime.now(UTC).year

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

        already = bind.execute(
            sa.text(
                """
                SELECT id FROM currencies
                WHERE tenant_id = :tenant_id AND code = 'AED' AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if already is not None:
            continue

        aed = bind.execute(
            sa.text(
                """
                INSERT INTO currencies (tenant_id, code, name, symbol, decimal_places, is_base)
                VALUES (:tenant_id, 'AED', 'UAE Dirham', 'د.إ', 2, true)
                RETURNING id
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        bind.execute(
            sa.text(
                """
                UPDATE tenants
                SET default_currency_id = :currency_id,
                    settings = coalesce(settings, '{}'::jsonb)
                        || '{"default_currency": "AED"}'::jsonb
                WHERE id = :tenant_id
                """
            ),
            {"currency_id": aed.id, "tenant_id": tenant_id},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO taxes (tenant_id, name, tax_category, rate, is_default)
                VALUES
                    (:tenant_id, 'Standard VAT 5%', 'STANDARD', 5, true),
                    (:tenant_id, 'Zero Rated', 'ZERO_RATED', 0, false),
                    (:tenant_id, 'Exempt', 'EXEMPT', 0, false),
                    (:tenant_id, 'Out of Scope', 'OUT_OF_SCOPE', 0, false)
                """
            ),
            {"tenant_id": tenant_id},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO units (tenant_id, code, name)
                VALUES
                    (:tenant_id, 'PCS', 'Pieces'),
                    (:tenant_id, 'BOX', 'Box'),
                    (:tenant_id, 'M', 'Metre'),
                    (:tenant_id, 'KG', 'Kilogram')
                """
            ),
            {"tenant_id": tenant_id},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO payment_terms (tenant_id, name, days, description)
                VALUES (:tenant_id, 'Net 30', 30, 'Payment due 30 days from the document date')
                """
            ),
            {"tenant_id": tenant_id},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO terms_templates (tenant_id, name, body, is_default)
                VALUES (
                    :tenant_id,
                    'Standard terms',
                    'Prices are in the document currency and exclusive of delivery '
                    'unless stated. This quotation is valid until the stated expiry date.',
                    true
                )
                """
            ),
            {"tenant_id": tenant_id},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO document_sequences
                    (tenant_id, document_type, series, fiscal_year, prefix, next_number, padding)
                VALUES (:tenant_id, 'QUOTATION', 'QUO', :year, 'QUO', 1, 6)
                """
            ),
            {"tenant_id": tenant_id, "year": year},
        )


def downgrade() -> None:
    """Revert this revision."""
    op.execute(sa.text("DROP TABLE IF EXISTS attachments"))
    op.drop_table("quotation_lines")
    op.drop_table("quotations")
    op.drop_table("contacts")
    op.drop_table("customer_addresses")
    op.drop_table("customers")
    op.drop_table("price_list_items")
    op.drop_table("price_lists")
    op.drop_table("products")
    op.drop_table("categories")
    op.drop_table("units")
    op.drop_table("document_sequences")
    op.drop_table("terms_templates")
    op.drop_table("payment_terms")
    op.drop_table("taxes")
    op.drop_table("exchange_rates")
    op.execute(sa.text("UPDATE tenants SET default_currency_id = NULL"))
    op.execute(sa.text("UPDATE branches SET default_currency_id = NULL"))
    op.drop_constraint("fk_branches_default_currency_id_currencies", "branches", type_="foreignkey")
    op.drop_constraint("fk_tenants_default_currency_id_currencies", "tenants", type_="foreignkey")
    op.drop_table("currencies")
