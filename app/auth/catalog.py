"""Canonical identity permission catalog and per-tenant seeding."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Permission
from app.core.permissions import Permission as ParsedPermission
from app.core.permissions import build_permission, parse_permission

IDENTITY_MODULE = "identity"

_IDENTITY_ACTIONS: dict[str, tuple[str, ...]] = {
    "user": ("create", "read", "update", "delete"),
    "role": ("create", "read", "update", "delete"),
    "permission": ("read",),
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
