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
        "attachment": ("create", "read", "delete"),
    },
    CRM_MODULE: {
        "customer": ("create", "read", "update", "delete"),
        "contact": ("create", "read", "update", "delete"),
    },
    INVENTORY_MODULE: {
        "unit": ("create", "read", "update", "delete"),
        "category": ("create", "read", "update", "delete"),
        "product": ("create", "read", "update", "delete"),
        "price_list": ("create", "read", "update", "delete"),
        "warehouse": ("create", "read", "update", "delete"),
    },
    ERP_MODULE: {
        "supplier": ("create", "read", "update", "delete"),
        "currency": ("create", "read", "update", "delete"),
        "exchange_rate": ("create", "read", "update", "delete"),
        "tax": ("create", "read", "update", "delete"),
        "payment_term": ("create", "read", "update", "delete"),
        "terms_template": ("create", "read", "update", "delete"),
        "document_sequence": ("create", "read", "update", "delete"),
        "quotation": ("create", "read", "update", "delete", "approve", "send"),
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
ATTACHMENT_DELETE = build_permission(IDENTITY_MODULE, "attachment", "delete")

CUSTOMER_CREATE = build_permission(CRM_MODULE, "customer", "create")
CUSTOMER_READ = build_permission(CRM_MODULE, "customer", "read")
CUSTOMER_UPDATE = build_permission(CRM_MODULE, "customer", "update")
CUSTOMER_DELETE = build_permission(CRM_MODULE, "customer", "delete")
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
PRICE_LIST_CREATE = build_permission(INVENTORY_MODULE, "price_list", "create")
PRICE_LIST_READ = build_permission(INVENTORY_MODULE, "price_list", "read")
PRICE_LIST_UPDATE = build_permission(INVENTORY_MODULE, "price_list", "update")
PRICE_LIST_DELETE = build_permission(INVENTORY_MODULE, "price_list", "delete")
WAREHOUSE_CREATE = build_permission(INVENTORY_MODULE, "warehouse", "create")
WAREHOUSE_READ = build_permission(INVENTORY_MODULE, "warehouse", "read")
WAREHOUSE_UPDATE = build_permission(INVENTORY_MODULE, "warehouse", "update")
WAREHOUSE_DELETE = build_permission(INVENTORY_MODULE, "warehouse", "delete")

SUPPLIER_CREATE = build_permission(ERP_MODULE, "supplier", "create")
SUPPLIER_READ = build_permission(ERP_MODULE, "supplier", "read")
SUPPLIER_UPDATE = build_permission(ERP_MODULE, "supplier", "update")
SUPPLIER_DELETE = build_permission(ERP_MODULE, "supplier", "delete")
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
