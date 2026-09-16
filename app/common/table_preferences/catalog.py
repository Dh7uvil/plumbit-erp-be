"""Allowlists and defaults for customizable list-table columns."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.catalog import COST_READ

LOCKED_COLUMN_ID = "actions"
PINNED_COLUMN_COUNT = 2


@dataclass(frozen=True, slots=True)
class TableColumnSpec:
    """One customizable column. `actions` is never catalogued."""

    key: str
    default_visible: bool = True
    required_permission: str | None = None


@dataclass(frozen=True, slots=True)
class TableCatalogEntry:
    """Allowed columns and defaults for one list screen."""

    table_key: str
    columns: tuple[TableColumnSpec, ...]

    def effective_columns(self, permissions: frozenset[str]) -> tuple[TableColumnSpec, ...]:
        return tuple(
            column
            for column in self.columns
            if column.required_permission is None or column.required_permission in permissions
        )

    def allowed_keys(self, permissions: frozenset[str]) -> tuple[str, ...]:
        return tuple(column.key for column in self.effective_columns(permissions))

    def default_visible(self, permissions: frozenset[str]) -> list[str]:
        return [
            column.key for column in self.effective_columns(permissions) if column.default_visible
        ]

    def default_order(self, permissions: frozenset[str]) -> list[str]:
        return list(self.allowed_keys(permissions))

    def pinned_keys(self, permissions: frozenset[str]) -> tuple[str, ...]:
        """Identifier and primary label: always visible and always first."""
        return tuple(self.default_visible(permissions)[:PINNED_COLUMN_COUNT])


def _cols(*keys: str) -> tuple[TableColumnSpec, ...]:
    return tuple(TableColumnSpec(key) for key in keys)


def _hidden(*keys: str) -> tuple[TableColumnSpec, ...]:
    return tuple(TableColumnSpec(key, default_visible=False) for key in keys)


def _entry(table_key: str, visible: tuple[str, ...], *hidden: TableColumnSpec) -> TableCatalogEntry:
    return TableCatalogEntry(table_key=table_key, columns=_cols(*visible) + hidden)


_AUDIT = _hidden("created_at", "updated_at")
_AUDIT_ACTORS = _hidden("created_at", "updated_at", "created_by", "updated_by")

_STOCK_COST = (
    TableColumnSpec("unit_cost", required_permission=COST_READ),
    TableColumnSpec("value", required_permission=COST_READ),
)
TABLE_CATALOG: dict[str, TableCatalogEntry] = {
    entry.table_key: entry
    for entry in (
        _entry(
            "identity.users",
            ("email", "user", "department", "designation", "role", "status", "joining_date"),
            *_hidden(
                "phone",
                "branch",
                "employee_code",
                "employee_status",
                "last_login_at",
                "created_at",
                "updated_at",
            ),
        ),
        _entry(
            "identity.roles",
            ("name", "description", "type", "users_count", "created_at"),
            *_hidden("updated_at"),
        ),
        _entry(
            "identity.audit_logs",
            (
                "log_id",
                "action",
                "timestamp",
                "user",
                "resource",
                "resource_id",
                "module",
                "ip_address",
                "status",
            ),
        ),
        _entry(
            "identity.outbox_events",
            ("event_type", "aggregate", "status", "attempts", "created_at", "error"),
            *_hidden("max_attempts", "available_at", "processed_at", "updated_at"),
        ),
        _entry(
            "crm.customers",
            ("code", "name", "type", "tax_treatment", "status"),
            *_hidden(
                "trn",
                "currency",
                "credit_limit",
                "notes",
                "payment_terms",
                "price_list",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "crm.contacts",
            ("name", "company", "email", "phone", "is_primary", "status"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.currencies",
            ("code", "name", "symbol", "decimal_places", "is_base", "is_active"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.exchange_rates",
            ("from_currency", "to_currency", "rate", "effective_date"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.taxes",
            ("name", "tax_category", "rate", "is_default", "is_active"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.payment_terms",
            ("name", "days", "description", "is_active"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.document_sequences",
            (
                "document_type",
                "series",
                "fiscal_year",
                "prefix",
                "next_number",
                "padding",
                "is_active",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.terms_templates",
            ("name", "is_default", "is_active"),
            *_hidden("body"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.accounts",
            ("code", "name", "account_type", "subtype", "kind", "is_active"),
            *_hidden("description", "parent", "currency", "is_system"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.journals",
            (
                "document_number",
                "narration",
                "entry_date",
                "journal_type",
                "source",
                "status",
                "debit",
                "credit",
            ),
            *_hidden("is_posted", "currency", "branch", "exchange_rate", "reference", "posted_at"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.suppliers",
            ("code", "name", "type", "tax_treatment", "status"),
            *_hidden("trn", "currency", "credit_limit", "notes", "payment_terms", "price_list"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.supplier_products",
            (
                "supplier_sku",
                "supplier_item",
                "supplier",
                "mapped_product",
                "price",
                "is_preferred",
                "status",
            ),
            *_hidden("currency_code", "notes", "price_updated_at"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.landed_costs",
            ("document_number", "method", "document_date", "charges", "status"),
            *_hidden("is_posted", "notes", "posted_at"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.quotations",
            ("document_number", "customer", "document_date", "status", "grand_total"),
            *_hidden(
                "is_posted",
                "valid_until",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.proforma_invoices",
            ("document_number", "customer", "document_date", "status", "grand_total"),
            *_hidden(
                "is_posted",
                "valid_until",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.sales_orders",
            ("document_number", "customer", "order_date", "status", "grand_total"),
            *_hidden(
                "fulfillment_status",
                "billing_status",
                "is_posted",
                "reference_number",
                "expected_shipment_date",
                "customer_po_number",
                "warehouse",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.sales_invoices",
            (
                "document_number",
                "customer",
                "invoice_date",
                "due_date",
                "status",
                "payment_status",
                "grand_total",
            ),
            *_hidden(
                "is_posted",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
                "amount_paid",
                "balance_due",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.purchase_orders",
            ("document_number", "supplier", "order_date", "status", "grand_total"),
            *_hidden(
                "is_posted",
                "reference_number",
                "expected_delivery_date",
                "receipt_status",
                "billing_status",
                "warehouse",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.purchase_invoices",
            (
                "document_number",
                "supplier",
                "invoice_date",
                "invoice_type",
                "status",
                "payment_status",
                "grand_total",
            ),
            *_hidden(
                "is_posted",
                "due_date",
                "supplier_invoice_number",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
                "amount_paid",
                "balance_due",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.credit_notes",
            ("document_number", "customer", "document_date", "reason", "status", "grand_total"),
            *_hidden(
                "is_posted",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
                "amount_applied",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.debit_notes",
            ("document_number", "supplier", "document_date", "reason", "status", "grand_total"),
            *_hidden(
                "is_posted",
                "currency",
                "branch",
                "exchange_rate",
                "notes",
                "subtotal",
                "tax_amount",
                "amount_applied",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.customer_payments",
            ("document_number", "customer", "payment_date", "method", "status", "amount"),
            *_hidden(
                "is_posted",
                "currency",
                "exchange_rate",
                "reference",
                "bank_charges",
                "amount_unapplied",
                "notes",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "erp.supplier_payments",
            ("document_number", "supplier", "payment_date", "method", "status", "amount"),
            *_hidden(
                "is_posted",
                "currency",
                "exchange_rate",
                "reference",
                "bank_charges",
                "amount_unapplied",
                "notes",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.products",
            ("sku", "name", "item_type", "selling_rate", "is_active"),
            *_hidden(
                "category",
                "unit",
                "hs_code",
                "sales_description",
                "purchase_rate",
                "track_inventory",
                "requires_qc",
                "tax",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.categories",
            ("code", "name", "parent", "is_active"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.units",
            ("code", "name", "is_active"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.warehouses",
            ("code", "name", "phone", "is_default", "is_active"),
            *_hidden("address", "is_designated_zone"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.price_lists",
            ("name", "list_type", "currency", "percent", "is_active"),
            *_AUDIT_ACTORS,
        ),
        TableCatalogEntry(
            table_key="inventory.stock",
            columns=(
                TableColumnSpec("sku"),
                TableColumnSpec("product"),
                TableColumnSpec("warehouse"),
                TableColumnSpec("qty_on_hand"),
                TableColumnSpec("qty_quality_hold"),
                TableColumnSpec("qty_reserved"),
                TableColumnSpec("qty_available"),
                TableColumnSpec("qty_incoming"),
                TableColumnSpec("qty_outgoing"),
                TableColumnSpec("qty_in_transit"),
                *_STOCK_COST,
                *_hidden("reorder_level", "reorder_qty", "last_movement_at"),
                *_AUDIT,
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.stock_movements",
            columns=(
                TableColumnSpec("sku"),
                TableColumnSpec("product"),
                TableColumnSpec("warehouse"),
                TableColumnSpec("document_date"),
                TableColumnSpec("movement_type"),
                TableColumnSpec("qty"),
                TableColumnSpec("source"),
                *_STOCK_COST,
                *_hidden("qty_before", "qty_after", "occurred_at", "notes"),
                *_AUDIT,
            ),
        ),
        _entry(
            "inventory.trading_history",
            ("document", "date", "party", "product", "qty", "invoiced", "rate", "revenue"),
            TableColumnSpec("unit_cost", required_permission=COST_READ),
            TableColumnSpec("billed_cost", required_permission=COST_READ),
            TableColumnSpec("margin", required_permission=COST_READ),
        ),
        _entry(
            "inventory.trading_party_aggregates",
            ("party", "qty", "invoiced", "revenue", "dispatches", "first", "last", "last_rate"),
        ),
        _entry(
            "inventory.trading_product_aggregates",
            ("sku", "product", "qty", "invoiced", "revenue", "dispatches", "first", "last", "last_rate"),
        ),
        _entry(
            "inventory.price_list_items",
            ("sku", "product", "rate"),
        ),
        _entry(
            "inventory.packages",
            ("document_number", "carton", "status"),
            *_hidden(
                "length",
                "width",
                "height",
                "gross_weight",
                "net_weight",
                "notes",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "logistics.shipments",
            ("document_number", "shipment_type", "status"),
            *_hidden(
                "transport_mode",
                "incoterm",
                "carrier_name",
                "etd",
                "eta",
                "notes",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.delivery_notes",
            ("document_number", "customer", "document_date", "status"),
            *_hidden(
                "is_posted",
                "warehouse",
                "vehicle_number",
                "driver_name",
                "notes",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.goods_receipts",
            ("document_number", "supplier", "document_date", "qc_status", "status"),
            *_hidden(
                "is_posted",
                "warehouse",
                "supplier_invoice_number",
                "bl_number",
                "notes",
            ),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.sales_returns",
            ("document_number", "reason", "document_date", "status"),
            *_hidden("is_posted", "notes"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.purchase_returns",
            ("document_number", "reason", "document_date", "status"),
            *_hidden("is_posted", "notes"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.quality_inspections",
            ("document_number", "goods_receipt", "document_date", "status"),
            *_hidden("notes", "inspector"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.stock_transfers",
            ("document_number", "from_warehouse", "document_date", "to_warehouse", "status"),
            *_hidden("is_posted", "reason", "reference", "notes"),
            *_AUDIT_ACTORS,
        ),
        _entry(
            "inventory.stock_adjustments",
            ("document_number", "warehouse", "document_date", "reason", "status"),
            *_hidden("is_posted", "reference", "notes"),
            *_AUDIT_ACTORS,
        ),
    )
}


def get_table_catalog(table_key: str) -> TableCatalogEntry | None:
    return TABLE_CATALOG.get(table_key)
