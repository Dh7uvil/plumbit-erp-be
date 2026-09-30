"""Scan uncleared cheques due on or before a date and enqueue notifications."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.auth.models import Tenant
from app.common.outbox.service import OutboxService
from app.core.enums import ChequeStatus, TenantStatus
from app.core.logging import configure_logging
from app.db.session import async_session_factory, transaction
from app.erp.accounting.cheques.models import Cheque
from app.wiring import wire_platform

_UNCLEARED = frozenset({ChequeStatus.ISSUED.value, ChequeStatus.DEPOSITED.value})


async def _scan(*, as_of: date, tenant_id: str | None, lookahead_days: int) -> int:
    wire_platform()
    total = 0
    async with async_session_factory() as session, transaction(session):
        stmt = select(Tenant.id).where(Tenant.status == TenantStatus.ACTIVE.value)
        if tenant_id is not None:
            stmt = stmt.where(Tenant.id == tenant_id)
        tenant_ids = list(await session.scalars(stmt))
    for tid in tenant_ids:
        async with async_session_factory() as session, transaction(session):
            due_or_cheque = func.coalesce(Cheque.due_date, Cheque.cheque_date)
            rows = (
                await session.execute(
                    select(Cheque)
                    .where(
                        Cheque.tenant_id == tid,
                        Cheque.deleted_at.is_(None),
                        Cheque.status.in_(tuple(_UNCLEARED)),
                        due_or_cheque <= as_of + timedelta(days=lookahead_days),
                        due_or_cheque >= as_of,
                    )
                    .order_by(due_or_cheque.asc())
                )
            ).scalars().all()
            outbox = OutboxService(session)
            enqueued = 0
            for cheque in rows:
                due = cheque.due_date or cheque.cheque_date
                if cheque.created_by is None:
                    continue
                await outbox.enqueue(
                    tid,
                    event_type="cheque.due",
                    aggregate_type="cheque",
                    aggregate_id=cheque.id,
                    payload={
                        "cheque_id": str(cheque.id),
                        "user_id": str(cheque.created_by),
                        "cheque_number": cheque.cheque_number,
                        "direction": cheque.direction,
                        "amount": str(cheque.amount),
                        "due_date": due.isoformat(),
                    },
                    dedupe_key=f"cheque-due:{cheque.id}:{due.isoformat()}",
                )
                enqueued += 1
            total += enqueued
            print(f"tenant={tid} due_cheques={len(rows)} enqueued={enqueued}")
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enqueue cheque.due notifications for cheques due within a window."
    )
    parser.add_argument(
        "--as-of",
        default=datetime.now(UTC).date().isoformat(),
        help="Start of due-date window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=7,
        help="Include cheques due within this many days after --as-of",
    )
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant UUID")
    return parser.parse_args()


def main() -> None:
    from app.core.config import get_settings

    args = _parse_args()
    configure_logging(get_settings().log_level)
    as_of = date.fromisoformat(args.as_of)
    try:
        total = asyncio.run(
            _scan(as_of=as_of, tenant_id=args.tenant_id, lookahead_days=args.lookahead_days)
        )
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        raise SystemExit(0) from None
    print(f"Total cheque.due events queued: {total}")


if __name__ == "__main__":
    main()
