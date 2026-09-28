"""Task persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.task_management.tasks.models import Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Task,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "due_at",
                    "title",
                    "status",
                    "priority",
                    "sort_order",
                    "task_number",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "priority",
                    "assignee_id",
                    "parent_id",
                    "related_entity_type",
                    "related_entity_id",
                }
            ),
            search_fields=frozenset({"title", "description", "task_number"}),
        )

    async def get(self, tenant_id: UUID, task_id: UUID) -> Task | None:
        return await self._repo.get(tenant_id, task_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[Task], int]:
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Task:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, task_id: UUID, values: Mapping[str, object]
    ) -> Task | None:
        return await self._repo.update(tenant_id, task_id, values)

    async def soft_delete(self, tenant_id: UUID, task_id: UUID) -> Task | None:
        return await self._repo.soft_delete(tenant_id, task_id)
