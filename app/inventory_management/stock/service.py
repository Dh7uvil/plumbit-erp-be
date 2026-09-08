"""Sole writer for stock balances and movements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.auth.catalog import INVENTORY_MODULE
from app.auth.org_service import OrganizationService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import utcnow
from app.core.enums import AuditAction, StockMovementType
from app.core.exceptions import (
    InsufficientStockError,
    PeriodLockedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.db.session import transaction
from app.inventory_management.products.schemas import ProductResponse
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.models import StockBalance, StockMovement
from app.inventory_management.stock.repository import (
    StockBalanceRepository,
    StockMovementRepository,
)
from app.inventory_management.stock.schemas import (
    StockBalanceResponse,
    StockMovementFilter,
    StockMovementResponse,
    StockReorderUpdate,
)
from app.inventory_management.warehouses.schemas import WarehouseResponse
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
SOURCE_STOCK_ADJUSTMENT = "stock_adjustment"
SOURCE_STOCK_TRANSFER = "stock_transfer"


@dataclass(slots=True)
class LockedBalance:
    row: StockBalance
    warehouse: WarehouseResponse
    product: ProductResponse
    allow_negative_stock: bool


class StockService:
    """The only code that updates balances or inserts movements."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.balances = StockBalanceRepository(session)
        self.movements = StockMovementRepository(session)
        self.products = ProductService(session)
        self.warehouses = WarehouseService(session)
        self.org = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list_balances(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        warehouse_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
        negative_only: bool = False,
        below_reorder: bool = False,
    ) -> tuple[list[StockBalanceResponse], int]:
        extra: list[ColumnElement[bool]] = []
        search = common_filter.search if common_filter is not None else None
        repo_filter = (
            common_filter.model_copy(update={"search": None})
            if common_filter is not None and search
            else common_filter
        )
        category_product_ids: list[UUID] | None = None
        if category_id is not None:
            category_product_ids = await self.products.ids_by_category(tenant_id, category_id)
            if not category_product_ids:
                return [], 0
            extra.append(StockBalance.product_id.in_(category_product_ids))
        if search:
            product_ids = await self.products.search_ids(tenant_id, search)
            warehouse_ids = await self.warehouses.search_ids(tenant_id, search)
            if category_product_ids is not None:
                product_ids = [item for item in product_ids if item in set(category_product_ids)]
            search_clauses: list[ColumnElement[bool]] = []
            if product_ids:
                search_clauses.append(StockBalance.product_id.in_(product_ids))
            if warehouse_ids:
                search_clauses.append(StockBalance.warehouse_id.in_(warehouse_ids))
            if not search_clauses:
                return [], 0
            extra.append(or_(*search_clauses))
        if negative_only:
            extra.append(self.balances.negative_only_clause())
        if below_reorder:
            extra.append(self.balances.below_reorder_clause())
        filters: dict[str, object] = {}
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        if product_id is not None:
            filters["product_id"] = product_id
        rows, total = await self.balances.list(
            tenant_id,
            page=page,
            common_filter=repo_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return await self._balance_responses(tenant_id, rows), total

    async def list_movements(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        filters: StockMovementFilter,
    ) -> tuple[list[StockMovementResponse], int]:
        extra: list[ColumnElement[bool]] = []
        if filters.document_date_from is not None:
            extra.append(StockMovement.document_date >= filters.document_date_from)
        if filters.document_date_to is not None:
            extra.append(StockMovement.document_date <= filters.document_date_to)
        category_product_ids: list[UUID] | None = None
        if filters.category_id is not None:
            category_product_ids = await self.products.ids_by_category(
                tenant_id, filters.category_id
            )
            if not category_product_ids:
                return [], 0
            extra.append(StockMovement.product_id.in_(category_product_ids))
        repo_filter = filters.model_copy(update={"search": None})
        if filters.search:
            product_ids = await self.products.search_ids(tenant_id, filters.search)
            if category_product_ids is not None:
                product_ids = [item for item in product_ids if item in set(category_product_ids)]
            search_clauses: list[ColumnElement[bool]] = [
                StockMovement.notes.ilike(f"%{filters.search}%")
            ]
            if product_ids:
                search_clauses.append(StockMovement.product_id.in_(product_ids))
            extra.append(or_(*search_clauses))
        repo_filters: dict[str, object] = {}
        if filters.warehouse_id is not None:
            repo_filters["warehouse_id"] = filters.warehouse_id
        if filters.product_id is not None:
            repo_filters["product_id"] = filters.product_id
        if filters.movement_type is not None:
            repo_filters["movement_type"] = filters.movement_type.value
        if filters.source_type is not None:
            repo_filters["source_type"] = filters.source_type
        if filters.source_id is not None:
            repo_filters["source_id"] = filters.source_id
        rows, total = await self.movements.list(
            tenant_id,
            page=page,
            common_filter=repo_filter,
            filters=repo_filters or None,
            extra_criteria=extra or None,
        )
        return await self._movement_responses(tenant_id, rows), total

    async def update_reorder(
        self,
        tenant_id: UUID,
        balance_id: UUID,
        payload: StockReorderUpdate,
        *,
        actor_user_id: UUID,
    ) -> StockBalanceResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self.balances.get(tenant_id, balance_id)
            if existing is None:
                raise ResourceNotFoundError("Stock balance not found")
            old_values: dict[str, object] = {
                "reorder_level": existing.reorder_level,
                "reorder_qty": existing.reorder_qty,
            }
            updated = await self.balances.update(tenant_id, balance_id, values)
            if updated is None:
                raise ResourceNotFoundError("Stock balance not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="stock_balance",
                entity_id=updated.id,
                old_values=old_values,
                new_values={
                    "reorder_level": updated.reorder_level,
                    "reorder_qty": updated.reorder_qty,
                },
            )
            responses = await self._balance_responses(tenant_id, (updated,))
            return responses[0]

    async def product_has_activity(self, tenant_id: UUID, product_id: UUID) -> bool:
        if await self.movements.has_movements(tenant_id, product_id):
            return True
        return await self.balances.has_nonzero_balance(tenant_id, product_id)

    async def lock_balance(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        document_date: date,
    ) -> LockedBalance:
        """Validate product/warehouse/period and SELECT FOR UPDATE the balance row."""

        product = await self.products.require_stockable(tenant_id, product_id)
        warehouse = await self.warehouses.get(tenant_id, warehouse_id)
        allow_negative, lock_date, hard_lock_date = await self.org.get_inventory_controls(tenant_id)
        self._assert_period_open(document_date, lock_date, hard_lock_date)
        row = await self._lock_or_create(tenant_id, warehouse_id, product_id)
        return LockedBalance(
            row=row,
            warehouse=warehouse,
            product=product,
            allow_negative_stock=allow_negative,
        )

    async def apply_locked(
        self,
        tenant_id: UUID,
        locked: LockedBalance,
        *,
        qty: Decimal,
        movement_type: StockMovementType,
        source_type: str,
        source_id: UUID,
        source_line_id: UUID | None,
        document_date: date,
        notes: str | None,
        occurred_at: datetime | None = None,
        unit_id: UUID | None = None,
    ) -> StockMovement:
        if qty == _ZERO:
            raise ValidationError("Movement quantity cannot be zero")
        if (
            unit_id is not None
            and locked.product.unit_id is not None
            and unit_id != locked.product.unit_id
        ):
            raise ValidationError("Unit must match the product unit")
        resolved_unit = unit_id if unit_id is not None else locked.product.unit_id
        available = locked.row.qty_on_hand - locked.row.qty_reserved
        resulting_available = available + qty
        if qty < _ZERO and resulting_available < _ZERO and not locked.allow_negative_stock:
            raise InsufficientStockError(
                details={
                    "warehouse_id": str(locked.warehouse.id),
                    "warehouse_code": locked.warehouse.code,
                    "product_id": str(locked.product.id),
                    "available_qty": str(available),
                    "requested_qty": str(-qty),
                }
            )
        qty_before = locked.row.qty_on_hand
        locked.row.qty_on_hand = qty_before + qty
        occurred = occurred_at or utcnow()
        locked.row.last_movement_at = occurred
        await self.session.flush()
        return await self.movements.create(
            tenant_id,
            {
                "movement_type": movement_type.value,
                "warehouse_id": locked.warehouse.id,
                "product_id": locked.product.id,
                "unit_id": resolved_unit,
                "qty": qty,
                "qty_before": qty_before,
                "qty_after": locked.row.qty_on_hand,
                "source_type": source_type,
                "source_id": source_id,
                "source_line_id": source_line_id,
                "document_date": document_date,
                "occurred_at": occurred,
                "notes": notes,
            },
        )

    async def apply_movement(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        qty: Decimal,
        movement_type: StockMovementType,
        source_type: str,
        source_id: UUID,
        document_date: date,
        source_line_id: UUID | None = None,
        notes: str | None = None,
        occurred_at: datetime | None = None,
        unit_id: UUID | None = None,
    ) -> StockMovement:
        locked = await self.lock_balance(
            tenant_id,
            warehouse_id=warehouse_id,
            product_id=product_id,
            document_date=document_date,
        )
        return await self.apply_locked(
            tenant_id,
            locked,
            qty=qty,
            movement_type=movement_type,
            source_type=source_type,
            source_id=source_id,
            source_line_id=source_line_id,
            document_date=document_date,
            notes=notes,
            occurred_at=occurred_at,
            unit_id=unit_id,
        )

    async def _lock_or_create(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> StockBalance:
        existing = await self.balances.get_for_update(tenant_id, warehouse_id, product_id)
        if existing is not None:
            return existing
        try:
            async with self.session.begin_nested():
                created = await self.balances.create(
                    tenant_id,
                    {
                        "warehouse_id": warehouse_id,
                        "product_id": product_id,
                        "qty_on_hand": _ZERO,
                        "qty_reserved": _ZERO,
                        "qty_incoming": _ZERO,
                        "qty_outgoing": _ZERO,
                        "qty_in_transit": _ZERO,
                    },
                )
                locked = await self.balances.get_for_update(tenant_id, warehouse_id, product_id)
                return locked if locked is not None else created
        except IntegrityError:
            row = await self.balances.get_for_update(tenant_id, warehouse_id, product_id)
            if row is None:
                raise
            return row

    def _assert_period_open(
        self,
        document_date: date,
        lock_date: date | None,
        hard_lock_date: date | None,
    ) -> None:
        if (hard_lock_date is not None and document_date <= hard_lock_date) or (
            lock_date is not None and document_date <= lock_date
        ):
            raise PeriodLockedError(
                details={
                    "lock_date": lock_date.isoformat() if lock_date else None,
                    "hard_lock_date": hard_lock_date.isoformat() if hard_lock_date else None,
                    "document_date": document_date.isoformat(),
                }
            )

    async def _balance_responses(
        self, tenant_id: UUID, rows: Sequence[StockBalance]
    ) -> list[StockBalanceResponse]:
        products = await self.products.get_many(tenant_id, [row.product_id for row in rows])
        warehouses = await self.warehouses.get_many(tenant_id, [row.warehouse_id for row in rows])
        responses: list[StockBalanceResponse] = []
        for row in rows:
            product = products.get(row.product_id)
            warehouse = warehouses.get(row.warehouse_id)
            responses.append(
                StockBalanceResponse(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    warehouse_id=row.warehouse_id,
                    warehouse_code=warehouse.code if warehouse else "",
                    warehouse_name=warehouse.name if warehouse else "",
                    product_id=row.product_id,
                    sku=product.sku if product else "",
                    product_name=product.name if product else "",
                    qty_on_hand=row.qty_on_hand,
                    qty_reserved=row.qty_reserved,
                    qty_available=row.qty_on_hand - row.qty_reserved,
                    qty_incoming=row.qty_incoming,
                    qty_outgoing=row.qty_outgoing,
                    qty_in_transit=row.qty_in_transit,
                    reorder_level=row.reorder_level,
                    reorder_qty=row.reorder_qty,
                    last_movement_at=row.last_movement_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return responses

    async def _movement_responses(
        self, tenant_id: UUID, rows: Sequence[StockMovement]
    ) -> list[StockMovementResponse]:
        products = await self.products.get_many(tenant_id, [row.product_id for row in rows])
        warehouses = await self.warehouses.get_many(tenant_id, [row.warehouse_id for row in rows])
        responses: list[StockMovementResponse] = []
        for row in rows:
            product = products.get(row.product_id)
            warehouse = warehouses.get(row.warehouse_id)
            responses.append(
                StockMovementResponse(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    movement_type=StockMovementType(row.movement_type),
                    warehouse_id=row.warehouse_id,
                    warehouse_code=warehouse.code if warehouse else "",
                    warehouse_name=warehouse.name if warehouse else "",
                    product_id=row.product_id,
                    sku=product.sku if product else "",
                    product_name=product.name if product else "",
                    unit_id=row.unit_id,
                    qty=row.qty,
                    qty_before=row.qty_before,
                    qty_after=row.qty_after,
                    source_type=row.source_type,
                    source_id=row.source_id,
                    source_line_id=row.source_line_id,
                    document_date=row.document_date,
                    occurred_at=row.occurred_at,
                    notes=row.notes,
                    created_at=row.created_at,
                )
            )
        return responses
