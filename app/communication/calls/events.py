"""Call event persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.extended.models import CallEvent
from app.core.enums import CallEventSource, CallEventType


class CallEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists_by_notice_id(self, tenant_id: UUID, notice_id: str) -> bool:
        stmt = select(CallEvent.id).where(
            CallEvent.tenant_id == tenant_id,
            CallEvent.payload.op("->>")("noticeId") == notice_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        tenant_id: UUID,
        *,
        call_id: UUID,
        event_type: str,
        user_id: UUID | None = None,
        payload: dict | None = None,
        source: str = CallEventSource.API.value,
    ) -> CallEvent:
        row = CallEvent(
            tenant_id=tenant_id,
            call_id=call_id,
            user_id=user_id,
            type=event_type,
            payload=payload,
            source=source,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class CallEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CallEventRepository(session)

    async def record(
        self,
        tenant_id: UUID,
        call_id: UUID,
        event_type: CallEventType | str,
        *,
        user_id: UUID | None = None,
        payload: dict | None = None,
        source: CallEventSource | str = CallEventSource.API,
    ) -> CallEvent:
        return await self.repo.create(
            tenant_id,
            call_id=call_id,
            event_type=str(event_type),
            user_id=user_id,
            payload=payload,
            source=str(source),
        )

    async def record_webhook(
        self,
        tenant_id: UUID,
        call_id: UUID,
        event_type: CallEventType | str,
        *,
        notice_id: str,
        user_id: UUID | None = None,
        payload: dict | None = None,
    ) -> CallEvent | None:
        if await self.repo.exists_by_notice_id(tenant_id, notice_id):
            return None
        merged = dict(payload or {})
        merged["noticeId"] = notice_id
        return await self.repo.create(
            tenant_id,
            call_id=call_id,
            event_type=str(event_type),
            user_id=user_id,
            payload=merged,
            source=CallEventSource.WEBHOOK.value,
        )
