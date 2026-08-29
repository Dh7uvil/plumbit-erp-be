"""Price-list queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.price_lists.models import PriceList, PriceListItem


class PriceListRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            PriceList,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
            allowed_filter_fields=frozenset({"currency_id", "list_type", "is_active"}),
            search_fields=frozenset({"name"}),
        )
        self._items = BaseRepository(
            session,
            PriceListItem,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"price_list_id", "product_id"}),
        )

    async def get(self, tenant_id: UUID, price_list_id: UUID) -> PriceList | None:
        return await self._repo.get(tenant_id, price_list_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[PriceList], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> PriceList:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, price_list_id: UUID, values: Mapping[str, object]
    ) -> PriceList | None:
        return await self._repo.update(tenant_id, price_list_id, values)

    async def soft_delete(self, tenant_id: UUID, price_list_id: UUID) -> PriceList | None:
        return await self._repo.soft_delete(tenant_id, price_list_id)

    async def get_item(
        self, tenant_id: UUID, price_list_id: UUID, product_id: UUID
    ) -> PriceListItem | None:
        statement = select(PriceListItem).where(
            PriceListItem.tenant_id == tenant_id,
            PriceListItem.price_list_id == price_list_id,
            PriceListItem.product_id == product_id,
            PriceListItem.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_items(self, tenant_id: UUID, price_list_id: UUID) -> Sequence[PriceListItem]:
        statement = (
            select(PriceListItem)
            .where(
                PriceListItem.tenant_id == tenant_id,
                PriceListItem.price_list_id == price_list_id,
                PriceListItem.deleted_at.is_(None),
            )
            .order_by(PriceListItem.created_at.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def upsert_item(
        self,
        tenant_id: UUID,
        *,
        price_list_id: UUID,
        product_id: UUID,
        rate: object,
    ) -> PriceListItem:
        existing = await self.get_item(tenant_id, price_list_id, product_id)
        if existing is not None:
            existing.rate = rate  # type: ignore[assignment]
            await self.session.flush()
            return existing
        return await self._items.create(
            tenant_id,
            {
                "price_list_id": price_list_id,
                "product_id": product_id,
                "rate": rate,
            },
        )

    async def delete_item(
        self, tenant_id: UUID, price_list_id: UUID, product_id: UUID
    ) -> PriceListItem | None:
        existing = await self.get_item(tenant_id, price_list_id, product_id)
        if existing is None:
            return None
        return await self._items.soft_delete(tenant_id, existing.id)
