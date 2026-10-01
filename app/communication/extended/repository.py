"""Extended communication repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.extended.models import ChatUserMapping


class ChatUserMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tenant_user(
        self, tenant_id: UUID, user_id: UUID
    ) -> ChatUserMapping | None:
        stmt = select(ChatUserMapping).where(
            ChatUserMapping.tenant_id == tenant_id,
            ChatUserMapping.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID,
        agora_user_id: str,
        rtc_uid: int,
    ) -> ChatUserMapping:
        row = ChatUserMapping(
            tenant_id=tenant_id,
            user_id=user_id,
            agora_user_id=agora_user_id,
            rtc_uid=rtc_uid,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def next_rtc_uid(self) -> int:
        result = await self.session.execute(text("SELECT nextval('chat_rtc_uid_seq')"))
        return int(result.scalar_one())
