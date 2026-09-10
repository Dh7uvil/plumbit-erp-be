"""Outbox poller: claim a batch, then handle each event in its own transaction."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.common.outbox.handlers import get_handler
from app.common.outbox.service import OutboxService
from app.core.enums import OutboxStatus
from app.db.session import async_session_factory, transaction

logger = logging.getLogger(__name__)

_wake = asyncio.Event()
OUTBOX_ENQUEUED_INFO_KEY = "outbox_enqueued"


def wake_poller() -> None:
    """Nudge the in-process poller. Safe to call from after_commit."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _wake.set()
        return
    loop.call_soon_threadsafe(_wake.set)


@event.listens_for(Session, "after_commit")
def _wake_poller_after_commit(session: Session) -> None:
    if session.info.pop(OUTBOX_ENQUEUED_INFO_KEY, False):
        wake_poller()


async def process_batch(*, batch: int, worker_id: str) -> int:
    """Claim up to ``batch`` events and dispatch each in its own session."""

    async with async_session_factory() as session, transaction(session):
        claimed = await OutboxService(session).claim(limit=batch, worker_id=worker_id)
        event_ids = [row.id for row in claimed]
    for event_id in event_ids:
        await dispatch_one(event_id)
    return len(event_ids)


async def run_forever(*, batch: int, interval: float, worker_id: str) -> None:
    """Claim and dispatch forever. Restart-safe via SKIP LOCKED and stale locks.

    After-commit sets ``_wake`` so a pending event is claimed without waiting
    out ``interval``. The poller is still the source of truth: if the nudge is
    missed, the next interval tick picks the row up.
    """

    while True:
        try:
            await process_batch(batch=batch, worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox_batch_failed")
        _wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_wake.wait(), timeout=interval)


async def dispatch_one(event_id: UUID) -> None:
    """Handle a claimed event. Unknown types go to DEAD, never DONE."""

    async with async_session_factory() as session, transaction(session):
        service = OutboxService(session)
        row = await service.repo.get_by_id(event_id)
        if row is None:
            return
        if row.status != OutboxStatus.PROCESSING.value:
            return
        handler = get_handler(row.event_type)
        if handler is None:
            logger.error(
                "unknown_outbox_event_type",
                extra={
                    "event_id": str(row.id),
                    "event_type": row.event_type,
                    "tenant_id": str(row.tenant_id),
                },
            )
            await service.mark_dead(row.id, error=f"Unknown event_type: {row.event_type}")
            return
        try:
            await handler(row)
        except Exception as exc:
            logger.exception(
                "outbox_handler_failed",
                extra={
                    "event_id": str(row.id),
                    "event_type": row.event_type,
                    "tenant_id": str(row.tenant_id),
                },
            )
            await service.fail(row.id, error=str(exc))
            return
        await service.succeed(row.id)
