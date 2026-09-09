"""Transactional outbox enqueue, claim, and terminal-state transitions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.outbox.models import OutboxEvent
from app.common.outbox.repository import OutboxRepository
from app.common.outbox.schemas import OutboxEventResponse, OutboxFilter
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.enums import OutboxStatus
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.middleware import get_request_id

DEFAULT_MAX_ATTEMPTS = 8
BACKOFF_CAP_SECONDS = 1024
_ERROR_MAX_LENGTH = 2000


def next_available_at(
    attempts: int,
    *,
    now: datetime | None = None,
    cap_seconds: int = BACKOFF_CAP_SECONDS,
) -> datetime:
    """Return the next retry instant: ``now + 2**attempts`` seconds, capped."""

    delay = min(2**attempts, cap_seconds)
    return (now or utcnow()) + timedelta(seconds=delay)


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OutboxRepository(session)

    async def enqueue(
        self,
        tenant_id: UUID,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: Mapping[str, object] | None = None,
        dedupe_key: str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> OutboxEvent:
        """Stage an event in the caller's transaction. Does not commit."""

        if dedupe_key:
            existing = await self.repo.get_by_dedupe(tenant_id, event_type, dedupe_key)
            if existing is not None:
                return existing

        now = utcnow()
        request_id = get_request_id()
        row = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            dedupe_key=dedupe_key,
            payload=dict(payload) if payload is not None else None,
            status=OutboxStatus.PENDING.value,
            attempts=0,
            max_attempts=max_attempts,
            available_at=now,
            request_id=request_id[:64] if request_id else None,
        )
        self.session.add(row)
        if dedupe_key is None:
            await self.session.flush()
            return row
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            existing = await self.repo.get_by_dedupe(tenant_id, event_type, dedupe_key)
            if existing is None:
                raise
            return existing
        return row

    async def claim(
        self, *, limit: int, worker_id: str, tenant_id: UUID | None = None
    ) -> list[OutboxEvent]:
        return list(await self.repo.claim(limit=limit, worker_id=worker_id, tenant_id=tenant_id))

    async def succeed(self, event_id: UUID) -> OutboxEvent:
        row = await self._require_by_id(event_id)
        row.status = OutboxStatus.DONE.value
        row.processed_at = utcnow()
        row.locked_at = None
        row.locked_by = None
        row.last_error = None
        await self.session.flush()
        return row

    async def fail(self, event_id: UUID, error: str) -> OutboxEvent:
        row = await self._require_by_id(event_id)
        row.attempts += 1
        row.last_error = error[:_ERROR_MAX_LENGTH]
        row.locked_at = None
        row.locked_by = None
        if row.attempts >= row.max_attempts:
            row.status = OutboxStatus.DEAD.value
        else:
            row.status = OutboxStatus.FAILED.value
            row.available_at = next_available_at(row.attempts)
        await self.session.flush()
        return row

    async def mark_dead(self, event_id: UUID, error: str) -> OutboxEvent:
        row = await self._require_by_id(event_id)
        row.status = OutboxStatus.DEAD.value
        row.last_error = error[:_ERROR_MAX_LENGTH]
        row.locked_at = None
        row.locked_by = None
        await self.session.flush()
        return row

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: OutboxFilter | BaseFilter | None = None,
        status: str | None = None,
        event_type: str | None = None,
        aggregate_type: str | None = None,
        aggregate_id: UUID | None = None,
    ) -> tuple[list[OutboxEventResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if event_type is not None:
            filters["event_type"] = event_type
        if aggregate_type is not None:
            filters["aggregate_type"] = aggregate_type
        if aggregate_id is not None:
            filters["aggregate_id"] = aggregate_id
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        return [OutboxEventResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, event_id: UUID) -> OutboxEventResponse:
        row = await self.repo.get(tenant_id, event_id)
        if row is None:
            raise ResourceNotFoundError("Outbox event not found")
        return OutboxEventResponse.model_validate(row)

    async def retry(self, tenant_id: UUID, event_id: UUID) -> OutboxEventResponse:
        row = await self.repo.get(tenant_id, event_id)
        if row is None:
            raise ResourceNotFoundError("Outbox event not found")
        if row.status not in (OutboxStatus.FAILED.value, OutboxStatus.DEAD.value):
            raise ValidationError(
                "Only failed or dead events can be retried",
                details={"status": row.status},
            )
        reset_attempts = row.status == OutboxStatus.DEAD.value or row.attempts >= row.max_attempts
        row.status = OutboxStatus.PENDING.value
        row.available_at = utcnow()
        row.locked_at = None
        row.locked_by = None
        if reset_attempts:
            row.attempts = 0
        await self.session.flush()
        await self.session.refresh(row, attribute_names=["updated_at"])
        return OutboxEventResponse.model_validate(row)

    async def _require_by_id(self, event_id: UUID) -> OutboxEvent:
        row = await self.repo.get_by_id(event_id)
        if row is None:
            raise ResourceNotFoundError("Outbox event not found")
        return row
