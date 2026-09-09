"""CLI to insert missing permission catalog rows on existing tenants.

New catalog entries (for example ``inventory.goods_receipt.post``) exist in code
before they exist in ``permissions``. This command inserts those rows only. It
does not grant them to any role — use ``grant-superadmin-permissions`` when
Superadmin should inherit the full catalog.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import parsed_catalog_permissions, seed_tenant_permissions
from app.auth.models import Permission, Tenant
from app.core.enums import TenantStatus
from app.db.session import async_session_factory, transaction


@dataclass(frozen=True, slots=True)
class PermissionSeedResult:
    tenant_id: UUID
    code: str
    inserted: int
    catalog_permissions: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Insert missing permission catalog rows on existing tenants. "
            "Idempotent: rows that already exist are left in place. Role grants "
            "are not changed."
        )
    )
    parser.add_argument(
        "--tenant-id",
        type=UUID,
        default=None,
        help="Seed only this tenant UUID (default: every active tenant)",
    )
    parser.add_argument(
        "--tenant-code",
        default=None,
        help="Seed only this tenant code (default: every active tenant)",
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


async def _existing_catalog_keys(
    session: AsyncSession, tenant_id: UUID
) -> set[tuple[str, str, str]]:
    result = await session.execute(
        select(Permission.module, Permission.resource, Permission.action).where(
            Permission.tenant_id == tenant_id
        )
    )
    return {(row.module, row.resource, row.action) for row in result.all()}


async def seed_catalog_permissions(
    *,
    tenant_id: UUID | None = None,
    tenant_code: str | None = None,
) -> list[PermissionSeedResult]:
    """Insert missing catalog permission rows on matching active tenants."""

    tenants = await _load_tenants(tenant_id=tenant_id, tenant_code=tenant_code)
    if (tenant_id is not None or tenant_code is not None) and not tenants:
        raise ValueError("No active tenant matched the given filter")

    catalog_keys = {
        (parsed.module, parsed.resource, parsed.action) for parsed in parsed_catalog_permissions()
    }
    results: list[PermissionSeedResult] = []
    for target_id, code in tenants:
        async with async_session_factory() as session, transaction(session):
            existing = await _existing_catalog_keys(session, target_id)
            missing = catalog_keys - existing
            await seed_tenant_permissions(session, target_id)
        results.append(
            PermissionSeedResult(
                tenant_id=target_id,
                code=code,
                inserted=len(missing),
                catalog_permissions=len(catalog_keys),
            )
        )
    return results


def _print_summary(results: list[PermissionSeedResult]) -> None:
    if not results:
        print("No active tenants to seed")
        return
    inserted_total = sum(row.inserted for row in results)
    print(
        f"Seeded permission catalog on {len(results)} tenant(s)  "
        f"inserted={inserted_total}"
    )
    for row in results:
        print(
            f"  {row.code}  {row.tenant_id}  "
            f"inserted={row.inserted}  catalog={row.catalog_permissions}"
        )


def main() -> None:
    args = _parse_args()
    try:
        results = asyncio.run(
            seed_catalog_permissions(tenant_id=args.tenant_id, tenant_code=args.tenant_code)
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
