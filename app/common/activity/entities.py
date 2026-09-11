"""Activity feed registry: audit entity type → required read permission and field allowlist."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.catalog import (
    ACCOUNT_READ,
    CONTACT_READ,
    CREDIT_NOTE_READ,
    CRM_MODULE,
    CUSTOMER_READ,
    CUSTOMER_PAYMENT_READ,
    DEBIT_NOTE_READ,
    DELIVERY_NOTE_READ,
    ERP_MODULE,
    GOODS_RECEIPT_READ,
    INVENTORY_MODULE,
    JOURNAL_ENTRY_READ,
    LANDED_COST_READ,
    PACKAGE_READ,
    PRODUCT_READ,
    PROFORMA_INVOICE_READ,
    PURCHASE_INVOICE_READ,
    PURCHASE_ORDER_READ,
    QUALITY_INSPECTION_READ,
    QUOTATION_READ,
    SALES_INVOICE_READ,
    SALES_ORDER_READ,
    SALES_RETURN_READ,
    SHIPMENT_READ,
    STOCK_ADJUSTMENT_READ,
    STOCK_TRANSFER_READ,
    SUPPLIER_PRODUCT_READ,
    SUPPLIER_PAYMENT_READ,
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
_PROFORMA_INVOICE_FIELDS: frozenset[str] = _DOCUMENT_MONEY_FIELDS | frozenset(
    {
        "document_number",
        "proforma_date",
        "valid_until",
        "customer",
        "price_list",
        "salesperson",
        "incoterm",
        "advance_required_amount",
    }
)
_SALES_ORDER_FIELDS: frozenset[str] = _DOCUMENT_MONEY_FIELDS | frozenset(
    {
        "document_number",
        "order_date",
        "reference_number",
        "customer_po_number",
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
        changed_fields=_QUOTATION_FIELDS | frozenset({"revision_number", "revision_reason"}),
    ),
    "proforma_invoice": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="proforma_invoice",
        read_permission=PROFORMA_INVOICE_READ,
        changed_fields=_PROFORMA_INVOICE_FIELDS,
    ),
    "sales_order": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="sales_order",
        read_permission=SALES_ORDER_READ,
        changed_fields=_SALES_ORDER_FIELDS,
    ),
    "sales_invoice": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="sales_invoice",
        read_permission=SALES_INVOICE_READ,
        changed_fields=_DOCUMENT_MONEY_FIELDS
        | frozenset(
            {
                "document_number",
                "invoice_date",
                "customer",
                "due_date",
                "payment_status",
                "cogs_status",
                "grand_total",
            }
        ),
    ),
    "purchase_order": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="purchase_order",
        read_permission=PURCHASE_ORDER_READ,
        changed_fields=_PURCHASE_ORDER_FIELDS,
    ),
    "purchase_invoice": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="purchase_invoice",
        read_permission=PURCHASE_INVOICE_READ,
        changed_fields=_DOCUMENT_MONEY_FIELDS
        | frozenset(
            {
                "document_number",
                "invoice_date",
                "supplier",
                "bill_type",
                "due_date",
                "payment_status",
                "grand_total",
            }
        ),
    ),
    "credit_note": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="credit_note",
        read_permission=CREDIT_NOTE_READ,
        changed_fields=_DOCUMENT_MONEY_FIELDS
        | frozenset(
            {
                "document_number",
                "credit_note_date",
                "customer",
                "reason_code",
                "grand_total",
            }
        ),
    ),
    "debit_note": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="debit_note",
        read_permission=DEBIT_NOTE_READ,
        changed_fields=_DOCUMENT_MONEY_FIELDS
        | frozenset(
            {
                "document_number",
                "debit_note_date",
                "supplier",
                "reason_code",
                "grand_total",
            }
        ),
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
    "goods_receipt": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="goods_receipt",
        read_permission=GOODS_RECEIPT_READ,
        changed_fields=_STOCK_FIELDS
        | frozenset(
            {
                "supplier",
                "warehouse",
                "purchase_order",
                "qc_status",
                "supplier_invoice_number",
                "container_number",
                "bl_number",
            }
        ),
    ),
    "quality_inspection": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="quality_inspection",
        read_permission=QUALITY_INSPECTION_READ,
        changed_fields=frozenset(
            {
                "document_number",
                "status",
                "version",
                "inspection_date",
                "goods_receipt",
                "notes",
            }
        ),
    ),
    "delivery_note": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="delivery_note",
        read_permission=DELIVERY_NOTE_READ,
        changed_fields=_STOCK_FIELDS
        | frozenset(
            {
                "customer",
                "warehouse",
                "sales_order",
                "shipment",
                "vehicle_number",
            }
        ),
    ),
    "sales_return": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="sales_return",
        read_permission=SALES_RETURN_READ,
        changed_fields=_STOCK_FIELDS
        | frozenset(
            {
                "customer",
                "warehouse",
                "delivery_note",
                "sales_order",
                "reason_code",
            }
        ),
    ),
    "package": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="package",
        read_permission=PACKAGE_READ,
        changed_fields=_STOCK_FIELDS
        | frozenset({"sales_order", "warehouse", "package_type", "gross_weight"}),
    ),
    "shipment": ActivityEntitySpec(
        module=INVENTORY_MODULE,
        entity_type="shipment",
        read_permission=SHIPMENT_READ,
        changed_fields=_STOCK_FIELDS
        | frozenset(
            {
                "shipment_type",
                "transport_mode",
                "bl_awb_number",
                "container_number",
                "carrier_name",
            }
        ),
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
            {
                "sku",
                "name",
                "item_type",
                "unit",
                "selling_rate",
                "is_active",
                "track_inventory",
                "requires_qc",
            }
        ),
    ),
    "contact": ActivityEntitySpec(
        module=CRM_MODULE,
        entity_type="contact",
        read_permission=CONTACT_READ,
        changed_fields=frozenset({"name", "email", "phone", "is_primary"}),
    ),
    "account": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="account",
        read_permission=ACCOUNT_READ,
        changed_fields=frozenset(
            {
                "code",
                "name",
                "account_type",
                "account_subtype",
                "is_group",
                "is_system",
                "system_role",
                "is_active",
            }
        ),
    ),
    "journal_entry": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="journal_entry",
        read_permission=JOURNAL_ENTRY_READ,
        changed_fields=_STOCK_FIELDS
        | frozenset({"entry_date", "narration", "journal_type", "total_debit_base", "total_credit_base"}),
    ),
    "customer_payment": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="customer_payment",
        read_permission=CUSTOMER_PAYMENT_READ,
        changed_fields=frozenset(
            {
                "document_number",
                "payment_date",
                "customer",
                "amount_received",
                "bank_charges",
                "amount_unapplied",
                "payment_method",
                "reference",
                "status",
                "version",
                "currency",
                "exchange_rate",
            }
        ),
    ),
    "supplier_payment": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="supplier_payment",
        read_permission=SUPPLIER_PAYMENT_READ,
        changed_fields=frozenset(
            {
                "document_number",
                "payment_date",
                "supplier",
                "amount_paid",
                "bank_charges",
                "amount_unapplied",
                "payment_method",
                "reference",
                "status",
                "version",
                "currency",
                "exchange_rate",
            }
        ),
    ),
    "landed_cost": ActivityEntitySpec(
        module=ERP_MODULE,
        entity_type="landed_cost",
        read_permission=LANDED_COST_READ,
        changed_fields=frozenset(
            {
                "document_number",
                "document_date",
                "allocation_method",
                "status",
                "version",
                "charge_count",
                "allocation_count",
            }
        ),
    ),
}


def get_activity_spec(entity_type: str) -> ActivityEntitySpec | None:
    """Return the registry entry for an audit entity type, if registered."""

    return ACTIVITY_ENTITIES.get(entity_type)
