"""Persistence for in-app notifications."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notifications.models import Notification
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
    ) -> Notification:
        row = Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            body=body,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int]:
        filters = [
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
        ]
        if unread_only:
            filters.append(Notification.read_at.is_(None))
        if common_filter is not None:
            if common_filter.date_from is not None:
                filters.append(Notification.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                filters.append(Notification.created_at <= common_filter.date_to)
            if common_filter.search:
                pattern = f"%{common_filter.search}%"
                filters.append(
                    Notification.title.ilike(pattern) | Notification.body.ilike(pattern)
                )

        count_stmt = select(func.count()).select_from(Notification).where(*filters)
        total = int(await self.session.scalar(count_stmt) or 0)

        sort_column = Notification.created_at
        order = sort_column.desc()
        if common_filter is not None and common_filter.sort_order == "asc":
            order = sort_column.asc()

        stmt = (
            select(Notification)
            .where(*filters)
            .order_by(order)
            .offset(page.offset)
            .limit(page.page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_unread(self, tenant_id: UUID, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
        )
        return int(await self.session.scalar(stmt) or 0)

    async def get_for_user(
        self, tenant_id: UUID, user_id: UUID, notification_id: UUID
    ) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.id == notification_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_read(
        self, tenant_id: UUID, user_id: UUID, notification_id: UUID, *, read_at: datetime
    ) -> Notification | None:
        row = await self.get_for_user(tenant_id, user_id, notification_id)
        if row is None or row.read_at is not None:
            return row
        row.read_at = read_at
        await self.session.flush()
        return row

    async def mark_all_read(
        self, tenant_id: UUID, user_id: UUID, *, read_at: datetime
    ) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=read_at)
        )
        await self.session.flush()
        return int(result.rowcount or 0)
