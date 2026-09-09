"""CLI to grant the full permission catalog to every Superadmin role.

Permissions are assigned to roles, not users. Superadmin users inherit the
catalog through the system role named ``Superadmin``. This command seeds any
missing catalog rows and additively grants them to that role on each matching
tenant — the same path used at tenant create and on login.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import get_system_admin_role, grant_catalog_to_role
from app.auth.models import Tenant, UserRole
from app.core.enums import TenantStatus
from app.db.session import async_session_factory, transaction


@dataclass(frozen=True, slots=True)
class SuperadminGrantResult:
    tenant_id: UUID
    code: str
    skipped: bool
    catalog_permissions: int
    superadmin_users: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed the permission catalog and grant every catalog permission to the "
            "Superadmin system role on existing tenants. Superadmin users inherit "
            "those grants. Idempotent: existing role-permission rows are left in place."
        )
    )
    parser.add_argument(
        "--tenant-id",
        type=UUID,
        default=None,
        help="Grant only this tenant UUID (default: every active tenant)",
    )
    parser.add_argument(
        "--tenant-code",
        default=None,
        help="Grant only this tenant code (default: every active tenant)",
    )
    return parser.parse_args()


async def _load_tenants(
    *,
    tenant_id: UUID | None,
    tenant_code: str | None,
) -> list[tuple[UUID, str]]:
    statement = (
        select(Tenant.id, Tenant.code)
        .where(Tenant.status == TenantStatus.ACTIVE)
        .order_by(Tenant.created_at.asc())
    )
    if tenant_id is not None:
        statement = statement.where(Tenant.id == tenant_id)
    if tenant_code is not None:
        statement = statement.where(Tenant.code == tenant_code)

    async with async_session_factory() as session:
        result = await session.execute(statement)
        return [(row.id, row.code) for row in result.all()]


async def _count_superadmin_users(session: AsyncSession, *, tenant_id: UUID, role_id: UUID) -> int:
    counted = await session.scalar(
        select(func.count())
        .select_from(UserRole)
        .where(
            UserRole.tenant_id == tenant_id,
            UserRole.role_id == role_id,
        )
    )
    return int(counted or 0)


async def grant_superadmin_permissions(
    *,
    tenant_id: UUID | None = None,
    tenant_code: str | None = None,
) -> list[SuperadminGrantResult]:
    """Seed the catalog and grant it to Superadmin on matching active tenants."""

    tenants = await _load_tenants(tenant_id=tenant_id, tenant_code=tenant_code)
    if (tenant_id is not None or tenant_code is not None) and not tenants:
        raise ValueError("No active tenant matched the given filter")

    results: list[SuperadminGrantResult] = []
    for target_id, code in tenants:
        async with async_session_factory() as session, transaction(session):
            admin = await get_system_admin_role(session, target_id)
            if admin is None:
                results.append(
                    SuperadminGrantResult(
                        tenant_id=target_id,
                        code=code,
                        skipped=True,
                        catalog_permissions=0,
                        superadmin_users=0,
                    )
                )
                continue
            permissions = await grant_catalog_to_role(session, target_id, admin.id)
            users = await _count_superadmin_users(session, tenant_id=target_id, role_id=admin.id)
        results.append(
            SuperadminGrantResult(
                tenant_id=target_id,
                code=code,
                skipped=False,
                catalog_permissions=len(permissions),
                superadmin_users=users,
            )
        )
    return results


def _print_summary(results: list[SuperadminGrantResult]) -> None:
    granted = [row for row in results if not row.skipped]
    skipped = [row for row in results if row.skipped]
    if not results:
        print("No active tenants to grant")
        return
    if granted:
        print(f"Granted catalog to Superadmin on {len(granted)} tenant(s)")
        for row in granted:
            print(
                f"  {row.code}  {row.tenant_id}  "
                f"users={row.superadmin_users}  permissions={row.catalog_permissions}"
            )
    if skipped:
        print(f"Skipped {len(skipped)} tenant(s) with no Superadmin role")
        for row in skipped:
            print(f"  {row.code}  {row.tenant_id}")


def main() -> None:
    args = _parse_args()
    try:
        results = asyncio.run(
            grant_superadmin_permissions(tenant_id=args.tenant_id, tenant_code=args.tenant_code)
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        raise SystemExit(1) from None

    _print_summary(results)


if __name__ == "__main__":
    main()
