"""Product queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.products.models import Product


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Product,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "sku", "name"}),
            allowed_filter_fields=frozenset(
                {"item_type", "category_id", "unit_id", "tax_id", "is_active"}
            ),
            search_fields=frozenset({"sku", "name", "sales_description"}),
        )

    async def get(self, tenant_id: UUID, product_id: UUID) -> Product | None:
        return await self._repo.get(tenant_id, product_id)

    async def get_many(self, tenant_id: UUID, ids: Sequence[UUID]) -> Sequence[Product]:
        if not ids:
            return []
        statement = self._repo.base_query(tenant_id).where(Product.id.in_(list(ids)))
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def search_ids(self, tenant_id: UUID, search: str) -> list[UUID]:
        term = f"%{search}%"
        statement = select(Product.id).where(
            Product.tenant_id == tenant_id,
            Product.deleted_at.is_(None),
            or_(Product.sku.ilike(term), Product.name.ilike(term)),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def ids_by_category(self, tenant_id: UUID, category_id: UUID) -> list[UUID]:
        statement = select(Product.id).where(
            Product.tenant_id == tenant_id,
            Product.deleted_at.is_(None),
            Product.category_id == category_id,
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Product], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Product:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, product_id: UUID, values: Mapping[str, object]
    ) -> Product | None:
        return await self._repo.update(tenant_id, product_id, values)

    async def soft_delete(self, tenant_id: UUID, product_id: UUID) -> Product | None:
        return await self._repo.soft_delete(tenant_id, product_id)
