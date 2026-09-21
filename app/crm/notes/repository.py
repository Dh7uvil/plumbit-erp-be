"""Note persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.notes.models import Note


class NoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Note,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"related_entity_type", "related_entity_id"}),
            search_fields=frozenset({"body"}),
        )

    async def get(self, tenant_id: UUID, note_id: UUID) -> Note | None:
        return await self._repo.get(tenant_id, note_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Note], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Note:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, note_id: UUID, values: Mapping[str, object]
    ) -> Note | None:
        return await self._repo.update(tenant_id, note_id, values)

    async def soft_delete(self, tenant_id: UUID, note_id: UUID) -> Note | None:
        return await self._repo.soft_delete(tenant_id, note_id)
