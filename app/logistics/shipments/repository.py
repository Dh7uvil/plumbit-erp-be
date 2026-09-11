"""Shipment queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.logistics.shipments.models import Shipment


class ShipmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Shipment,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "status", "etd", "eta"}
            ),
            allowed_filter_fields=frozenset({"status", "shipment_type", "transport_mode"}),
            search_fields=frozenset(
                {
                    "document_number",
                    "container_number",
                    "bl_awb_number",
                    "carrier_name",
                    "notes",
                }
            ),
        )

    async def get(
        self, tenant_id: UUID, shipment_id: UUID, *, for_update: bool = False
    ) -> Shipment | None:
        statement = self._repo.base_query(tenant_id).where(Shipment.id == shipment_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Shipment], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def list_by_ids(
        self, tenant_id: UUID, shipment_ids: Sequence[UUID]
    ) -> Sequence[Shipment]:
        if not shipment_ids:
            return []
        statement = (
            self._repo.base_query(tenant_id)
            .where(Shipment.id.in_(list(shipment_ids)))
            .order_by(Shipment.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Shipment:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, shipment_id: UUID, values: Mapping[str, object]
    ) -> Shipment | None:
        return await self._repo.update(tenant_id, shipment_id, values)

    async def soft_delete(self, tenant_id: UUID, shipment_id: UUID) -> Shipment | None:
        return await self._repo.soft_delete(tenant_id, shipment_id)
