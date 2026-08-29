"""Category queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.categories.models import Category


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Category,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "code", "name"}),
            allowed_filter_fields=frozenset({"parent_id", "is_active"}),
            search_fields=frozenset({"code", "name"}),
        )

    async def get(self, tenant_id: UUID, category_id: UUID) -> Category | None:
        return await self._repo.get(tenant_id, category_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Category], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Category:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, category_id: UUID, values: Mapping[str, object]
    ) -> Category | None:
        return await self._repo.update(tenant_id, category_id, values)

    async def soft_delete(self, tenant_id: UUID, category_id: UUID) -> Category | None:
        return await self._repo.soft_delete(tenant_id, category_id)

    async def count_children(self, tenant_id: UUID, parent_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Category)
            .where(
                Category.tenant_id == tenant_id,
                Category.parent_id == parent_id,
                Category.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(statement)
        return int(total or 0)
