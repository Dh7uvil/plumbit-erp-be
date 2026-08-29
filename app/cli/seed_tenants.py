"""CLI to backfill common catalog data on existing tenants."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.auth.models import Tenant
from app.core.enums import TenantStatus
from app.db.seeds.common import seed_common_data
from app.db.session import async_session_factory, transaction


@dataclass(frozen=True, slots=True)
class TenantSeedResult:
    tenant_id: UUID
    code: str
    currencies_inserted: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill common catalog data (ISO 4217 currencies, AED default) onto "
            "existing tenants. Idempotent: already-present codes are skipped."
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


async def seed_existing_tenants(
    *,
    tenant_id: UUID | None = None,
    tenant_code: str | None = None,
) -> list[TenantSeedResult]:
    """Apply ``seed_common_data`` to matching active tenants."""

    tenants = await _load_tenants(tenant_id=tenant_id, tenant_code=tenant_code)
    if (tenant_id is not None or tenant_code is not None) and not tenants:
        raise ValueError("No active tenant matched the given filter")

    results: list[TenantSeedResult] = []
    for target_id, code in tenants:
        async with async_session_factory() as session, transaction(session):
            inserted = await seed_common_data(session, target_id)
        results.append(
            TenantSeedResult(
                tenant_id=target_id,
                code=code,
                currencies_inserted=inserted,
            )
        )
    return results


def _print_summary(results: list[TenantSeedResult]) -> None:
    if not results:
        print("No active tenants to seed")
        return
    print(f"Seeded common data for {len(results)} tenant(s)")
    for row in results:
        print(f"  {row.code}  {row.tenant_id}  currencies_inserted={row.currencies_inserted}")


def main() -> None:
    args = _parse_args()
    try:
        results = asyncio.run(
            seed_existing_tenants(tenant_id=args.tenant_id, tenant_code=args.tenant_code)
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
