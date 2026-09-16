"""Persistence for user notification preferences."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notification_preferences.models import UserNotificationPreference


class UserNotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, user_id: UUID) -> UserNotificationPreference | None:
        result = await self.session.execute(
            select(UserNotificationPreference).where(
                UserNotificationPreference.tenant_id == tenant_id,
                UserNotificationPreference.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        email_enabled: bool,
        in_app_enabled: bool,
        whatsapp_enabled: bool,
    ) -> UserNotificationPreference:
        row = await self.get(tenant_id, user_id)
        if row is None:
            row = UserNotificationPreference(
                tenant_id=tenant_id,
                user_id=user_id,
                email_enabled=email_enabled,
                in_app_enabled=in_app_enabled,
                whatsapp_enabled=whatsapp_enabled,
            )
            self.session.add(row)
            await self.session.flush()
            return row
        row.email_enabled = email_enabled
        row.in_app_enabled = in_app_enabled
        row.whatsapp_enabled = whatsapp_enabled
        await self.session.flush()
        return row
