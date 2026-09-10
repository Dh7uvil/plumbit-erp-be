"""Canonical permission catalog registry and per-tenant seeding."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Permission, Role, RolePermission
from app.core.permissions import Permission as ParsedPermission
from app.core.permissions import build_permission, parse_permission

IDENTITY_MODULE = "identity"
CRM_MODULE = "crm"
INVENTORY_MODULE = "inventory"
ERP_MODULE = "erp"

_CATALOG_ACTIONS: dict[str, dict[str, tuple[str, ...]]] = {
    IDENTITY_MODULE: {
        "user": ("create", "read", "update", "delete"),
        "role": ("create", "read", "update", "delete"),
        "permission": ("read",),
        "organization": ("read", "update"),
        "department": ("create", "read", "update", "delete"),
        "branch": ("create", "read", "update", "delete"),
        "employee": ("create", "read", "update", "delete"),
        "audit_log": ("read",),
        "attachment": ("create", "read", "update", "delete"),
        "outbox_event": ("read", "retry"),
    },
    CRM_MODULE: {
        "customer": ("create", "read", "update", "delete", "history"),
        "contact": ("create", "read", "update", "delete"),
    },
    INVENTORY_MODULE: {
        "unit": ("create", "read", "update", "delete"),
        "category": ("create", "read", "update", "delete"),
        "product": ("create", "read", "update", "delete", "history"),
        "price_list": ("create", "read", "update", "delete"),
        "warehouse": ("create", "read", "update", "delete"),
        "stock": ("read", "update"),
        "cost": ("read",),
        "stock_transfer": ("create", "read", "update", "delete", "post"),
        "stock_adjustment": ("create", "read", "update", "delete", "post"),
        "goods_receipt": ("create", "read", "update", "delete", "post"),
        "quality_inspection": ("create", "read", "update", "approve"),
        "delivery_note": ("create", "read", "update", "delete", "post"),
        "package": ("create", "read", "update", "delete"),
        "shipment": ("create", "read", "update", "delete", "dispatch", "close"),
        "sales_return": ("create", "read", "update", "delete", "post"),
    },
    ERP_MODULE: {
        "supplier": ("create", "read", "update", "delete", "history"),
        "supplier_product": ("create", "read", "update", "delete", "link"),
        "currency": ("create", "read", "update", "delete"),
        "exchange_rate": ("create", "read", "update", "delete"),
        "tax": ("create", "read", "update", "delete"),
        "payment_term": ("create", "read", "update", "delete"),
        "terms_template": ("create", "read", "update", "delete"),
        "document_sequence": ("create", "read", "update", "delete"),
        "quotation": ("create", "read", "update", "delete", "approve", "send", "revise"),
        "sales_order": (
            "create",
            "read",
            "update",
            "delete",
            "approve",
            "confirm",
            "close",
            "acknowledge",
        ),
        "proforma_invoice": ("create", "read", "update", "delete", "send", "confirm"),
        "purchase_order": ("create", "read", "update", "delete", "approve", "issue", "close"),
        "period": ("lock", "override"),
    },
}


def _permissions_for(module: str) -> tuple[str, ...]:
    return tuple(
        build_permission(module, resource, action)
        for resource, actions in _CATALOG_ACTIONS[module].items()
        for action in actions
    )


IDENTITY_PERMISSIONS: tuple[str, ...] = _permissions_for(IDENTITY_MODULE)
CRM_PERMISSIONS: tuple[str, ...] = _permissions_for(CRM_MODULE)
INVENTORY_PERMISSIONS: tuple[str, ...] = _permissions_for(INVENTORY_MODULE)
ERP_PERMISSIONS: tuple[str, ...] = _permissions_for(ERP_MODULE)
CATALOG_PERMISSIONS: tuple[str, ...] = (
    IDENTITY_PERMISSIONS + CRM_PERMISSIONS + INVENTORY_PERMISSIONS + ERP_PERMISSIONS
)

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
CONTACT_CREATE = build_permission(CRM_MODULE, "contact", "create")
CONTACT_READ = build_permission(CRM_MODULE, "contact", "read")
CONTACT_UPDATE = build_permission(CRM_MODULE, "contact", "update")
CONTACT_DELETE = build_permission(CRM_MODULE, "contact", "delete")

UNIT_CREATE = build_permission(INVENTORY_MODULE, "unit", "create")
UNIT_READ = build_permission(INVENTORY_MODULE, "unit", "read")
UNIT_UPDATE = build_permission(INVENTORY_MODULE, "unit", "update")
UNIT_DELETE = build_permission(INVENTORY_MODULE, "unit", "delete")
CATEGORY_CREATE = build_permission(INVENTORY_MODULE, "category", "create")
CATEGORY_READ = build_permission(INVENTORY_MODULE, "category", "read")
CATEGORY_UPDATE = build_permission(INVENTORY_MODULE, "category", "update")
CATEGORY_DELETE = build_permission(INVENTORY_MODULE, "category", "delete")
PRODUCT_CREATE = build_permission(INVENTORY_MODULE, "product", "create")
PRODUCT_READ = build_permission(INVENTORY_MODULE, "product", "read")
PRODUCT_UPDATE = build_permission(INVENTORY_MODULE, "product", "update")
PRODUCT_DELETE = build_permission(INVENTORY_MODULE, "product", "delete")
PRODUCT_HISTORY = build_permission(INVENTORY_MODULE, "product", "history")
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
GOODS_RECEIPT_CREATE = build_permission(INVENTORY_MODULE, "goods_receipt", "create")
GOODS_RECEIPT_READ = build_permission(INVENTORY_MODULE, "goods_receipt", "read")
GOODS_RECEIPT_UPDATE = build_permission(INVENTORY_MODULE, "goods_receipt", "update")
GOODS_RECEIPT_DELETE = build_permission(INVENTORY_MODULE, "goods_receipt", "delete")
GOODS_RECEIPT_POST = build_permission(INVENTORY_MODULE, "goods_receipt", "post")
QUALITY_INSPECTION_CREATE = build_permission(INVENTORY_MODULE, "quality_inspection", "create")
QUALITY_INSPECTION_READ = build_permission(INVENTORY_MODULE, "quality_inspection", "read")
QUALITY_INSPECTION_UPDATE = build_permission(INVENTORY_MODULE, "quality_inspection", "update")
QUALITY_INSPECTION_APPROVE = build_permission(INVENTORY_MODULE, "quality_inspection", "approve")
DELIVERY_NOTE_CREATE = build_permission(INVENTORY_MODULE, "delivery_note", "create")
DELIVERY_NOTE_READ = build_permission(INVENTORY_MODULE, "delivery_note", "read")
DELIVERY_NOTE_UPDATE = build_permission(INVENTORY_MODULE, "delivery_note", "update")
DELIVERY_NOTE_DELETE = build_permission(INVENTORY_MODULE, "delivery_note", "delete")
DELIVERY_NOTE_POST = build_permission(INVENTORY_MODULE, "delivery_note", "post")
PACKAGE_CREATE = build_permission(INVENTORY_MODULE, "package", "create")
PACKAGE_READ = build_permission(INVENTORY_MODULE, "package", "read")
PACKAGE_UPDATE = build_permission(INVENTORY_MODULE, "package", "update")
PACKAGE_DELETE = build_permission(INVENTORY_MODULE, "package", "delete")
SHIPMENT_CREATE = build_permission(INVENTORY_MODULE, "shipment", "create")
SHIPMENT_READ = build_permission(INVENTORY_MODULE, "shipment", "read")
SHIPMENT_UPDATE = build_permission(INVENTORY_MODULE, "shipment", "update")
SHIPMENT_DELETE = build_permission(INVENTORY_MODULE, "shipment", "delete")
SHIPMENT_DISPATCH = build_permission(INVENTORY_MODULE, "shipment", "dispatch")
SHIPMENT_CLOSE = build_permission(INVENTORY_MODULE, "shipment", "close")
SALES_RETURN_CREATE = build_permission(INVENTORY_MODULE, "sales_return", "create")
SALES_RETURN_READ = build_permission(INVENTORY_MODULE, "sales_return", "read")
SALES_RETURN_UPDATE = build_permission(INVENTORY_MODULE, "sales_return", "update")
SALES_RETURN_DELETE = build_permission(INVENTORY_MODULE, "sales_return", "delete")
SALES_RETURN_POST = build_permission(INVENTORY_MODULE, "sales_return", "post")

SUPPLIER_CREATE = build_permission(ERP_MODULE, "supplier", "create")
SUPPLIER_READ = build_permission(ERP_MODULE, "supplier", "read")
SUPPLIER_UPDATE = build_permission(ERP_MODULE, "supplier", "update")
SUPPLIER_DELETE = build_permission(ERP_MODULE, "supplier", "delete")
SUPPLIER_HISTORY = build_permission(ERP_MODULE, "supplier", "history")
SUPPLIER_PRODUCT_CREATE = build_permission(ERP_MODULE, "supplier_product", "create")
SUPPLIER_PRODUCT_READ = build_permission(ERP_MODULE, "supplier_product", "read")
SUPPLIER_PRODUCT_UPDATE = build_permission(ERP_MODULE, "supplier_product", "update")
SUPPLIER_PRODUCT_DELETE = build_permission(ERP_MODULE, "supplier_product", "delete")
SUPPLIER_PRODUCT_LINK = build_permission(ERP_MODULE, "supplier_product", "link")
CURRENCY_CREATE = build_permission(ERP_MODULE, "currency", "create")
CURRENCY_READ = build_permission(ERP_MODULE, "currency", "read")
CURRENCY_UPDATE = build_permission(ERP_MODULE, "currency", "update")
CURRENCY_DELETE = build_permission(ERP_MODULE, "currency", "delete")
EXCHANGE_RATE_CREATE = build_permission(ERP_MODULE, "exchange_rate", "create")
EXCHANGE_RATE_READ = build_permission(ERP_MODULE, "exchange_rate", "read")
EXCHANGE_RATE_UPDATE = build_permission(ERP_MODULE, "exchange_rate", "update")
EXCHANGE_RATE_DELETE = build_permission(ERP_MODULE, "exchange_rate", "delete")
TAX_CREATE = build_permission(ERP_MODULE, "tax", "create")
TAX_READ = build_permission(ERP_MODULE, "tax", "read")
TAX_UPDATE = build_permission(ERP_MODULE, "tax", "update")
TAX_DELETE = build_permission(ERP_MODULE, "tax", "delete")
PAYMENT_TERM_CREATE = build_permission(ERP_MODULE, "payment_term", "create")
PAYMENT_TERM_READ = build_permission(ERP_MODULE, "payment_term", "read")
PAYMENT_TERM_UPDATE = build_permission(ERP_MODULE, "payment_term", "update")
PAYMENT_TERM_DELETE = build_permission(ERP_MODULE, "payment_term", "delete")
TERMS_TEMPLATE_CREATE = build_permission(ERP_MODULE, "terms_template", "create")
TERMS_TEMPLATE_READ = build_permission(ERP_MODULE, "terms_template", "read")
TERMS_TEMPLATE_UPDATE = build_permission(ERP_MODULE, "terms_template", "update")
TERMS_TEMPLATE_DELETE = build_permission(ERP_MODULE, "terms_template", "delete")
DOCUMENT_SEQUENCE_CREATE = build_permission(ERP_MODULE, "document_sequence", "create")
DOCUMENT_SEQUENCE_READ = build_permission(ERP_MODULE, "document_sequence", "read")
DOCUMENT_SEQUENCE_UPDATE = build_permission(ERP_MODULE, "document_sequence", "update")
DOCUMENT_SEQUENCE_DELETE = build_permission(ERP_MODULE, "document_sequence", "delete")
QUOTATION_CREATE = build_permission(ERP_MODULE, "quotation", "create")
QUOTATION_READ = build_permission(ERP_MODULE, "quotation", "read")
QUOTATION_UPDATE = build_permission(ERP_MODULE, "quotation", "update")
QUOTATION_DELETE = build_permission(ERP_MODULE, "quotation", "delete")
QUOTATION_APPROVE = build_permission(ERP_MODULE, "quotation", "approve")
QUOTATION_SEND = build_permission(ERP_MODULE, "quotation", "send")
QUOTATION_REVISE = build_permission(ERP_MODULE, "quotation", "revise")
SALES_ORDER_CREATE = build_permission(ERP_MODULE, "sales_order", "create")
SALES_ORDER_READ = build_permission(ERP_MODULE, "sales_order", "read")
SALES_ORDER_UPDATE = build_permission(ERP_MODULE, "sales_order", "update")
SALES_ORDER_DELETE = build_permission(ERP_MODULE, "sales_order", "delete")
SALES_ORDER_APPROVE = build_permission(ERP_MODULE, "sales_order", "approve")
SALES_ORDER_CONFIRM = build_permission(ERP_MODULE, "sales_order", "confirm")
SALES_ORDER_CLOSE = build_permission(ERP_MODULE, "sales_order", "close")
SALES_ORDER_ACKNOWLEDGE = build_permission(ERP_MODULE, "sales_order", "acknowledge")
PROFORMA_INVOICE_CREATE = build_permission(ERP_MODULE, "proforma_invoice", "create")
PROFORMA_INVOICE_READ = build_permission(ERP_MODULE, "proforma_invoice", "read")
PROFORMA_INVOICE_UPDATE = build_permission(ERP_MODULE, "proforma_invoice", "update")
PROFORMA_INVOICE_DELETE = build_permission(ERP_MODULE, "proforma_invoice", "delete")
PROFORMA_INVOICE_SEND = build_permission(ERP_MODULE, "proforma_invoice", "send")
PROFORMA_INVOICE_CONFIRM = build_permission(ERP_MODULE, "proforma_invoice", "confirm")
PURCHASE_ORDER_CREATE = build_permission(ERP_MODULE, "purchase_order", "create")
PURCHASE_ORDER_READ = build_permission(ERP_MODULE, "purchase_order", "read")
PURCHASE_ORDER_UPDATE = build_permission(ERP_MODULE, "purchase_order", "update")
PURCHASE_ORDER_DELETE = build_permission(ERP_MODULE, "purchase_order", "delete")
PURCHASE_ORDER_APPROVE = build_permission(ERP_MODULE, "purchase_order", "approve")
PURCHASE_ORDER_ISSUE = build_permission(ERP_MODULE, "purchase_order", "issue")
PURCHASE_ORDER_CLOSE = build_permission(ERP_MODULE, "purchase_order", "close")
PERIOD_LOCK = build_permission(ERP_MODULE, "period", "lock")
PERIOD_OVERRIDE = build_permission(ERP_MODULE, "period", "override")

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
