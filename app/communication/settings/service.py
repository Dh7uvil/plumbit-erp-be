"""Chat notification settings use cases."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.settings.repository import ChatNotificationSettingsRepository
from app.communication.settings.schemas import (
    ChatNotificationSettingsResponse,
    ChatNotificationSettingsUpdate,
)
from app.communication.shared.feature import require_communication_enabled
from app.db.session import transaction


class ChatNotificationSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChatNotificationSettingsRepository(session)

    async def get(
        self, tenant_id: UUID, user_id: UUID
    ) -> ChatNotificationSettingsResponse:
        require_communication_enabled()
        async with transaction(self.session):
            row = await self.repo.get_or_create(tenant_id, user_id)
        return ChatNotificationSettingsResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: ChatNotificationSettingsUpdate,
    ) -> ChatNotificationSettingsResponse:
        require_communication_enabled()
        async with transaction(self.session):
            row = await self.repo.get_or_create(tenant_id, user_id)
            values = payload.model_dump(exclude_unset=True)
            if values:
                row = await self.repo.update(row, values)
        return ChatNotificationSettingsResponse.model_validate(row)
