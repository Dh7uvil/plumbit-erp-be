"""Presence repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.presence.models import UserPresence


class PresenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, user_id: UUID) -> UserPresence | None:
        stmt = select(UserPresence).where(
            UserPresence.tenant_id == tenant_id,
            UserPresence.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> list[UserPresence]:
        if not user_ids:
            return []
        stmt = select(UserPresence).where(
            UserPresence.tenant_id == tenant_id,
            UserPresence.user_id.in_(user_ids),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, tenant_id: UUID, user_id: UUID, values: dict) -> UserPresence:
        row = await self.get(tenant_id, user_id)
        if row is None:
            row = UserPresence(tenant_id=tenant_id, user_id=user_id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await self.session.flush()
        return row
