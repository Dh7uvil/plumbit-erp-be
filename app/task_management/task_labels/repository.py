"""Task label persistence."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.task_management.task_labels.models import TaskLabel


class TaskLabelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            TaskLabel,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "color"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, tenant_id: UUID, label_id: UUID) -> TaskLabel | None:
        return await self._repo.get(tenant_id, label_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[list[TaskLabel], int]:
        rows, total = await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return list(rows), total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> TaskLabel:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, label_id: UUID, values: Mapping[str, object]
    ) -> TaskLabel | None:
        return await self._repo.update(tenant_id, label_id, values)

    async def soft_delete(self, tenant_id: UUID, label_id: UUID) -> TaskLabel | None:
        return await self._repo.soft_delete(tenant_id, label_id)
