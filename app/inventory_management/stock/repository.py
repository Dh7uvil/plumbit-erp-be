"""Stock balance and movement queries."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select, sql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.stock.models import StockBalance, StockMovement

_ZERO = Decimal("0")
_BALANCE_SORT = frozenset(
    {
        "created_at",
        "updated_at",
        "qty_on_hand",
        "qty_reserved",
        "qty_available",
        "last_movement_at",
    }
)
_MOVEMENT_SORT = frozenset({"created_at", "updated_at", "document_date", "occurred_at", "qty"})
_BALANCE_FILTERS = frozenset({"warehouse_id", "product_id"})
_MOVEMENT_FILTERS = frozenset(
    {"warehouse_id", "product_id", "movement_type", "source_type", "source_id"}
)


class StockBalanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _column(self, name: str) -> InstrumentedAttribute[Any]:
        column = getattr(StockBalance, name, None)
        if not isinstance(column, InstrumentedAttribute):
            raise TypeError(f"StockBalance has no mapped column {name!r}")
        return column

    def _available_expr(self) -> ColumnElement[Decimal]:
        return StockBalance.qty_on_hand - StockBalance.qty_reserved

    def _criteria(
        self,
        tenant_id: UUID,
        *,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [StockBalance.tenant_id == tenant_id]
        if filters:
            unknown = filters.keys() - _BALANCE_FILTERS
            if unknown:
                fields = ", ".join(sorted(unknown))
                raise ValueError(f"filter fields are not allowed: {fields}")
            for name, value in filters.items():
                criteria.append(self._column(name) == value)
        if extra_criteria:
            criteria.extend(extra_criteria)
        return criteria

    async def get(self, tenant_id: UUID, balance_id: UUID) -> StockBalance | None:
        statement = select(StockBalance).where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.id == balance_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_for_update(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> StockBalance | None:
        statement = (
            select(StockBalance)
            .where(
                StockBalance.tenant_id == tenant_id,
                StockBalance.warehouse_id == warehouse_id,
                StockBalance.product_id == product_id,
            )
            .with_for_update()
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[StockBalance], int]:
        criteria = self._criteria(tenant_id, filters=filters, extra_criteria=extra_criteria)
        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(StockBalance.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(StockBalance.created_at <= common_filter.date_to)
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in _BALANCE_SORT:
            raise ValueError(f"sort field is not allowed: {sort_by}")
        sort_column: Any
        if sort_by == "qty_available":
            sort_column = self._available_expr()
        else:
            sort_column = self._column(sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        statement = (
            select(StockBalance)
            .where(*criteria)
            .order_by(ordering)
            .offset(page.offset)
            .limit(page.page_size)
        )
        count_statement = select(func.count()).select_from(StockBalance).where(*criteria)
        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> StockBalance:
        entity = StockBalance(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(entity, name, value)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(
        self, tenant_id: UUID, balance_id: UUID, values: Mapping[str, object]
    ) -> StockBalance | None:
        entity = await self.get(tenant_id, balance_id)
        if entity is None:
            return None
        for name, value in values.items():
            setattr(entity, name, value)
        await self.session.flush()
        await self.session.refresh(entity, attribute_names=["updated_at"])
        return entity

    async def has_nonzero_balance(self, tenant_id: UUID, product_id: UUID) -> bool:
        statement = (
            select(StockBalance.id)
            .where(
                StockBalance.tenant_id == tenant_id,
                StockBalance.product_id == product_id,
                or_(
                    StockBalance.qty_on_hand != _ZERO,
                    StockBalance.qty_reserved != _ZERO,
                    StockBalance.qty_incoming != _ZERO,
                    StockBalance.qty_outgoing != _ZERO,
                    StockBalance.qty_in_transit != _ZERO,
                ),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    def below_reorder_clause(self) -> ColumnElement[bool]:
        return sql.and_(
            StockBalance.reorder_level.is_not(None),
            StockBalance.qty_on_hand < StockBalance.reorder_level,
        )

    def negative_only_clause(self) -> ColumnElement[bool]:
        return StockBalance.qty_on_hand < _ZERO


class StockMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _column(self, name: str) -> InstrumentedAttribute[Any]:
        column = getattr(StockMovement, name, None)
        if not isinstance(column, InstrumentedAttribute):
            raise TypeError(f"StockMovement has no mapped column {name!r}")
        return column

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> StockMovement:
        entity = StockMovement(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(entity, name, value)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[StockMovement], int]:
        criteria: list[ColumnElement[bool]] = [StockMovement.tenant_id == tenant_id]
        if filters:
            unknown = filters.keys() - _MOVEMENT_FILTERS
            if unknown:
                fields = ", ".join(sorted(unknown))
                raise ValueError(f"filter fields are not allowed: {fields}")
            for name, value in filters.items():
                criteria.append(self._column(name) == value)
        if extra_criteria:
            criteria.extend(extra_criteria)
        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(StockMovement.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(StockMovement.created_at <= common_filter.date_to)
        sort_by = common_filter.sort_by if common_filter else "occurred_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in _MOVEMENT_SORT:
            raise ValueError(f"sort field is not allowed: {sort_by}")
        sort_column = self._column(sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        statement: Select[tuple[StockMovement]] = (
            select(StockMovement)
            .where(*criteria)
            .order_by(ordering)
            .offset(page.offset)
            .limit(page.page_size)
        )
        count_statement = select(func.count()).select_from(StockMovement).where(*criteria)
        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def has_movements(self, tenant_id: UUID, product_id: UUID) -> bool:
        statement = (
            select(StockMovement.id)
            .where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.product_id == product_id,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None
