"""Canonical permission catalog registry and per-tenant seeding."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Permission, Role, RolePermission
from app.core.permissions import Permission as ParsedPermission
from app.core.permissions import build_permission, parse_permission

IDENTITY_MODULE = "identity"
CRM_MODULE = "crm"
SALES_MODULE = "sales"
PURCHASE_MODULE = "purchase"
LOGISTICS_MODULE = "logistics"
INVENTORY_MODULE = "inventory"
ACCOUNTING_MODULE = "accounting"
REPORTS_MODULE = "reports"
MASTERS_MODULE = "masters"

_IMEX_ACTIONS: tuple[str, ...] = ("import", "export")


def _with_imex(*actions: str) -> tuple[str, ...]:
    """Append per-resource import/export actions."""

    return actions + _IMEX_ACTIONS


_CATALOG_ACTIONS: dict[str, dict[str, tuple[str, ...]]] = {
    IDENTITY_MODULE: {
        "user": ('create', 'read', 'update', 'delete'),
        "role": ('create', 'read', 'update', 'delete'),
        "permission": ('read',),
        "organization": ('read', 'update'),
        "department": ('create', 'read', 'update', 'delete'),
        "branch": ('create', 'read', 'update', 'delete'),
        "employee": ('create', 'read', 'update', 'delete'),
        "audit_log": ('read',),
        "attachment": ('create', 'read', 'update', 'delete'),
        "outbox_event": ('read', 'retry'),
    },
    CRM_MODULE: {
        "customer": _with_imex('create', 'read', 'update', 'delete', 'history'),
        "contact": _with_imex('create', 'read', 'update', 'delete'),
    },
    SALES_MODULE: {
        "quotation": _with_imex('create', 'read', 'update', 'delete', 'approve', 'send', 'revise'),
        "proforma_invoice": _with_imex('create', 'read', 'update', 'delete', 'send', 'confirm'),
        "sales_order": _with_imex('create', 'read', 'update', 'delete', 'approve', 'confirm', 'close', 'acknowledge'),
        "delivery_note": _with_imex('create', 'read', 'update', 'delete', 'post'),
        "sales_invoice": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
        "credit_note": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
        "customer_payment": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
        "sales_return": _with_imex('create', 'read', 'update', 'delete', 'post'),
    },
    PURCHASE_MODULE: {
        "supplier": _with_imex('create', 'read', 'update', 'delete', 'history'),
        "supplier_product": _with_imex('create', 'read', 'update', 'delete', 'link'),
        "purchase_order": _with_imex('create', 'read', 'update', 'delete', 'approve', 'issue', 'close'),
        "goods_receipt": _with_imex('create', 'read', 'update', 'delete', 'post'),
        "quality_inspection": ('create', 'read', 'update', 'approve'),
        "purchase_invoice": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
        "debit_note": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
        "supplier_payment": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
        "landed_cost": (
            "read",
            "create",
            "update",
            "post",
            "cancel",
        ),
        "purchase_return": _with_imex('create', 'read', 'update', 'delete', 'post', 'cancel'),
    },
    LOGISTICS_MODULE: {
        "package": _with_imex('create', 'read', 'update', 'delete'),
        "shipment": _with_imex('create', 'read', 'update', 'delete', 'dispatch', 'close'),
    },
    INVENTORY_MODULE: {
        "unit": _with_imex('create', 'read', 'update', 'delete'),
        "category": _with_imex('create', 'read', 'update', 'delete'),
        "product": _with_imex('create', 'read', 'update', 'delete', 'history'),
        "price_list": ('create', 'read', 'update', 'delete'),
        "warehouse": ('create', 'read', 'update', 'delete'),
        "stock": ('read', 'update'),
        "cost": ('read',),
        "stock_transfer": (
            "create",
            "read",
            "update",
            "delete",
            "post",
        ),
        "stock_adjustment": (
            "create",
            "read",
            "update",
            "delete",
            "post",
        ),
    },
    ACCOUNTING_MODULE: {
        "account": ('create', 'read', 'update', 'delete'),
        "journal_entry": (
            "create",
            "read",
            "update",
            "delete",
            "post",
            "reverse",
        ),
        "opening_balance": ('manage',),
        "period": ('lock', 'override'),
        "credit_control": ('override',),
    },
    REPORTS_MODULE: {
        "report": (
            "ledger",
            "tax",
            "ar_ap",
            "inventory",
            "financial",
        ),
    },
    MASTERS_MODULE: {
        "currency": ('create', 'read', 'update', 'delete'),
        "exchange_rate": ('create', 'read', 'update', 'delete'),
        "tax": ('create', 'read', 'update', 'delete'),
        "payment_term": ('create', 'read', 'update', 'delete'),
        "terms_template": ('create', 'read', 'update', 'delete'),
        "document_sequence": ('create', 'read', 'update', 'delete'),
    },
}


# (old_module, resource) → new_module. Action names stay the same.
_RESOURCE_MODULE_REMAP: dict[tuple[str, str], str] = {
    ("erp", "quotation"): SALES_MODULE,
    ("erp", "proforma_invoice"): SALES_MODULE,
    ("erp", "sales_order"): SALES_MODULE,
    ("erp", "sales_invoice"): SALES_MODULE,
    ("erp", "credit_note"): SALES_MODULE,
    ("erp", "customer_payment"): SALES_MODULE,
    ("inventory", "delivery_note"): SALES_MODULE,
    ("inventory", "sales_return"): SALES_MODULE,
    ("erp", "supplier"): PURCHASE_MODULE,
    ("erp", "supplier_product"): PURCHASE_MODULE,
    ("erp", "purchase_order"): PURCHASE_MODULE,
    ("inventory", "goods_receipt"): PURCHASE_MODULE,
    ("inventory", "quality_inspection"): PURCHASE_MODULE,
    ("erp", "purchase_invoice"): PURCHASE_MODULE,
    ("erp", "debit_note"): PURCHASE_MODULE,
    ("erp", "supplier_payment"): PURCHASE_MODULE,
    ("erp", "landed_cost"): PURCHASE_MODULE,
    ("inventory", "package"): LOGISTICS_MODULE,
    ("inventory", "shipment"): LOGISTICS_MODULE,
    ("erp", "account"): ACCOUNTING_MODULE,
    ("erp", "journal_entry"): ACCOUNTING_MODULE,
    ("erp", "opening_balance"): ACCOUNTING_MODULE,
    ("erp", "period"): ACCOUNTING_MODULE,
    ("erp", "credit_control"): ACCOUNTING_MODULE,
    ("erp", "report"): REPORTS_MODULE,
    ("erp", "currency"): MASTERS_MODULE,
    ("erp", "exchange_rate"): MASTERS_MODULE,
    ("erp", "tax"): MASTERS_MODULE,
    ("erp", "payment_term"): MASTERS_MODULE,
    ("erp", "terms_template"): MASTERS_MODULE,
    ("erp", "document_sequence"): MASTERS_MODULE,
}


def _permissions_for(module: str) -> tuple[str, ...]:
    return tuple(
        build_permission(module, resource, action)
        for resource, actions in _CATALOG_ACTIONS[module].items()
        for action in actions
    )


IDENTITY_PERMISSIONS: tuple[str, ...] = _permissions_for(IDENTITY_MODULE)
CRM_PERMISSIONS: tuple[str, ...] = _permissions_for(CRM_MODULE)
SALES_PERMISSIONS: tuple[str, ...] = _permissions_for(SALES_MODULE)
PURCHASE_PERMISSIONS: tuple[str, ...] = _permissions_for(PURCHASE_MODULE)
LOGISTICS_PERMISSIONS: tuple[str, ...] = _permissions_for(LOGISTICS_MODULE)
INVENTORY_PERMISSIONS: tuple[str, ...] = _permissions_for(INVENTORY_MODULE)
ACCOUNTING_PERMISSIONS: tuple[str, ...] = _permissions_for(ACCOUNTING_MODULE)
REPORTS_PERMISSIONS: tuple[str, ...] = _permissions_for(REPORTS_MODULE)
MASTERS_PERMISSIONS: tuple[str, ...] = _permissions_for(MASTERS_MODULE)
CATALOG_PERMISSIONS: tuple[str, ...] = (
    IDENTITY_PERMISSIONS +
    CRM_PERMISSIONS +
    SALES_PERMISSIONS +
    PURCHASE_PERMISSIONS +
    LOGISTICS_PERMISSIONS +
    INVENTORY_PERMISSIONS +
    ACCOUNTING_PERMISSIONS +
    REPORTS_PERMISSIONS +
    MASTERS_PERMISSIONS
)


def permission_code_remap() -> dict[str, str]:
    """Map retired catalog codes onto their replacements."""

    mapping: dict[str, str] = {}
    for (old_module, resource), new_module in _RESOURCE_MODULE_REMAP.items():
        actions = _CATALOG_ACTIONS.get(new_module, {}).get(resource, ())
        for action in actions:
            old = build_permission(old_module, resource, action)
            new = build_permission(new_module, resource, action)
            if old != new:
                mapping[old] = new
    return mapping


USER_CREATE = build_permission(IDENTITY_MODULE, "user", "create")
USER_READ = build_permission(IDENTITY_MODULE, "user", "read")
USER_UPDATE = build_permission(IDENTITY_MODULE, "user", "update")
USER_DELETE = build_permission(IDENTITY_MODULE, "user", "delete")
ROLE_CREATE = build_permission(IDENTITY_MODULE, "role", "create")
ROLE_READ = build_permission(IDENTITY_MODULE, "role", "read")
ROLE_UPDATE = build_permission(IDENTITY_MODULE, "role", "update")
ROLE_DELETE = build_permission(IDENTITY_MODULE, "role", "delete")
PERMISSION_READ = build_permission(IDENTITY_MODULE, "permission", "read")
ORGANIZATION_READ = build_permission(IDENTITY_MODULE, "organization", "read")
ORGANIZATION_UPDATE = build_permission(IDENTITY_MODULE, "organization", "update")
DEPARTMENT_CREATE = build_permission(IDENTITY_MODULE, "department", "create")
DEPARTMENT_READ = build_permission(IDENTITY_MODULE, "department", "read")
DEPARTMENT_UPDATE = build_permission(IDENTITY_MODULE, "department", "update")
DEPARTMENT_DELETE = build_permission(IDENTITY_MODULE, "department", "delete")
BRANCH_CREATE = build_permission(IDENTITY_MODULE, "branch", "create")
BRANCH_READ = build_permission(IDENTITY_MODULE, "branch", "read")
BRANCH_UPDATE = build_permission(IDENTITY_MODULE, "branch", "update")
BRANCH_DELETE = build_permission(IDENTITY_MODULE, "branch", "delete")
EMPLOYEE_CREATE = build_permission(IDENTITY_MODULE, "employee", "create")
EMPLOYEE_READ = build_permission(IDENTITY_MODULE, "employee", "read")
EMPLOYEE_UPDATE = build_permission(IDENTITY_MODULE, "employee", "update")
EMPLOYEE_DELETE = build_permission(IDENTITY_MODULE, "employee", "delete")
AUDIT_LOG_READ = build_permission(IDENTITY_MODULE, "audit_log", "read")
ATTACHMENT_CREATE = build_permission(IDENTITY_MODULE, "attachment", "create")
ATTACHMENT_READ = build_permission(IDENTITY_MODULE, "attachment", "read")
ATTACHMENT_UPDATE = build_permission(IDENTITY_MODULE, "attachment", "update")
ATTACHMENT_DELETE = build_permission(IDENTITY_MODULE, "attachment", "delete")
OUTBOX_EVENT_READ = build_permission(IDENTITY_MODULE, "outbox_event", "read")
OUTBOX_EVENT_RETRY = build_permission(IDENTITY_MODULE, "outbox_event", "retry")

CUSTOMER_CREATE = build_permission(CRM_MODULE, "customer", "create")
CUSTOMER_READ = build_permission(CRM_MODULE, "customer", "read")
CUSTOMER_UPDATE = build_permission(CRM_MODULE, "customer", "update")
CUSTOMER_DELETE = build_permission(CRM_MODULE, "customer", "delete")
CUSTOMER_HISTORY = build_permission(CRM_MODULE, "customer", "history")
CUSTOMER_IMPORT = build_permission(CRM_MODULE, "customer", "import")
CUSTOMER_EXPORT = build_permission(CRM_MODULE, "customer", "export")
CONTACT_CREATE = build_permission(CRM_MODULE, "contact", "create")
CONTACT_READ = build_permission(CRM_MODULE, "contact", "read")
CONTACT_UPDATE = build_permission(CRM_MODULE, "contact", "update")
CONTACT_DELETE = build_permission(CRM_MODULE, "contact", "delete")
CONTACT_IMPORT = build_permission(CRM_MODULE, "contact", "import")
CONTACT_EXPORT = build_permission(CRM_MODULE, "contact", "export")

QUOTATION_CREATE = build_permission(SALES_MODULE, "quotation", "create")
QUOTATION_READ = build_permission(SALES_MODULE, "quotation", "read")
QUOTATION_UPDATE = build_permission(SALES_MODULE, "quotation", "update")
QUOTATION_DELETE = build_permission(SALES_MODULE, "quotation", "delete")
QUOTATION_APPROVE = build_permission(SALES_MODULE, "quotation", "approve")
QUOTATION_SEND = build_permission(SALES_MODULE, "quotation", "send")
QUOTATION_REVISE = build_permission(SALES_MODULE, "quotation", "revise")
QUOTATION_IMPORT = build_permission(SALES_MODULE, "quotation", "import")
QUOTATION_EXPORT = build_permission(SALES_MODULE, "quotation", "export")
PROFORMA_INVOICE_CREATE = build_permission(SALES_MODULE, "proforma_invoice", "create")
PROFORMA_INVOICE_READ = build_permission(SALES_MODULE, "proforma_invoice", "read")
PROFORMA_INVOICE_UPDATE = build_permission(SALES_MODULE, "proforma_invoice", "update")
PROFORMA_INVOICE_DELETE = build_permission(SALES_MODULE, "proforma_invoice", "delete")
PROFORMA_INVOICE_SEND = build_permission(SALES_MODULE, "proforma_invoice", "send")
PROFORMA_INVOICE_CONFIRM = build_permission(SALES_MODULE, "proforma_invoice", "confirm")
PROFORMA_INVOICE_IMPORT = build_permission(SALES_MODULE, "proforma_invoice", "import")
PROFORMA_INVOICE_EXPORT = build_permission(SALES_MODULE, "proforma_invoice", "export")
SALES_ORDER_CREATE = build_permission(SALES_MODULE, "sales_order", "create")
SALES_ORDER_READ = build_permission(SALES_MODULE, "sales_order", "read")
SALES_ORDER_UPDATE = build_permission(SALES_MODULE, "sales_order", "update")
SALES_ORDER_DELETE = build_permission(SALES_MODULE, "sales_order", "delete")
SALES_ORDER_APPROVE = build_permission(SALES_MODULE, "sales_order", "approve")
SALES_ORDER_CONFIRM = build_permission(SALES_MODULE, "sales_order", "confirm")
SALES_ORDER_CLOSE = build_permission(SALES_MODULE, "sales_order", "close")
SALES_ORDER_ACKNOWLEDGE = build_permission(SALES_MODULE, "sales_order", "acknowledge")
SALES_ORDER_IMPORT = build_permission(SALES_MODULE, "sales_order", "import")
SALES_ORDER_EXPORT = build_permission(SALES_MODULE, "sales_order", "export")
DELIVERY_NOTE_CREATE = build_permission(SALES_MODULE, "delivery_note", "create")
DELIVERY_NOTE_READ = build_permission(SALES_MODULE, "delivery_note", "read")
DELIVERY_NOTE_UPDATE = build_permission(SALES_MODULE, "delivery_note", "update")
DELIVERY_NOTE_DELETE = build_permission(SALES_MODULE, "delivery_note", "delete")
DELIVERY_NOTE_POST = build_permission(SALES_MODULE, "delivery_note", "post")
DELIVERY_NOTE_IMPORT = build_permission(SALES_MODULE, "delivery_note", "import")
DELIVERY_NOTE_EXPORT = build_permission(SALES_MODULE, "delivery_note", "export")
SALES_INVOICE_CREATE = build_permission(SALES_MODULE, "sales_invoice", "create")
SALES_INVOICE_READ = build_permission(SALES_MODULE, "sales_invoice", "read")
SALES_INVOICE_UPDATE = build_permission(SALES_MODULE, "sales_invoice", "update")
SALES_INVOICE_DELETE = build_permission(SALES_MODULE, "sales_invoice", "delete")
SALES_INVOICE_POST = build_permission(SALES_MODULE, "sales_invoice", "post")
SALES_INVOICE_CANCEL = build_permission(SALES_MODULE, "sales_invoice", "cancel")
SALES_INVOICE_IMPORT = build_permission(SALES_MODULE, "sales_invoice", "import")
SALES_INVOICE_EXPORT = build_permission(SALES_MODULE, "sales_invoice", "export")
CREDIT_NOTE_CREATE = build_permission(SALES_MODULE, "credit_note", "create")
CREDIT_NOTE_READ = build_permission(SALES_MODULE, "credit_note", "read")
CREDIT_NOTE_UPDATE = build_permission(SALES_MODULE, "credit_note", "update")
CREDIT_NOTE_DELETE = build_permission(SALES_MODULE, "credit_note", "delete")
CREDIT_NOTE_POST = build_permission(SALES_MODULE, "credit_note", "post")
CREDIT_NOTE_CANCEL = build_permission(SALES_MODULE, "credit_note", "cancel")
CREDIT_NOTE_IMPORT = build_permission(SALES_MODULE, "credit_note", "import")
CREDIT_NOTE_EXPORT = build_permission(SALES_MODULE, "credit_note", "export")
CUSTOMER_PAYMENT_CREATE = build_permission(SALES_MODULE, "customer_payment", "create")
CUSTOMER_PAYMENT_READ = build_permission(SALES_MODULE, "customer_payment", "read")
CUSTOMER_PAYMENT_UPDATE = build_permission(SALES_MODULE, "customer_payment", "update")
CUSTOMER_PAYMENT_DELETE = build_permission(SALES_MODULE, "customer_payment", "delete")
CUSTOMER_PAYMENT_POST = build_permission(SALES_MODULE, "customer_payment", "post")
CUSTOMER_PAYMENT_CANCEL = build_permission(SALES_MODULE, "customer_payment", "cancel")
CUSTOMER_PAYMENT_IMPORT = build_permission(SALES_MODULE, "customer_payment", "import")
CUSTOMER_PAYMENT_EXPORT = build_permission(SALES_MODULE, "customer_payment", "export")
SALES_RETURN_CREATE = build_permission(SALES_MODULE, "sales_return", "create")
SALES_RETURN_READ = build_permission(SALES_MODULE, "sales_return", "read")
SALES_RETURN_UPDATE = build_permission(SALES_MODULE, "sales_return", "update")
SALES_RETURN_DELETE = build_permission(SALES_MODULE, "sales_return", "delete")
SALES_RETURN_POST = build_permission(SALES_MODULE, "sales_return", "post")
SALES_RETURN_IMPORT = build_permission(SALES_MODULE, "sales_return", "import")
SALES_RETURN_EXPORT = build_permission(SALES_MODULE, "sales_return", "export")

SUPPLIER_CREATE = build_permission(PURCHASE_MODULE, "supplier", "create")
SUPPLIER_READ = build_permission(PURCHASE_MODULE, "supplier", "read")
SUPPLIER_UPDATE = build_permission(PURCHASE_MODULE, "supplier", "update")
SUPPLIER_DELETE = build_permission(PURCHASE_MODULE, "supplier", "delete")
SUPPLIER_HISTORY = build_permission(PURCHASE_MODULE, "supplier", "history")
SUPPLIER_IMPORT = build_permission(PURCHASE_MODULE, "supplier", "import")
SUPPLIER_EXPORT = build_permission(PURCHASE_MODULE, "supplier", "export")
SUPPLIER_PRODUCT_CREATE = build_permission(PURCHASE_MODULE, "supplier_product", "create")
SUPPLIER_PRODUCT_READ = build_permission(PURCHASE_MODULE, "supplier_product", "read")
SUPPLIER_PRODUCT_UPDATE = build_permission(PURCHASE_MODULE, "supplier_product", "update")
SUPPLIER_PRODUCT_DELETE = build_permission(PURCHASE_MODULE, "supplier_product", "delete")
SUPPLIER_PRODUCT_LINK = build_permission(PURCHASE_MODULE, "supplier_product", "link")
SUPPLIER_PRODUCT_IMPORT = build_permission(PURCHASE_MODULE, "supplier_product", "import")
SUPPLIER_PRODUCT_EXPORT = build_permission(PURCHASE_MODULE, "supplier_product", "export")
PURCHASE_ORDER_CREATE = build_permission(PURCHASE_MODULE, "purchase_order", "create")
PURCHASE_ORDER_READ = build_permission(PURCHASE_MODULE, "purchase_order", "read")
PURCHASE_ORDER_UPDATE = build_permission(PURCHASE_MODULE, "purchase_order", "update")
PURCHASE_ORDER_DELETE = build_permission(PURCHASE_MODULE, "purchase_order", "delete")
PURCHASE_ORDER_APPROVE = build_permission(PURCHASE_MODULE, "purchase_order", "approve")
PURCHASE_ORDER_ISSUE = build_permission(PURCHASE_MODULE, "purchase_order", "issue")
PURCHASE_ORDER_CLOSE = build_permission(PURCHASE_MODULE, "purchase_order", "close")
PURCHASE_ORDER_IMPORT = build_permission(PURCHASE_MODULE, "purchase_order", "import")
PURCHASE_ORDER_EXPORT = build_permission(PURCHASE_MODULE, "purchase_order", "export")
GOODS_RECEIPT_CREATE = build_permission(PURCHASE_MODULE, "goods_receipt", "create")
GOODS_RECEIPT_READ = build_permission(PURCHASE_MODULE, "goods_receipt", "read")
GOODS_RECEIPT_UPDATE = build_permission(PURCHASE_MODULE, "goods_receipt", "update")
GOODS_RECEIPT_DELETE = build_permission(PURCHASE_MODULE, "goods_receipt", "delete")
GOODS_RECEIPT_POST = build_permission(PURCHASE_MODULE, "goods_receipt", "post")
GOODS_RECEIPT_IMPORT = build_permission(PURCHASE_MODULE, "goods_receipt", "import")
GOODS_RECEIPT_EXPORT = build_permission(PURCHASE_MODULE, "goods_receipt", "export")
QUALITY_INSPECTION_CREATE = build_permission(PURCHASE_MODULE, "quality_inspection", "create")
QUALITY_INSPECTION_READ = build_permission(PURCHASE_MODULE, "quality_inspection", "read")
QUALITY_INSPECTION_UPDATE = build_permission(PURCHASE_MODULE, "quality_inspection", "update")
QUALITY_INSPECTION_APPROVE = build_permission(PURCHASE_MODULE, "quality_inspection", "approve")
PURCHASE_INVOICE_CREATE = build_permission(PURCHASE_MODULE, "purchase_invoice", "create")
PURCHASE_INVOICE_READ = build_permission(PURCHASE_MODULE, "purchase_invoice", "read")
PURCHASE_INVOICE_UPDATE = build_permission(PURCHASE_MODULE, "purchase_invoice", "update")
PURCHASE_INVOICE_DELETE = build_permission(PURCHASE_MODULE, "purchase_invoice", "delete")
PURCHASE_INVOICE_POST = build_permission(PURCHASE_MODULE, "purchase_invoice", "post")
PURCHASE_INVOICE_CANCEL = build_permission(PURCHASE_MODULE, "purchase_invoice", "cancel")
PURCHASE_INVOICE_IMPORT = build_permission(PURCHASE_MODULE, "purchase_invoice", "import")
PURCHASE_INVOICE_EXPORT = build_permission(PURCHASE_MODULE, "purchase_invoice", "export")
DEBIT_NOTE_CREATE = build_permission(PURCHASE_MODULE, "debit_note", "create")
DEBIT_NOTE_READ = build_permission(PURCHASE_MODULE, "debit_note", "read")
DEBIT_NOTE_UPDATE = build_permission(PURCHASE_MODULE, "debit_note", "update")
DEBIT_NOTE_DELETE = build_permission(PURCHASE_MODULE, "debit_note", "delete")
DEBIT_NOTE_POST = build_permission(PURCHASE_MODULE, "debit_note", "post")
DEBIT_NOTE_CANCEL = build_permission(PURCHASE_MODULE, "debit_note", "cancel")
DEBIT_NOTE_IMPORT = build_permission(PURCHASE_MODULE, "debit_note", "import")
DEBIT_NOTE_EXPORT = build_permission(PURCHASE_MODULE, "debit_note", "export")
SUPPLIER_PAYMENT_CREATE = build_permission(PURCHASE_MODULE, "supplier_payment", "create")
SUPPLIER_PAYMENT_READ = build_permission(PURCHASE_MODULE, "supplier_payment", "read")
SUPPLIER_PAYMENT_UPDATE = build_permission(PURCHASE_MODULE, "supplier_payment", "update")
SUPPLIER_PAYMENT_DELETE = build_permission(PURCHASE_MODULE, "supplier_payment", "delete")
SUPPLIER_PAYMENT_POST = build_permission(PURCHASE_MODULE, "supplier_payment", "post")
SUPPLIER_PAYMENT_CANCEL = build_permission(PURCHASE_MODULE, "supplier_payment", "cancel")
SUPPLIER_PAYMENT_IMPORT = build_permission(PURCHASE_MODULE, "supplier_payment", "import")
SUPPLIER_PAYMENT_EXPORT = build_permission(PURCHASE_MODULE, "supplier_payment", "export")
LANDED_COST_READ = build_permission(PURCHASE_MODULE, "landed_cost", "read")
LANDED_COST_CREATE = build_permission(PURCHASE_MODULE, "landed_cost", "create")
LANDED_COST_UPDATE = build_permission(PURCHASE_MODULE, "landed_cost", "update")
LANDED_COST_POST = build_permission(PURCHASE_MODULE, "landed_cost", "post")
LANDED_COST_CANCEL = build_permission(PURCHASE_MODULE, "landed_cost", "cancel")
PURCHASE_RETURN_CREATE = build_permission(PURCHASE_MODULE, "purchase_return", "create")
PURCHASE_RETURN_READ = build_permission(PURCHASE_MODULE, "purchase_return", "read")
PURCHASE_RETURN_UPDATE = build_permission(PURCHASE_MODULE, "purchase_return", "update")
PURCHASE_RETURN_DELETE = build_permission(PURCHASE_MODULE, "purchase_return", "delete")
PURCHASE_RETURN_POST = build_permission(PURCHASE_MODULE, "purchase_return", "post")
PURCHASE_RETURN_CANCEL = build_permission(PURCHASE_MODULE, "purchase_return", "cancel")
PURCHASE_RETURN_IMPORT = build_permission(PURCHASE_MODULE, "purchase_return", "import")
PURCHASE_RETURN_EXPORT = build_permission(PURCHASE_MODULE, "purchase_return", "export")

PACKAGE_CREATE = build_permission(LOGISTICS_MODULE, "package", "create")
PACKAGE_READ = build_permission(LOGISTICS_MODULE, "package", "read")
PACKAGE_UPDATE = build_permission(LOGISTICS_MODULE, "package", "update")
PACKAGE_DELETE = build_permission(LOGISTICS_MODULE, "package", "delete")
PACKAGE_IMPORT = build_permission(LOGISTICS_MODULE, "package", "import")
PACKAGE_EXPORT = build_permission(LOGISTICS_MODULE, "package", "export")
SHIPMENT_CREATE = build_permission(LOGISTICS_MODULE, "shipment", "create")
SHIPMENT_READ = build_permission(LOGISTICS_MODULE, "shipment", "read")
SHIPMENT_UPDATE = build_permission(LOGISTICS_MODULE, "shipment", "update")
SHIPMENT_DELETE = build_permission(LOGISTICS_MODULE, "shipment", "delete")
SHIPMENT_DISPATCH = build_permission(LOGISTICS_MODULE, "shipment", "dispatch")
SHIPMENT_CLOSE = build_permission(LOGISTICS_MODULE, "shipment", "close")
SHIPMENT_IMPORT = build_permission(LOGISTICS_MODULE, "shipment", "import")
SHIPMENT_EXPORT = build_permission(LOGISTICS_MODULE, "shipment", "export")

UNIT_CREATE = build_permission(INVENTORY_MODULE, "unit", "create")
UNIT_READ = build_permission(INVENTORY_MODULE, "unit", "read")
UNIT_UPDATE = build_permission(INVENTORY_MODULE, "unit", "update")
UNIT_DELETE = build_permission(INVENTORY_MODULE, "unit", "delete")
UNIT_IMPORT = build_permission(INVENTORY_MODULE, "unit", "import")
UNIT_EXPORT = build_permission(INVENTORY_MODULE, "unit", "export")
CATEGORY_CREATE = build_permission(INVENTORY_MODULE, "category", "create")
CATEGORY_READ = build_permission(INVENTORY_MODULE, "category", "read")
CATEGORY_UPDATE = build_permission(INVENTORY_MODULE, "category", "update")
CATEGORY_DELETE = build_permission(INVENTORY_MODULE, "category", "delete")
CATEGORY_IMPORT = build_permission(INVENTORY_MODULE, "category", "import")
CATEGORY_EXPORT = build_permission(INVENTORY_MODULE, "category", "export")
PRODUCT_CREATE = build_permission(INVENTORY_MODULE, "product", "create")
PRODUCT_READ = build_permission(INVENTORY_MODULE, "product", "read")
PRODUCT_UPDATE = build_permission(INVENTORY_MODULE, "product", "update")
PRODUCT_DELETE = build_permission(INVENTORY_MODULE, "product", "delete")
PRODUCT_HISTORY = build_permission(INVENTORY_MODULE, "product", "history")
PRODUCT_IMPORT = build_permission(INVENTORY_MODULE, "product", "import")
PRODUCT_EXPORT = build_permission(INVENTORY_MODULE, "product", "export")
PRICE_LIST_CREATE = build_permission(INVENTORY_MODULE, "price_list", "create")
PRICE_LIST_READ = build_permission(INVENTORY_MODULE, "price_list", "read")
PRICE_LIST_UPDATE = build_permission(INVENTORY_MODULE, "price_list", "update")
PRICE_LIST_DELETE = build_permission(INVENTORY_MODULE, "price_list", "delete")
WAREHOUSE_CREATE = build_permission(INVENTORY_MODULE, "warehouse", "create")
WAREHOUSE_READ = build_permission(INVENTORY_MODULE, "warehouse", "read")
WAREHOUSE_UPDATE = build_permission(INVENTORY_MODULE, "warehouse", "update")
WAREHOUSE_DELETE = build_permission(INVENTORY_MODULE, "warehouse", "delete")
STOCK_READ = build_permission(INVENTORY_MODULE, "stock", "read")
STOCK_UPDATE = build_permission(INVENTORY_MODULE, "stock", "update")
COST_READ = build_permission(INVENTORY_MODULE, "cost", "read")
STOCK_TRANSFER_CREATE = build_permission(INVENTORY_MODULE, "stock_transfer", "create")
STOCK_TRANSFER_READ = build_permission(INVENTORY_MODULE, "stock_transfer", "read")
STOCK_TRANSFER_UPDATE = build_permission(INVENTORY_MODULE, "stock_transfer", "update")
STOCK_TRANSFER_DELETE = build_permission(INVENTORY_MODULE, "stock_transfer", "delete")
STOCK_TRANSFER_POST = build_permission(INVENTORY_MODULE, "stock_transfer", "post")
STOCK_ADJUSTMENT_CREATE = build_permission(INVENTORY_MODULE, "stock_adjustment", "create")
STOCK_ADJUSTMENT_READ = build_permission(INVENTORY_MODULE, "stock_adjustment", "read")
STOCK_ADJUSTMENT_UPDATE = build_permission(INVENTORY_MODULE, "stock_adjustment", "update")
STOCK_ADJUSTMENT_DELETE = build_permission(INVENTORY_MODULE, "stock_adjustment", "delete")
STOCK_ADJUSTMENT_POST = build_permission(INVENTORY_MODULE, "stock_adjustment", "post")

ACCOUNT_CREATE = build_permission(ACCOUNTING_MODULE, "account", "create")
ACCOUNT_READ = build_permission(ACCOUNTING_MODULE, "account", "read")
ACCOUNT_UPDATE = build_permission(ACCOUNTING_MODULE, "account", "update")
ACCOUNT_DELETE = build_permission(ACCOUNTING_MODULE, "account", "delete")
JOURNAL_ENTRY_CREATE = build_permission(ACCOUNTING_MODULE, "journal_entry", "create")
JOURNAL_ENTRY_READ = build_permission(ACCOUNTING_MODULE, "journal_entry", "read")
JOURNAL_ENTRY_UPDATE = build_permission(ACCOUNTING_MODULE, "journal_entry", "update")
JOURNAL_ENTRY_DELETE = build_permission(ACCOUNTING_MODULE, "journal_entry", "delete")
JOURNAL_ENTRY_POST = build_permission(ACCOUNTING_MODULE, "journal_entry", "post")
JOURNAL_ENTRY_REVERSE = build_permission(ACCOUNTING_MODULE, "journal_entry", "reverse")
OPENING_BALANCE_MANAGE = build_permission(ACCOUNTING_MODULE, "opening_balance", "manage")
PERIOD_LOCK = build_permission(ACCOUNTING_MODULE, "period", "lock")
PERIOD_OVERRIDE = build_permission(ACCOUNTING_MODULE, "period", "override")
CREDIT_CONTROL_OVERRIDE = build_permission(ACCOUNTING_MODULE, "credit_control", "override")

REPORT_LEDGER = build_permission(REPORTS_MODULE, "report", "ledger")
REPORT_TAX = build_permission(REPORTS_MODULE, "report", "tax")
REPORT_AR_AP = build_permission(REPORTS_MODULE, "report", "ar_ap")
REPORT_INVENTORY = build_permission(REPORTS_MODULE, "report", "inventory")
REPORT_FINANCIAL = build_permission(REPORTS_MODULE, "report", "financial")

CURRENCY_CREATE = build_permission(MASTERS_MODULE, "currency", "create")
CURRENCY_READ = build_permission(MASTERS_MODULE, "currency", "read")
CURRENCY_UPDATE = build_permission(MASTERS_MODULE, "currency", "update")
CURRENCY_DELETE = build_permission(MASTERS_MODULE, "currency", "delete")
EXCHANGE_RATE_CREATE = build_permission(MASTERS_MODULE, "exchange_rate", "create")
EXCHANGE_RATE_READ = build_permission(MASTERS_MODULE, "exchange_rate", "read")
EXCHANGE_RATE_UPDATE = build_permission(MASTERS_MODULE, "exchange_rate", "update")
EXCHANGE_RATE_DELETE = build_permission(MASTERS_MODULE, "exchange_rate", "delete")
TAX_CREATE = build_permission(MASTERS_MODULE, "tax", "create")
TAX_READ = build_permission(MASTERS_MODULE, "tax", "read")
TAX_UPDATE = build_permission(MASTERS_MODULE, "tax", "update")
TAX_DELETE = build_permission(MASTERS_MODULE, "tax", "delete")
PAYMENT_TERM_CREATE = build_permission(MASTERS_MODULE, "payment_term", "create")
PAYMENT_TERM_READ = build_permission(MASTERS_MODULE, "payment_term", "read")
PAYMENT_TERM_UPDATE = build_permission(MASTERS_MODULE, "payment_term", "update")
PAYMENT_TERM_DELETE = build_permission(MASTERS_MODULE, "payment_term", "delete")
TERMS_TEMPLATE_CREATE = build_permission(MASTERS_MODULE, "terms_template", "create")
TERMS_TEMPLATE_READ = build_permission(MASTERS_MODULE, "terms_template", "read")
TERMS_TEMPLATE_UPDATE = build_permission(MASTERS_MODULE, "terms_template", "update")
TERMS_TEMPLATE_DELETE = build_permission(MASTERS_MODULE, "terms_template", "delete")
DOCUMENT_SEQUENCE_CREATE = build_permission(MASTERS_MODULE, "document_sequence", "create")
DOCUMENT_SEQUENCE_READ = build_permission(MASTERS_MODULE, "document_sequence", "read")
DOCUMENT_SEQUENCE_UPDATE = build_permission(MASTERS_MODULE, "document_sequence", "update")
DOCUMENT_SEQUENCE_DELETE = build_permission(MASTERS_MODULE, "document_sequence", "delete")

SYSTEM_ADMIN_ROLE_NAME = "Superadmin"


def parsed_identity_permissions() -> tuple[ParsedPermission, ...]:
    """Return the identity catalog as parsed permission values."""

    return tuple(parse_permission(value) for value in IDENTITY_PERMISSIONS)


def parsed_catalog_permissions() -> tuple[ParsedPermission, ...]:
    """Return the full permission catalog as parsed permission values."""

    return tuple(parse_permission(value) for value in CATALOG_PERMISSIONS)



async def seed_tenant_permissions(
    session: AsyncSession,
    tenant_id: UUID,
) -> list[Permission]:
    """Insert missing catalog rows for a tenant and return the full set."""

    existing_result = await session.execute(
        select(Permission).where(Permission.tenant_id == tenant_id)
    )
    existing_rows = list(existing_result.scalars().all())
    existing_keys = {(row.module, row.resource, row.action) for row in existing_rows}

    created: list[Permission] = []
    for parsed in parsed_catalog_permissions():
        key = (parsed.module, parsed.resource, parsed.action)
        if key in existing_keys:
            continue
        row = Permission(
            tenant_id=tenant_id,
            module=parsed.module,
            resource=parsed.resource,
            action=parsed.action,
        )
        session.add(row)
        created.append(row)

    if created:
        await session.flush()
        existing_rows.extend(created)

    return existing_rows


async def grant_catalog_to_role(
    session: AsyncSession,
    tenant_id: UUID,
    role_id: UUID,
) -> list[Permission]:
    """Seed the catalog and grant every catalog permission to ``role_id``."""

    permissions = await seed_tenant_permissions(session, tenant_id)
    existing_result = await session.execute(
        select(RolePermission.permission_id).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role_id == role_id,
        )
    )
    existing_ids = {row[0] for row in existing_result.all()}
    created = False
    for permission in permissions:
        if permission.id in existing_ids:
            continue
        session.add(
            RolePermission(
                tenant_id=tenant_id,
                role_id=role_id,
                permission_id=permission.id,
            )
        )
        created = True
    if created:
        await session.flush()
    return permissions


async def get_system_admin_role(
    session: AsyncSession,
    tenant_id: UUID,
) -> Role | None:
    """Return the tenant's system Superadmin role, if it exists."""

    result = await session.execute(
        select(Role).where(
            Role.tenant_id == tenant_id,
            Role.name == SYSTEM_ADMIN_ROLE_NAME,
            Role.is_system_role.is_(True),
        )
    )
    return result.scalar_one_or_none()

