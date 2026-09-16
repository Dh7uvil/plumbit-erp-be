"""User notification preference use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notification_preferences.repository import UserNotificationPreferenceRepository
from app.common.notification_preferences.schemas import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)
from app.db.session import transaction

DEFAULT_EMAIL_ENABLED = True
DEFAULT_IN_APP_ENABLED = True
DEFAULT_WHATSAPP_ENABLED = False


def default_preferences() -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        email_enabled=DEFAULT_EMAIL_ENABLED,
        in_app_enabled=DEFAULT_IN_APP_ENABLED,
        whatsapp_enabled=DEFAULT_WHATSAPP_ENABLED,
        is_default=True,
    )


class NotificationPreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserNotificationPreferenceRepository(session)

    async def get(self, tenant_id: UUID, user_id: UUID) -> NotificationPreferenceResponse:
        row = await self.repo.get(tenant_id, user_id)
        if row is None:
            return default_preferences()
        return NotificationPreferenceResponse(
            email_enabled=row.email_enabled,
            in_app_enabled=row.in_app_enabled,
            whatsapp_enabled=row.whatsapp_enabled,
            is_default=False,
        )

    async def upsert(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: NotificationPreferenceUpdate,
    ) -> NotificationPreferenceResponse:
        current = await self.get(tenant_id, user_id)
        values = payload.model_dump(exclude_unset=True)
        email_enabled = values.get("email_enabled", current.email_enabled)
        in_app_enabled = values.get("in_app_enabled", current.in_app_enabled)
        whatsapp_enabled = values.get("whatsapp_enabled", current.whatsapp_enabled)
        try:
            async with transaction(self.session):
                await self.repo.upsert(
                    tenant_id,
                    user_id,
                    email_enabled=email_enabled,
                    in_app_enabled=in_app_enabled,
                    whatsapp_enabled=whatsapp_enabled,
                )
        except IntegrityError:
            async with transaction(self.session):
                await self.repo.upsert(
                    tenant_id,
                    user_id,
                    email_enabled=email_enabled,
                    in_app_enabled=in_app_enabled,
                    whatsapp_enabled=whatsapp_enabled,
                )
        return NotificationPreferenceResponse(
            email_enabled=email_enabled,
            in_app_enabled=in_app_enabled,
            whatsapp_enabled=whatsapp_enabled,
            is_default=False,
        )
