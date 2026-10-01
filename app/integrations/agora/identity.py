"""Stable Agora identity mapping per tenant user."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.extended.models import ChatUserMapping
from app.communication.extended.repository import ChatUserMappingRepository


def format_agora_user_id(tenant_id: UUID, user_id: UUID) -> str:
    return f"t{tenant_id.hex[:8]}_u{user_id.hex[:8]}"


class ChatIdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChatUserMappingRepository(session)

    async def get_or_create_mapping(
        self, tenant_id: UUID, user_id: UUID
    ) -> ChatUserMapping:
        existing = await self.repo.get_by_tenant_user(tenant_id, user_id)
        if existing is not None:
            return existing

        agora_user_id = format_agora_user_id(tenant_id, user_id)
        rtc_uid = await self.repo.next_rtc_uid()
        row = ChatUserMapping(
            tenant_id=tenant_id,
            user_id=user_id,
            agora_user_id=agora_user_id,
            rtc_uid=rtc_uid,
        )
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            existing = await self.repo.get_by_tenant_user(tenant_id, user_id)
            if existing is None:
                raise
            return existing
        return row
