"""Cost center queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.cost_centers.models import CostCenter


class CostCenterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            CostCenter,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "code", "is_active"}
            ),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name", "code", "description"}),
        )

    async def get(self, tenant_id: UUID, cost_center_id: UUID) -> CostCenter | None:
        return await self._repo.get(tenant_id, cost_center_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[CostCenter], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> CostCenter:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, cost_center_id: UUID, values: Mapping[str, object]
    ) -> CostCenter | None:
        return await self._repo.update(tenant_id, cost_center_id, values)

    async def soft_delete(self, tenant_id: UUID, cost_center_id: UUID) -> CostCenter | None:
        return await self._repo.soft_delete(tenant_id, cost_center_id)
