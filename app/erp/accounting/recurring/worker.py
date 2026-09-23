"""Scan due recurring templates and enqueue draft generation."""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from app.common.outbox.service import OutboxService
from app.db.session import async_session_factory, transaction
from app.erp.accounting.recurring.repository import RecurringRepository

logger = logging.getLogger(__name__)

RECURRING_GENERATE_EVENT = "accounting.recurring.generate"


async def enqueue_due_recurring(*, today: date | None = None) -> int:
    """Enqueue one outbox event per due template. The handler creates the draft."""

    as_of = today or date.today()
    async with async_session_factory() as session, transaction(session):
        due = await RecurringRepository(session).due_templates(as_of)
        outbox = OutboxService(session)
        queued = 0
        for row in due:
            if row.created_by is None:
                logger.warning(
                    "recurring_template_missing_actor",
                    extra={"template_id": str(row.id), "tenant_id": str(row.tenant_id)},
                )
                continue
            await outbox.enqueue(
                row.tenant_id,
                event_type=RECURRING_GENERATE_EVENT,
                aggregate_type="recurring_template",
                aggregate_id=row.id,
                payload={
                    "template_id": str(row.id),
                    "actor_user_id": str(row.created_by),
                    "run_date": row.next_run_date.isoformat(),
                },
                dedupe_key=f"recurring:{row.id}:{row.next_run_date.isoformat()}",
            )
            queued += 1
        return queued


async def handle_recurring_generate(event: object) -> None:
    """Outbox handler. Generates a draft and never posts it."""

    from app.common.outbox.models import OutboxEvent
    from app.erp.accounting.recurring.service import RecurringService

    if not isinstance(event, OutboxEvent):
        return
    payload = event.payload or {}
    template_raw = payload.get("template_id")
    actor_raw = payload.get("actor_user_id")
    if not isinstance(template_raw, str) or not isinstance(actor_raw, str):
        raise ValueError("Invalid recurring generation payload")
    async with async_session_factory() as session:
        await RecurringService(session).materialize(
            event.tenant_id,
            UUID(template_raw),
            actor_user_id=UUID(actor_raw),
            force=False,
        )
