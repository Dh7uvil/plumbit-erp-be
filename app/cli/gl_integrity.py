"""Verify GL integrity: balanced journals and trial balance."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select

from app.auth.models import Tenant
from app.core.enums import TenantStatus
from app.core.logging import configure_logging
from app.db.session import async_session_factory, transaction
from app.erp.accounting.integrity.service import GlIntegrityService
from app.wiring import wire_platform


async def _check_tenant(tenant_id: UUID, *, as_of: date) -> list[str]:
    async with async_session_factory() as session:
        result = await GlIntegrityService(session).scan(tenant_id, as_of=as_of)
    return [issue.message for issue in result.issues]


async def _run(*, as_of: date, tenant_id: str | None) -> int:
    wire_platform()
    async with async_session_factory() as session, transaction(session):
        stmt = select(Tenant.id).where(Tenant.status == TenantStatus.ACTIVE.value)
        if tenant_id is not None:
            stmt = stmt.where(Tenant.id == tenant_id)
        tenant_ids = list(await session.scalars(stmt))

    issue_count = 0
    for tid in tenant_ids:
        issues = await _check_tenant(tid, as_of=as_of)
        if issues:
            print(f"tenant={tid} issues={len(issues)}")
            for item in issues:
                print(f"  {item}")
            issue_count += len(issues)
        else:
            print(f"tenant={tid} ok")
    return issue_count


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check GL integrity for active tenants.")
    parser.add_argument(
        "--as-of",
        default=datetime.now(UTC).date().isoformat(),
        help="Trial balance as-of date (YYYY-MM-DD)",
    )
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant UUID")
    return parser.parse_args()


def main() -> None:
    from app.core.config import get_settings

    args = _parse_args()
    configure_logging(get_settings().log_level)
    as_of = date.fromisoformat(args.as_of)
    try:
        issues = asyncio.run(_run(as_of=as_of, tenant_id=args.tenant_id))
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        raise SystemExit(0) from None
    if issues:
        print(f"Integrity check failed with {issues} issue(s)", file=sys.stderr)
        raise SystemExit(1)
    print("GL integrity check passed")


if __name__ == "__main__":
    main()
