"""Activity persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.activities.models import Activity


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Activity,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "due_at",
                    "start_at",
                    "subject",
                    "status",
                    "priority",
                    "activity_type",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "related_entity_type",
                    "related_entity_id",
                    "owner_id",
                    "status",
                    "activity_type",
                }
            ),
            search_fields=frozenset({"subject", "description", "outcome"}),
        )

    async def get(self, tenant_id: UUID, activity_id: UUID) -> Activity | None:
        return await self._repo.get(tenant_id, activity_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[Activity], int]:
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Activity:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, activity_id: UUID, values: Mapping[str, object]
    ) -> Activity | None:
        return await self._repo.update(tenant_id, activity_id, values)

    async def soft_delete(self, tenant_id: UUID, activity_id: UUID) -> Activity | None:
        return await self._repo.soft_delete(tenant_id, activity_id)
