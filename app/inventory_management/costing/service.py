"""FIFO costing: add, consume, offset negatives, restore. Mutations from StockService."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money, quantize_quantity
from app.core.exceptions import CostLayerImbalanceError, ValidationError
from app.inventory_management.costing.models import StockCostConsumption, StockCostLayer
from app.inventory_management.costing.repository import CostingRepository
from app.inventory_management.stock.models import StockMovement

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class CostConsumption:
    layer_id: UUID
    qty: Decimal
    unit_cost: Decimal


class CostingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CostingRepository(session)

    async def add_layer(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        qty: Decimal,
        unit_cost: Decimal,
        source_type: str,
        source_id: UUID,
        document_date: date,
        source_line_id: UUID | None = None,
        landed_unit_cost: Decimal | None = None,
        is_estimated: bool = False,
        is_negative: bool = False,
    ) -> StockCostLayer:
        qty = quantize_quantity(qty)
        if qty == _ZERO:
            raise ValidationError("Cost layer quantity cannot be zero")
        cost = quantize_money(unit_cost)
        landed = quantize_money(landed_unit_cost if landed_unit_cost is not None else cost)
        return await self.repo.create_layer(
            tenant_id,
            {
                "warehouse_id": warehouse_id,
                "product_id": product_id,
                "source_type": source_type,
                "source_id": source_id,
                "source_line_id": source_line_id,
                "document_date": document_date,
                "qty_received": qty,
                "qty_remaining": qty,
                "unit_cost": cost,
                "landed_unit_cost": landed,
                "is_estimated": is_estimated,
                "is_negative": is_negative or qty < _ZERO,
            },
        )

    async def consume(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        qty: Decimal,
        movement_id: UUID,
        document_date: date,
        source_type: str,
        source_id: UUID,
        allow_negative: bool,
        fallback_unit_cost: Decimal,
        source_line_id: UUID | None = None,
    ) -> tuple[tuple[CostConsumption, ...], Decimal]:
        remaining = quantize_quantity(qty)
        if remaining <= _ZERO:
            raise ValidationError("Consume quantity must be positive")
        layers = await self.repo.list_positive_fifo(
            tenant_id, warehouse_id, product_id, for_update=True
        )
        consumed: list[CostConsumption] = []
        total = _ZERO
        for layer in layers:
            if remaining <= _ZERO:
                break
            take = layer.qty_remaining if layer.qty_remaining <= remaining else remaining
            take = quantize_quantity(take)
            layer.qty_remaining = quantize_quantity(layer.qty_remaining - take)
            layer_cost = layer.landed_unit_cost
            await self.repo.create_consumption(
                tenant_id,
                {
                    "movement_id": movement_id,
                    "layer_id": layer.id,
                    "qty": take,
                    "unit_cost": layer_cost,
                },
            )
            consumed.append(CostConsumption(layer_id=layer.id, qty=take, unit_cost=layer_cost))
            total += take * layer_cost
            remaining -= take
        if remaining > _ZERO:
            if not allow_negative:
                raise CostLayerImbalanceError(
                    details={
                        "warehouse_id": str(warehouse_id),
                        "product_id": str(product_id),
                        "unlayered_qty": str(remaining),
                    }
                )
            last_cost = await self._last_known_cost(
                tenant_id, warehouse_id, product_id, fallback_unit_cost
            )
            negative = await self._extend_or_create_negative(
                tenant_id,
                warehouse_id=warehouse_id,
                product_id=product_id,
                qty=remaining,
                unit_cost=last_cost,
                document_date=document_date,
                source_type=source_type,
                source_id=source_id,
                source_line_id=source_line_id,
            )
            await self.repo.create_consumption(
                tenant_id,
                {
                    "movement_id": movement_id,
                    "layer_id": negative.id,
                    "qty": remaining,
                    "unit_cost": last_cost,
                },
            )
            consumed.append(
                CostConsumption(layer_id=negative.id, qty=remaining, unit_cost=last_cost)
            )
            total += remaining * last_cost
        await self.session.flush()
        return tuple(consumed), quantize_money(total)

    async def consume_from_source(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        qty: Decimal,
        movement_id: UUID,
        original_source_type: str,
        original_source_id: UUID,
        original_source_line_id: UUID | None,
    ) -> tuple[tuple[CostConsumption, ...], Decimal]:
        """Consume remaining qty from the original inbound layers only, not today's FIFO mix."""

        remaining = quantize_quantity(qty)
        if remaining <= _ZERO:
            raise ValidationError("Consume quantity must be positive")
        layers = await self.repo.list_positive_fifo_for_source(
            tenant_id,
            warehouse_id,
            product_id,
            source_type=original_source_type,
            source_id=original_source_id,
            source_line_id=original_source_line_id,
            for_update=True,
        )
        consumed: list[CostConsumption] = []
        total = _ZERO
        for layer in layers:
            if remaining <= _ZERO:
                break
            take = layer.qty_remaining if layer.qty_remaining <= remaining else remaining
            take = quantize_quantity(take)
            if take <= _ZERO:
                continue
            layer.qty_remaining = quantize_quantity(layer.qty_remaining - take)
            layer_cost = layer.landed_unit_cost
            await self.repo.create_consumption(
                tenant_id,
                {
                    "movement_id": movement_id,
                    "layer_id": layer.id,
                    "qty": take,
                    "unit_cost": layer_cost,
                },
            )
            consumed.append(CostConsumption(layer_id=layer.id, qty=take, unit_cost=layer_cost))
            total += take * layer_cost
            remaining -= take
        if remaining > _ZERO:
            raise ValidationError(
                "Original receipt layers do not have enough remaining quantity to return"
            )
        await self.session.flush()
        return tuple(consumed), quantize_money(total)

    async def offset_negative_layers(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        receipt_qty: Decimal,
        unit_cost: Decimal,
        movement_id: UUID,
    ) -> Decimal:
        remaining = quantize_quantity(receipt_qty)
        if remaining <= _ZERO:
            return remaining
        negatives = await self.repo.list_negative_fifo(
            tenant_id, warehouse_id, product_id, for_update=True
        )
        cost = quantize_money(unit_cost)
        for layer in negatives:
            if remaining <= _ZERO:
                break
            debt = quantize_quantity(-layer.qty_remaining)
            offset = debt if debt <= remaining else remaining
            offset = quantize_quantity(offset)
            layer.qty_remaining = quantize_quantity(layer.qty_remaining + offset)
            await self.repo.create_consumption(
                tenant_id,
                {
                    "movement_id": movement_id,
                    "layer_id": layer.id,
                    "qty": offset,
                    "unit_cost": cost,
                },
            )
            remaining -= offset
        await self.session.flush()
        return remaining

    async def restore(self, tenant_id: UUID, consumptions: Sequence[CostConsumption]) -> None:
        for item in consumptions:
            layer = await self.repo.get(tenant_id, item.layer_id)
            if layer is None:
                raise ValidationError("Cost layer not found for restore")
            layer.qty_remaining = quantize_quantity(layer.qty_remaining + item.qty)
        await self.session.flush()

    async def restore_partial(
        self, tenant_id: UUID, movement_id: UUID, qty: Decimal
    ) -> tuple[CostConsumption, ...]:
        remaining = quantize_quantity(qty)
        if remaining <= _ZERO:
            raise ValidationError("Restore quantity must be positive")
        rows = await self.repo.list_consumptions_for_movement(
            tenant_id, movement_id, for_update=True
        )
        restored: list[CostConsumption] = []
        for row in rows:
            restorable = quantize_quantity(row.qty - row.qty_restored)
            if restorable <= _ZERO:
                continue
            take = restorable if restorable <= remaining else remaining
            take = quantize_quantity(take)
            layer = await self.repo.get(tenant_id, row.layer_id)
            if layer is None:
                raise ValidationError("Cost layer not found for restore")
            layer.qty_remaining = quantize_quantity(layer.qty_remaining + take)
            row.qty_restored = quantize_quantity(row.qty_restored + take)
            restored.append(
                CostConsumption(layer_id=row.layer_id, qty=take, unit_cost=row.unit_cost)
            )
            remaining = quantize_quantity(remaining - take)
            if remaining <= _ZERO:
                break
        if remaining > _ZERO:
            raise ValidationError(
                "Restore quantity exceeds restorable consumptions",
                details={"unrestorable_qty": str(remaining)},
            )
        await self.session.flush()
        return tuple(restored)

    async def unrestore_partial(
        self, tenant_id: UUID, movement_id: UUID, qty: Decimal
    ) -> tuple[CostConsumption, ...]:
        """Undo a previous restore against this outbound movement's consumptions."""

        remaining = quantize_quantity(qty)
        if remaining <= _ZERO:
            raise ValidationError("Unrestore quantity must be positive")
        rows = await self.repo.list_consumptions_for_movement(
            tenant_id, movement_id, for_update=True
        )
        undone: list[CostConsumption] = []
        for row in reversed(list(rows)):
            available = quantize_quantity(row.qty_restored)
            if available <= _ZERO:
                continue
            take = available if available <= remaining else remaining
            take = quantize_quantity(take)
            layer = await self.repo.get(tenant_id, row.layer_id)
            if layer is None:
                raise ValidationError("Cost layer not found for unrestore")
            layer.qty_remaining = quantize_quantity(layer.qty_remaining - take)
            row.qty_restored = quantize_quantity(row.qty_restored - take)
            undone.append(CostConsumption(layer_id=row.layer_id, qty=take, unit_cost=row.unit_cost))
            remaining = quantize_quantity(remaining - take)
            if remaining <= _ZERO:
                break
        if remaining > _ZERO:
            raise ValidationError(
                "Unrestore quantity exceeds restored consumptions",
                details={"unrestorable_qty": str(remaining)},
            )
        await self.session.flush()
        return tuple(undone)

    async def net_cost_for_source_line(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID,
    ) -> tuple[Decimal, Decimal]:
        """Return (qty, value) still consumed for one source line, net of returns."""

        return await self._net_cost(
            tenant_id, source_type, source_id, source_line_id=source_line_id
        )

    async def net_cost_for_source(
        self, tenant_id: UUID, source_type: str, source_id: UUID
    ) -> tuple[Decimal, Decimal]:
        """Return (qty, value) still consumed for a source document, net of returns."""

        return await self._net_cost(tenant_id, source_type, source_id, source_line_id=None)

    async def _net_cost(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        *,
        source_line_id: UUID | None,
    ) -> tuple[Decimal, Decimal]:
        open_qty = StockCostConsumption.qty - StockCostConsumption.qty_restored
        criteria = [
            StockCostConsumption.tenant_id == tenant_id,
            StockMovement.tenant_id == tenant_id,
            StockMovement.source_type == source_type,
            StockMovement.source_id == source_id,
        ]
        if source_line_id is not None:
            criteria.append(StockMovement.source_line_id == source_line_id)
        statement = (
            select(
                func.coalesce(func.sum(open_qty), _ZERO),
                func.coalesce(func.sum(open_qty * StockCostConsumption.unit_cost), _ZERO),
            )
            .select_from(StockCostConsumption)
            .join(StockMovement, StockMovement.id == StockCostConsumption.movement_id)
            .where(*criteria)
        )
        qty, value = (await self.session.execute(statement)).one()
        qty_value = qty if isinstance(qty, Decimal) else Decimal(str(qty or 0))
        money_value = value if isinstance(value, Decimal) else Decimal(str(value or 0))
        return quantize_quantity(qty_value), quantize_money(money_value)

    async def revalue(
        self, tenant_id: UUID, layer_id: UUID, new_landed_unit_cost: Decimal
    ) -> StockCostLayer:
        layer = await self.repo.get(tenant_id, layer_id)
        if layer is None:
            raise ValidationError("Cost layer not found")
        layer.landed_unit_cost = quantize_money(new_landed_unit_cost)
        await self.session.flush()
        return layer

    async def delete_layers_for_source(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID | None = None,
    ) -> int:
        return await self.repo.delete_layers_for_source(
            tenant_id, source_type, source_id, source_line_id
        )

    async def layers_fully_remaining(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> bool:
        layers = await self.repo.list_layers_for_source(tenant_id, source_type, source_id)
        return all(layer.qty_remaining == layer.qty_received for layer in layers)

    async def layers_for_source(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID | None = None,
    ) -> Sequence[StockCostLayer]:
        return await self.repo.list_layers_for_source(
            tenant_id, source_type, source_id, source_line_id
        )

    async def list_layers(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> Sequence[StockCostLayer]:
        return await self.repo.list_for_balance(tenant_id, warehouse_id, product_id)

    async def remaining_value(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> tuple[Decimal, Decimal]:
        layers = await self.repo.list_for_balance(tenant_id, warehouse_id, product_id)
        qty = sum((layer.qty_remaining for layer in layers), _ZERO)
        value = sum((layer.qty_remaining * layer.landed_unit_cost for layer in layers), _ZERO)
        return quantize_quantity(qty), quantize_money(value)

    async def assert_balanced(
        self,
        tenant_id: UUID,
        warehouse_id: UUID,
        product_id: UUID,
        qty_on_hand: Decimal,
    ) -> None:
        remaining = await self.repo.sum_remaining(tenant_id, warehouse_id, product_id)
        if remaining != quantize_quantity(qty_on_hand):
            raise CostLayerImbalanceError(
                details={
                    "warehouse_id": str(warehouse_id),
                    "product_id": str(product_id),
                    "qty_on_hand": str(qty_on_hand),
                    "layer_qty_remaining": str(remaining),
                }
            )

    async def _last_known_cost(
        self,
        tenant_id: UUID,
        warehouse_id: UUID,
        product_id: UUID,
        fallback: Decimal,
    ) -> Decimal:
        latest = await self.repo.latest_layer(tenant_id, warehouse_id, product_id)
        if latest is not None:
            return latest.landed_unit_cost
        return quantize_money(fallback)

    async def _extend_or_create_negative(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        qty: Decimal,
        unit_cost: Decimal,
        document_date: date,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID | None,
    ) -> StockCostLayer:
        existing = await self.repo.list_negative_fifo(
            tenant_id, warehouse_id, product_id, for_update=True
        )
        if existing:
            layer = existing[-1]
            layer.qty_remaining = quantize_quantity(layer.qty_remaining - qty)
            layer.qty_received = quantize_quantity(layer.qty_received - qty)
            await self.session.flush()
            return layer
        return await self.add_layer(
            tenant_id,
            warehouse_id=warehouse_id,
            product_id=product_id,
            qty=-qty,
            unit_cost=unit_cost,
            source_type=source_type,
            source_id=source_id,
            source_line_id=source_line_id,
            document_date=document_date,
            is_negative=True,
        )
