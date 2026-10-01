"""Chat notification settings repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.extended.models import ChatNotificationSettings


class ChatNotificationSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, user_id: UUID) -> ChatNotificationSettings | None:
        stmt = select(ChatNotificationSettings).where(
            ChatNotificationSettings.tenant_id == tenant_id,
            ChatNotificationSettings.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self, tenant_id: UUID, user_id: UUID
    ) -> ChatNotificationSettings:
        row = await self.get(tenant_id, user_id)
        if row is not None:
            return row
        row = ChatNotificationSettings(tenant_id=tenant_id, user_id=user_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self, row: ChatNotificationSettings, values: dict[str, object]
    ) -> ChatNotificationSettings:
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row
