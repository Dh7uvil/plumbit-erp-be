"""In-app notification use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notifications.repository import NotificationRepository
from app.common.notifications.schemas import NotificationResponse, UnreadCountResponse
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.exceptions import ResourceNotFoundError
from app.db.session import transaction


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)

    async def create(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        event: str,
        entity_type: str,
        entity_id: UUID | None,
        title: str,
        body: str,
    ) -> NotificationResponse:
        row = await self.repo.create(
            tenant_id,
            user_id,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            body=body,
        )
        return NotificationResponse.model_validate(row)

    async def list(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        unread_only: bool = False,
    ) -> tuple[list[NotificationResponse], int]:
        rows, total = await self.repo.list_for_user(
            tenant_id,
            user_id,
            page=page,
            common_filter=common_filter,
            unread_only=unread_only,
        )
        return [NotificationResponse.model_validate(row) for row in rows], total

    async def unread_count(self, tenant_id: UUID, user_id: UUID) -> UnreadCountResponse:
        count = await self.repo.count_unread(tenant_id, user_id)
        return UnreadCountResponse(count=count)

    async def mark_read(
        self, tenant_id: UUID, user_id: UUID, notification_id: UUID
    ) -> NotificationResponse:
        async with transaction(self.session):
            row = await self.repo.mark_read(
                tenant_id, user_id, notification_id, read_at=utcnow()
            )
            if row is None:
                raise ResourceNotFoundError("Notification not found")
            return NotificationResponse.model_validate(row)

    async def mark_all_read(self, tenant_id: UUID, user_id: UUID) -> UnreadCountResponse:
        async with transaction(self.session):
            await self.repo.mark_all_read(tenant_id, user_id, read_at=utcnow())
            return await self.unread_count(tenant_id, user_id)
