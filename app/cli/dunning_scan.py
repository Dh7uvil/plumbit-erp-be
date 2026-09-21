"""Scan open invoices and enqueue payment reminders."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.auth.models import Tenant
from app.core.enums import TenantStatus
from app.core.logging import configure_logging
from app.db.session import async_session_factory, transaction
from app.erp.accounting.dunning.service import DunningService
from app.wiring import wire_platform


async def _scan(*, as_of: date, tenant_id: str | None) -> int:
    wire_platform()
    total = 0
    async with async_session_factory() as session, transaction(session):
        stmt = select(Tenant.id).where(Tenant.status == TenantStatus.ACTIVE.value)
        if tenant_id is not None:
            stmt = stmt.where(Tenant.id == tenant_id)
        tenant_ids = list(await session.scalars(stmt))
    for tid in tenant_ids:
        async with async_session_factory() as session, transaction(session):
            sent = await DunningService(session).scan_tenant(tid, as_of=as_of)
            total += sent
            print(f"tenant={tid} reminders={sent}")
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enqueue dunning reminders for open invoices.")
    parser.add_argument(
        "--as-of",
        default=datetime.now(UTC).date().isoformat(),
        help="Calendar date to evaluate rules against (YYYY-MM-DD)",
    )
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant UUID")
    return parser.parse_args()


def main() -> None:
    from app.core.config import get_settings

    args = _parse_args()
    configure_logging(get_settings().log_level)
    as_of = date.fromisoformat(args.as_of)
    try:
        total = asyncio.run(_scan(as_of=as_of, tenant_id=args.tenant_id))
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        raise SystemExit(0) from None
    print(f"Total reminders queued: {total}")


if __name__ == "__main__":
    main()
