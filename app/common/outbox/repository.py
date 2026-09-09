"""Outbox event queries. Not a BaseRepository: rows are not soft-deleted."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.outbox.models import OutboxEvent
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.enums import OutboxStatus

_STALE_LOCK = timedelta(minutes=5)
_ALLOWED_SORT = frozenset({"created_at", "available_at", "status", "event_type"})
_ALLOWED_FILTER = frozenset({"status", "event_type", "aggregate_type", "aggregate_id"})


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, event_id: UUID) -> OutboxEvent | None:
        result = await self.session.execute(
            select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        result = await self.session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))
        return result.scalar_one_or_none()

    async def get_by_dedupe(
        self, tenant_id: UUID, event_type: str, dedupe_key: str
    ) -> OutboxEvent | None:
        result = await self.session.execute(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.event_type == event_type,
                OutboxEvent.dedupe_key == dedupe_key,
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[OutboxEvent], int]:
        criteria = self._criteria(tenant_id, common_filter=common_filter, filters=filters)
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in _ALLOWED_SORT:
            msg = f"sort field is not allowed: {sort_by}"
            raise ValueError(msg)
        sort_column = getattr(OutboxEvent, sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        statement: Select[tuple[OutboxEvent]] = (
            select(OutboxEvent)
            .where(*criteria)
            .order_by(ordering)
            .offset(page.offset)
            .limit(page.page_size)
        )
        count_statement = select(func.count()).select_from(OutboxEvent).where(*criteria)
        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def claim(
        self, *, limit: int, worker_id: str, tenant_id: UUID | None = None
    ) -> Sequence[OutboxEvent]:
        now = utcnow()
        stale_before = now - _STALE_LOCK
        claimable = or_(
            and_(
                OutboxEvent.status.in_((OutboxStatus.PENDING.value, OutboxStatus.FAILED.value)),
                OutboxEvent.available_at <= now,
            ),
            and_(
                OutboxEvent.status == OutboxStatus.PROCESSING.value,
                OutboxEvent.locked_at.is_not(None),
                OutboxEvent.locked_at < stale_before,
            ),
        )
        criteria = [claimable]
        if tenant_id is not None:
            criteria.append(OutboxEvent.tenant_id == tenant_id)
        statement = (
            select(OutboxEvent)
            .where(*criteria)
            .order_by(OutboxEvent.available_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        rows = list(result.scalars().all())
        locked_by = worker_id[:80]
        for row in rows:
            row.status = OutboxStatus.PROCESSING.value
            row.locked_at = now
            row.locked_by = locked_by
        await self.session.flush()
        return rows

    def _criteria(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> Sequence[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [OutboxEvent.tenant_id == tenant_id]
        if filters:
            unknown = filters.keys() - _ALLOWED_FILTER
            if unknown:
                fields = ", ".join(sorted(unknown))
                msg = f"filter fields are not allowed: {fields}"
                raise ValueError(msg)
            for name, value in filters.items():
                criteria.append(getattr(OutboxEvent, name) == value)
        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(OutboxEvent.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(OutboxEvent.created_at <= common_filter.date_to)
        return criteria
