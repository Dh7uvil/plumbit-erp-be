"""Canonical identity permission catalog and per-tenant seeding."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Permission, Role, RolePermission
from app.core.permissions import Permission as ParsedPermission
from app.core.permissions import build_permission, parse_permission

IDENTITY_MODULE = "identity"

_IDENTITY_ACTIONS: dict[str, tuple[str, ...]] = {
    "user": ("create", "read", "update", "delete"),
    "role": ("create", "read", "update", "delete"),
    "permission": ("read",),
    "organization": ("read", "update"),
    "department": ("create", "read", "update", "delete"),
    "branch": ("create", "read", "update", "delete"),
    "employee": ("create", "read", "update", "delete"),
    "audit_log": ("read",),
}

IDENTITY_PERMISSIONS: tuple[str, ...] = tuple(
    build_permission(IDENTITY_MODULE, resource, action)
    for resource, actions in _IDENTITY_ACTIONS.items()
    for action in actions
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

SYSTEM_ADMIN_ROLE_NAME = "Admin"


def parsed_identity_permissions() -> tuple[ParsedPermission, ...]:
    """Return the catalog as parsed permission values."""

    return tuple(parse_permission(value) for value in IDENTITY_PERMISSIONS)


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
    for parsed in parsed_identity_permissions():
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
    """Return the tenant's system Admin role, if it exists."""

    result = await session.execute(
        select(Role).where(
            Role.tenant_id == tenant_id,
            Role.name == SYSTEM_ADMIN_ROLE_NAME,
            Role.is_system_role.is_(True),
        )
    )
    return result.scalar_one_or_none()
