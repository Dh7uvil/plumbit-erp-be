"""Warehouse queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.warehouses.models import Warehouse


class WarehouseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Warehouse,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "code", "name"}),
            allowed_filter_fields=frozenset({"is_active", "is_default"}),
            search_fields=frozenset({"code", "name"}),
        )

    async def get(self, tenant_id: UUID, warehouse_id: UUID) -> Warehouse | None:
        return await self._repo.get(tenant_id, warehouse_id)

    async def get_many(self, tenant_id: UUID, ids: Sequence[UUID]) -> Sequence[Warehouse]:
        if not ids:
            return []
        statement = self._repo.base_query(tenant_id).where(Warehouse.id.in_(list(ids)))
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def search_ids(self, tenant_id: UUID, search: str) -> list[UUID]:
        term = f"%{search}%"
        statement = select(Warehouse.id).where(
            Warehouse.tenant_id == tenant_id,
            Warehouse.deleted_at.is_(None),
            or_(Warehouse.code.ilike(term), Warehouse.name.ilike(term)),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def count(self, tenant_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Warehouse)
            .where(
                Warehouse.tenant_id == tenant_id,
                Warehouse.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(statement)
        return int(total or 0)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Warehouse], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Warehouse:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, warehouse_id: UUID, values: Mapping[str, object]
    ) -> Warehouse | None:
        return await self._repo.update(tenant_id, warehouse_id, values)

    async def soft_delete(self, tenant_id: UUID, warehouse_id: UUID) -> Warehouse | None:
        return await self._repo.soft_delete(tenant_id, warehouse_id)

    async def clear_other_defaults(self, tenant_id: UUID, *, keep_id: UUID | None = None) -> None:
        criteria = [
            Warehouse.tenant_id == tenant_id,
            Warehouse.is_default.is_(True),
            Warehouse.deleted_at.is_(None),
        ]
        if keep_id is not None:
            criteria.append(Warehouse.id != keep_id)
        result = await self.session.execute(select(Warehouse).where(*criteria))
        for row in result.scalars().all():
            row.is_default = False
        await self.session.flush()
