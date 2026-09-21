"""Lost reason persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.lost_reasons.models import LostReason


class LostReasonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            LostReason,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "is_active"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name", "description"}),
        )

    async def get(self, tenant_id: UUID, lost_reason_id: UUID) -> LostReason | None:
        return await self._repo.get(tenant_id, lost_reason_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[LostReason], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> LostReason:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, lost_reason_id: UUID, values: Mapping[str, object]
    ) -> LostReason | None:
        return await self._repo.update(tenant_id, lost_reason_id, values)

    async def soft_delete(self, tenant_id: UUID, lost_reason_id: UUID) -> LostReason | None:
        return await self._repo.soft_delete(tenant_id, lost_reason_id)
