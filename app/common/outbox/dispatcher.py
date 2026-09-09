"""Outbox poller: claim a batch, then handle each event in its own transaction."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.common.outbox.handlers import get_handler
from app.common.outbox.service import OutboxService
from app.core.enums import OutboxStatus
from app.db.session import async_session_factory, transaction

logger = logging.getLogger(__name__)


async def process_batch(*, batch: int, worker_id: str) -> int:
    """Claim up to ``batch`` events and dispatch each in its own session."""

    async with async_session_factory() as session, transaction(session):
        claimed = await OutboxService(session).claim(limit=batch, worker_id=worker_id)
        event_ids = [row.id for row in claimed]
    for event_id in event_ids:
        await dispatch_one(event_id)
    return len(event_ids)


async def run_forever(*, batch: int, interval: float, worker_id: str) -> None:
    """Claim and dispatch forever. Restart-safe via SKIP LOCKED and stale locks."""

    while True:
        try:
            await process_batch(batch=batch, worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox_batch_failed")
        await asyncio.sleep(interval)


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
