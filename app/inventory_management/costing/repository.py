"""FIFO cost layer queries."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory_management.costing.models import StockCostConsumption, StockCostLayer

_ZERO = Decimal("0")


class CostingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, layer_id: UUID) -> StockCostLayer | None:
        statement = select(StockCostLayer).where(
            StockCostLayer.tenant_id == tenant_id,
            StockCostLayer.id == layer_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_balance(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> Sequence[StockCostLayer]:
        statement = (
            select(StockCostLayer)
            .where(
                StockCostLayer.tenant_id == tenant_id,
                StockCostLayer.warehouse_id == warehouse_id,
                StockCostLayer.product_id == product_id,
            )
            .order_by(StockCostLayer.document_date.asc(), StockCostLayer.created_at.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_positive_fifo(
        self,
        tenant_id: UUID,
        warehouse_id: UUID,
        product_id: UUID,
        *,
        for_update: bool = False,
    ) -> Sequence[StockCostLayer]:
        statement = (
            select(StockCostLayer)
            .where(
                StockCostLayer.tenant_id == tenant_id,
                StockCostLayer.warehouse_id == warehouse_id,
                StockCostLayer.product_id == product_id,
                StockCostLayer.qty_remaining > _ZERO,
            )
            .order_by(StockCostLayer.document_date.asc(), StockCostLayer.created_at.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_negative_fifo(
        self,
        tenant_id: UUID,
        warehouse_id: UUID,
        product_id: UUID,
        *,
        for_update: bool = False,
    ) -> Sequence[StockCostLayer]:
        statement = (
            select(StockCostLayer)
            .where(
                StockCostLayer.tenant_id == tenant_id,
                StockCostLayer.warehouse_id == warehouse_id,
                StockCostLayer.product_id == product_id,
                StockCostLayer.qty_remaining < _ZERO,
            )
            .order_by(StockCostLayer.document_date.asc(), StockCostLayer.created_at.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def latest_layer(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> StockCostLayer | None:
        statement = (
            select(StockCostLayer)
            .where(
                StockCostLayer.tenant_id == tenant_id,
                StockCostLayer.warehouse_id == warehouse_id,
                StockCostLayer.product_id == product_id,
            )
            .order_by(StockCostLayer.document_date.desc(), StockCostLayer.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def sum_remaining(self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID) -> Decimal:
        statement = select(func.coalesce(func.sum(StockCostLayer.qty_remaining), _ZERO)).where(
            StockCostLayer.tenant_id == tenant_id,
            StockCostLayer.warehouse_id == warehouse_id,
            StockCostLayer.product_id == product_id,
        )
        result = await self.session.execute(statement)
        value = result.scalar_one()
        return value if isinstance(value, Decimal) else Decimal(str(value or 0))

    async def create_layer(self, tenant_id: UUID, values: dict[str, object]) -> StockCostLayer:
        entity = StockCostLayer(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(entity, name, value)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def create_consumption(
        self, tenant_id: UUID, values: dict[str, object]
    ) -> StockCostConsumption:
        entity = StockCostConsumption(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(entity, name, value)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def list_consumptions_for_movement(
        self, tenant_id: UUID, movement_id: UUID, *, for_update: bool = False
    ) -> Sequence[StockCostConsumption]:
        statement = (
            select(StockCostConsumption)
            .where(
                StockCostConsumption.tenant_id == tenant_id,
                StockCostConsumption.movement_id == movement_id,
            )
            .order_by(StockCostConsumption.created_at.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_layers_for_source(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID | None = None,
    ) -> Sequence[StockCostLayer]:
        criteria = [
            StockCostLayer.tenant_id == tenant_id,
            StockCostLayer.source_type == source_type,
            StockCostLayer.source_id == source_id,
        ]
        if source_line_id is not None:
            criteria.append(StockCostLayer.source_line_id == source_line_id)
        statement = select(StockCostLayer).where(*criteria)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def delete_layers_for_source(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID | None = None,
    ) -> int:
        layers = await self.list_layers_for_source(
            tenant_id, source_type, source_id, source_line_id
        )
        if not layers:
            return 0
        layer_ids = [layer.id for layer in layers]
        await self.session.execute(
            delete(StockCostConsumption).where(
                StockCostConsumption.tenant_id == tenant_id,
                StockCostConsumption.layer_id.in_(layer_ids),
            )
        )
        await self.session.execute(
            delete(StockCostLayer).where(
                StockCostLayer.tenant_id == tenant_id,
                StockCostLayer.id.in_(layer_ids),
            )
        )
        await self.session.flush()
        return len(layer_ids)

    async def has_any_layers(self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID) -> bool:
        statement = (
            select(StockCostLayer.id)
            .where(
                StockCostLayer.tenant_id == tenant_id,
                StockCostLayer.warehouse_id == warehouse_id,
                StockCostLayer.product_id == product_id,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None
