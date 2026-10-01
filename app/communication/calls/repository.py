"""Call repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.communication.calls.models import Call, CallParticipant
from app.core.enums import CallParticipantStatus, CallStatus


class CallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, call_id: UUID) -> Call | None:
        stmt = select(Call).where(Call.tenant_id == tenant_id, Call.id == call_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(self, tenant_id: UUID, call_id: UUID) -> Call | None:
        stmt = (
            select(Call)
            .where(Call.tenant_id == tenant_id, Call.id == call_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_channel_name(self, channel_name: str) -> Call | None:
        stmt = select(Call).where(Call.channel_name == channel_name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def users_in_active_calls(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> set[UUID]:
        if not user_ids:
            return set()
        stmt = (
            select(CallParticipant.user_id)
            .join(
                Call,
                (Call.id == CallParticipant.call_id)
                & (Call.tenant_id == CallParticipant.tenant_id),
            )
            .where(
                Call.tenant_id == tenant_id,
                Call.status.in_(
                    (CallStatus.ACTIVE.value, CallStatus.RINGING.value)
                ),
                CallParticipant.status == CallParticipantStatus.JOINED.value,
                CallParticipant.user_id.in_(user_ids),
            )
            .distinct()
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def create(self, tenant_id: UUID, values: dict) -> Call:
        row = Call(tenant_id=tenant_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, tenant_id: UUID, call_id: UUID, values: dict) -> Call | None:
        row = await self.get(tenant_id, call_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        conversation_id: UUID | None = None,
        participant_user_id: UUID | None = None,
    ) -> tuple[list[Call], int]:
        stmt = select(Call).where(Call.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Call.status == status)
        if conversation_id:
            stmt = stmt.where(Call.conversation_id == conversation_id)
        if participant_user_id is not None:
            stmt = stmt.join(
                CallParticipant,
                (CallParticipant.call_id == Call.id)
                & (CallParticipant.tenant_id == Call.tenant_id),
            ).where(CallParticipant.user_id == participant_user_id)
        count = int((await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        order = Call.started_at.desc()
        stmt = stmt.order_by(order).offset(page.offset).limit(page.page_size)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, count


class CallParticipantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_call(
        self, tenant_id: UUID, call_id: UUID
    ) -> list[CallParticipant]:
        stmt = select(CallParticipant).where(
            CallParticipant.tenant_id == tenant_id,
            CallParticipant.call_id == call_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(
        self, tenant_id: UUID, call_id: UUID, user_id: UUID
    ) -> CallParticipant | None:
        stmt = select(CallParticipant).where(
            CallParticipant.tenant_id == tenant_id,
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_rtc_uid(
        self, tenant_id: UUID, call_id: UUID, rtc_uid: int
    ) -> CallParticipant | None:
        stmt = select(CallParticipant).where(
            CallParticipant.tenant_id == tenant_id,
            CallParticipant.call_id == call_id,
            CallParticipant.rtc_uid == rtc_uid,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, row: CallParticipant) -> CallParticipant:
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, row: CallParticipant, values: dict) -> CallParticipant:
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def next_rtc_uid(self, tenant_id: UUID, call_id: UUID) -> int:
        participants = await self.list_for_call(tenant_id, call_id)
        if not participants:
            return 1
        return max(p.rtc_uid for p in participants) + 1
