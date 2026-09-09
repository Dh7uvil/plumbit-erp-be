"""Activity feed registry: audit entity type → required read permission and field allowlist."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.catalog import (
    CONTACT_READ,
    CRM_MODULE,
    CUSTOMER_READ,
    ERP_MODULE,
    INVENTORY_MODULE,
    PRODUCT_READ,
    PURCHASE_ORDER_READ,
    QUOTATION_READ,
    SALES_ORDER_READ,
    STOCK_ADJUSTMENT_READ,
    STOCK_TRANSFER_READ,
    SUPPLIER_PRODUCT_READ,
    SUPPLIER_READ,
)

_DOCUMENT_MONEY_FIELDS: frozenset[str] = frozenset(
    {
        "discount_type",
        "discount_value",
        "discount_amount",
        "shipping_amount",
        "adjustment_amount",
        "subtotal",
        "tax_amount",
        "grand_total",
        "foreign_amount",
        "base_amount",
        "exchange_rate",
        "currency",
        "tax_treatment",
        "place_of_supply",
        "payment_terms",
        "contact",
        "branch",
        "version",
        "status",
    }
)

_QUOTATION_FIELDS: frozenset[str] = _DOCUMENT_MONEY_FIELDS | frozenset(
    {
        "quote_number",
        "quote_date",
        "valid_until",
        "customer",
        "price_list",
        "salesperson",
    }
)
_SALES_ORDER_FIELDS: frozenset[str] = _DOCUMENT_MONEY_FIELDS | frozenset(
    {
        "document_number",
        "order_date",
        "reference_number",
        "warehouse",
        "customer",
        "price_list",
        "salesperson",
        "fulfillment_status",
        "billing_status",
    }
)
_PURCHASE_ORDER_FIELDS: frozenset[str] = _DOCUMENT_MONEY_FIELDS | frozenset(
    {
        "document_number",
        "order_date",
        "reference_number",
        "warehouse",
        "supplier",
        "receipt_status",
        "billing_status",
    }
)
_STOCK_FIELDS: frozenset[str] = frozenset(
    {
        "document_number",
        "status",
        "version",
        "document_date",
        "reference",
        "line_count",
    }
)
_PARTY_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "code",
        "company_type",
        "trn",
        "tax_treatment",
        "currency",
        "price_list",
        "payment_terms",
        "credit_limit",
        "salesperson",
        "notes",
    }
)


@dataclass(frozen=True, slots=True)
class ActivityEntitySpec:
    """How the activity feed reads and redacts one audit entity type."""

    module: str
    entity_type: str
    read_permission: str
    changed_fields: frozenset[str]


ACTIVITY_ENTITIES: dict[str, ActivityEntitySpec] = {
    "quotation": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="quotation",
        read_permission=QUOTATION_READ,
        changed_fields=_QUOTATION_FIELDS,
    ),
    "sales_order": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="sales_order",
        read_permission=SALES_ORDER_READ,
        changed_fields=_SALES_ORDER_FIELDS,
    ),
    "purchase_order": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="purchase_order",
        read_permission=PURCHASE_ORDER_READ,
        changed_fields=_PURCHASE_ORDER_FIELDS,
    ),
    "stock_transfer": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="stock_transfer",
        read_permission=STOCK_TRANSFER_READ,
        changed_fields=_STOCK_FIELDS | frozenset({"from_warehouse", "to_warehouse"}),
    ),
    "stock_adjustment": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="stock_adjustment",
        read_permission=STOCK_ADJUSTMENT_READ,
        changed_fields=_STOCK_FIELDS | frozenset({"warehouse", "reason"}),
    ),
    "customer": ActivityEntitySpec(
        module=CRM_MODULE,
        entity_type="customer",
        read_permission=CUSTOMER_READ,
        changed_fields=_PARTY_FIELDS,
    ),
    "supplier": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="supplier",
        read_permission=SUPPLIER_READ,
        changed_fields=_PARTY_FIELDS,
    ),
    "supplier_product": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="supplier_product",
        read_permission=SUPPLIER_PRODUCT_READ,
        changed_fields=frozenset(
            {
                "supplier",
                "product",
                "supplier_sku",
                "supplier_item_name",
                "price",
                "currency",
                "is_preferred",
                "is_preferred_supplier",
                "is_active",
            }
        ),
    ),
    "product": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="product",
        read_permission=PRODUCT_READ,
        changed_fields=frozenset(
            {"sku", "name", "item_type", "unit", "selling_rate", "is_active", "track_inventory"}
        ),
    ),
    "contact": ActivityEntitySpec(
        module=CRM_MODULE,
        entity_type="contact",
        read_permission=CONTACT_READ,
        changed_fields=frozenset({"name", "email", "phone", "is_primary"}),
    ),
}


def get_activity_spec(entity_type: str) -> ActivityEntitySpec | None:
    """Return the registry entry for an audit entity type, if registered."""

    return ACTIVITY_ENTITIES.get(entity_type)
