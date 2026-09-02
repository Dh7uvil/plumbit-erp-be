"""Stock adjustment queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.stock_adjustments.models import (
    StockAdjustment,
    StockAdjustmentLine,
)


class StockAdjustmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            StockAdjustment,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "document_date", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "warehouse_id", "reason", "branch_id"}),
            search_fields=frozenset({"document_number", "reference", "notes"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(StockAdjustment.lines)

    def has_product_clause(self, product_id: UUID) -> ColumnElement[bool]:
        return exists().where(
            StockAdjustmentLine.stock_adjustment_id == StockAdjustment.id,
            StockAdjustmentLine.product_id == product_id,
            StockAdjustmentLine.tenant_id == StockAdjustment.tenant_id,
        )

    async def get(
        self, tenant_id: UUID, adjustment_id: UUID, *, for_update: bool = False
    ) -> StockAdjustment | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(StockAdjustment.id == adjustment_id)
            .options(self._with_lines())
        )
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
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[StockAdjustment], int]:
        rows, total = await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = (
            self._repo.base_query(tenant_id)
            .where(StockAdjustment.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> StockAdjustment:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, adjustment_id: UUID, values: Mapping[str, object]
    ) -> StockAdjustment | None:
        return await self._repo.update(tenant_id, adjustment_id, values)

    async def soft_delete(self, tenant_id: UUID, adjustment_id: UUID) -> StockAdjustment | None:
        return await self._repo.soft_delete(tenant_id, adjustment_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[StockAdjustmentLine]:
        await self.session.execute(
            delete(StockAdjustmentLine).where(
                StockAdjustmentLine.tenant_id == tenant_id,
                StockAdjustmentLine.stock_adjustment_id == adjustment_id,
            )
        )
        created: builtins.list[StockAdjustmentLine] = []
        for values in lines:
            row = StockAdjustmentLine(tenant_id=tenant_id, stock_adjustment_id=adjustment_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
