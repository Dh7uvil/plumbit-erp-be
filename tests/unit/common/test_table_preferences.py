import pytest

from app.auth.catalog import COST_READ
from app.common.table_preferences.catalog import TABLE_CATALOG, get_table_catalog
from app.common.table_preferences.normalize import merge_stored, validate_update
from app.core.exceptions import ValidationError


def test_catalog_covers_list_tables() -> None:
    expected = {
        "identity.users",
        "identity.roles",
        "identity.audit_logs",
        "identity.outbox_events",
        "crm.customers",
        "crm.contacts",
        "erp.currencies",
        "erp.exchange_rates",
        "erp.taxes",
        "erp.payment_terms",
        "erp.document_sequences",
        "erp.terms_templates",
        "erp.accounts",
        "erp.charge_types",
        "erp.journals",
        "erp.suppliers",
        "erp.supplier_products",
        "erp.landed_costs",
        "erp.quotations",
        "erp.proforma_invoices",
        "erp.sales_orders",
        "erp.sales_invoices",
        "erp.purchase_orders",
        "erp.purchase_invoices",
        "erp.credit_notes",
        "erp.debit_notes",
        "erp.customer_payments",
        "erp.supplier_payments",
        "inventory.products",
        "inventory.categories",
        "inventory.units",
        "inventory.warehouses",
        "inventory.price_lists",
        "inventory.stock",
        "inventory.stock_movements",
        "inventory.trading_history",
        "inventory.trading_party_aggregates",
        "inventory.trading_product_aggregates",
        "inventory.price_list_items",
        "inventory.packages",
        "logistics.shipments",
        "inventory.delivery_notes",
        "inventory.goods_receipts",
        "inventory.sales_returns",
        "inventory.purchase_returns",
        "inventory.quality_inspections",
        "inventory.stock_transfers",
        "inventory.stock_adjustments",
    }
    assert set(TABLE_CATALOG) == expected
    for entry in TABLE_CATALOG.values():
        assert "actions" not in entry.allowed_keys(frozenset())
        assert entry.default_visible(frozenset())


def test_unknown_table_key_is_none() -> None:
    assert get_table_catalog("erp.unknown") is None


def test_cost_columns_require_permission() -> None:
    entry = TABLE_CATALOG["inventory.stock_movements"]
    without_cost = entry.allowed_keys(frozenset())
    with_cost = entry.allowed_keys(frozenset({COST_READ}))
    assert "unit_cost" not in without_cost
    assert "value" not in without_cost
    assert "unit_cost" in with_cost
    assert "value" in with_cost


def test_trading_history_cost_columns_require_permission() -> None:
    entry = TABLE_CATALOG["inventory.trading_history"]
    without_cost = entry.allowed_keys(frozenset())
    with_cost = entry.allowed_keys(frozenset({COST_READ}))
    assert "unit_cost" not in without_cost
    assert "billed_cost" not in without_cost
    assert "margin" not in without_cost
    assert "unit_cost" in with_cost
    assert "billed_cost" in with_cost
    assert "margin" in with_cost
    assert entry.default_visible(frozenset()) == [
        "document",
        "date",
        "party",
        "product",
        "qty",
        "invoiced",
        "rate",
        "revenue",
    ]


def test_validate_update_strips_actions_and_completes_order() -> None:
    entry = TABLE_CATALOG["erp.exchange_rates"]
    result = validate_update(
        entry,
        visible_columns=["rate", "actions"],
        column_order=["rate", "actions"],
        permissions=frozenset(),
    )
    assert result.visible_columns[:3] == ["from_currency", "to_currency", "rate"]
    assert result.column_order[:2] == ["from_currency", "to_currency"]
    assert "effective_date" in result.column_order
    assert "created_at" in result.column_order


def test_validate_update_rejects_unknown_keys() -> None:
    entry = TABLE_CATALOG["erp.exchange_rates"]
    with pytest.raises(ValidationError) as exc:
        validate_update(
            entry,
            visible_columns=["rate", "secret"],
            column_order=["rate"],
            permissions=frozenset(),
        )
    assert exc.value.details["unknown_columns"] == ["secret"]


def test_validate_update_forces_pinned_when_visible_empty() -> None:
    entry = TABLE_CATALOG["erp.exchange_rates"]
    result = validate_update(
        entry,
        visible_columns=["actions"],
        column_order=["from_currency"],
        permissions=frozenset(),
    )
    assert result.visible_columns[:2] == ["from_currency", "to_currency"]
    assert result.column_order[:2] == ["from_currency", "to_currency"]


def test_validate_update_rejects_duplicates() -> None:
    entry = TABLE_CATALOG["erp.exchange_rates"]
    with pytest.raises(ValidationError, match="duplicates"):
        validate_update(
            entry,
            visible_columns=["rate", "rate"],
            column_order=["rate"],
            permissions=frozenset(),
        )


def test_validate_update_strips_permission_gated_as_unknown() -> None:
    entry = TABLE_CATALOG["inventory.stock_movements"]
    with pytest.raises(ValidationError) as exc:
        validate_update(
            entry,
            visible_columns=["sku", "unit_cost"],
            column_order=["sku", "unit_cost"],
            permissions=frozenset(),
        )
    assert "unit_cost" in exc.value.details["unknown_columns"]


def test_merge_stored_drops_unknown_and_fills_new_keys() -> None:
    entry = TABLE_CATALOG["erp.sales_orders"]
    merged = merge_stored(
        entry,
        visible_columns=["document_number", "removed_field", "actions"],
        column_order=["customer", "document_number"],
        permissions=frozenset(),
    )
    assert merged.visible_columns[:2] == ["document_number", "customer"]
    assert merged.column_order[:2] == ["document_number", "customer"]
    assert "fulfillment_status" in merged.column_order
    assert "billing_status" in merged.column_order


def test_merge_stored_falls_back_when_visible_empty() -> None:
    entry = TABLE_CATALOG["erp.exchange_rates"]
    merged = merge_stored(
        entry,
        visible_columns=["gone"],
        column_order=["gone"],
        permissions=frozenset(),
    )
    assert merged.visible_columns == entry.default_visible(frozenset())
    assert merged.column_order == entry.default_order(frozenset())


def test_sales_orders_optional_columns_hidden_by_default() -> None:
    entry = TABLE_CATALOG["erp.sales_orders"]
    visible = entry.default_visible(frozenset())
    assert visible == [
        "document_number",
        "customer",
        "order_date",
        "status",
        "grand_total",
    ]
    assert "fulfillment_status" in entry.allowed_keys(frozenset())
    assert "created_by" in entry.allowed_keys(frozenset())
    assert "updated_by" in entry.allowed_keys(frozenset())


def test_users_optional_columns_hidden_by_default() -> None:
    entry = TABLE_CATALOG["identity.users"]
    visible = entry.default_visible(frozenset())
    assert visible == [
        "email",
        "user",
        "department",
        "designation",
        "role",
        "status",
        "joining_date",
    ]
    assert "phone" in entry.allowed_keys(frozenset())
    assert "created_at" in entry.allowed_keys(frozenset())
    assert "updated_at" in entry.allowed_keys(frozenset())
    assert "created_by" not in entry.allowed_keys(frozenset())


def test_audit_actor_columns_hidden_on_masters() -> None:
    entry = TABLE_CATALOG["inventory.products"]
    assert entry.default_visible(frozenset()) == [
        "sku",
        "name",
        "item_type",
        "selling_rate",
        "is_active",
    ]
    for key in ("created_at", "updated_at", "created_by", "updated_by", "tax", "purchase_rate"):
        assert key in entry.allowed_keys(frozenset())
        assert key not in entry.default_visible(frozenset())


def test_stock_has_timestamps_without_actors() -> None:
    entry = TABLE_CATALOG["inventory.stock"]
    allowed = entry.allowed_keys(frozenset())
    assert "created_at" in allowed
    assert "updated_at" in allowed
    assert "created_by" not in allowed
    assert "reorder_level" in allowed


def test_default_visible_starts_with_identifier_then_label() -> None:
    expected = {
        "identity.users": ("email", "user"),
        "identity.audit_logs": ("log_id", "action"),
        "erp.exchange_rates": ("from_currency", "to_currency"),
        "erp.journals": ("document_number", "narration"),
        "erp.supplier_products": ("supplier_sku", "supplier_item"),
        "erp.landed_costs": ("document_number", "method"),
        "inventory.delivery_notes": ("document_number", "customer"),
        "inventory.goods_receipts": ("document_number", "supplier"),
        "inventory.sales_returns": ("document_number", "reason"),
        "inventory.purchase_returns": ("document_number", "reason"),
        "inventory.quality_inspections": ("document_number", "goods_receipt"),
        "inventory.stock_transfers": ("document_number", "from_warehouse"),
        "inventory.stock_adjustments": ("document_number", "warehouse"),
    }
    for table_key, prefix in expected.items():
        visible = TABLE_CATALOG[table_key].default_visible(frozenset())
        assert tuple(visible[:2]) == prefix, table_key
        assert TABLE_CATALOG[table_key].pinned_keys(frozenset()) == prefix
    exchange = TABLE_CATALOG["erp.exchange_rates"]
    assert exchange.default_visible(frozenset()) == [
        "from_currency",
        "to_currency",
        "rate",
        "effective_date",
    ]
    assert "to_currency" not in [
        column.key
        for column in exchange.columns
        if not column.default_visible
    ]
