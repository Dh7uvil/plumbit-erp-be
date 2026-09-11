"""Landed cost queries."""

import builtins
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import StockDocumentStatus
from app.erp.landed_costs.models import LandedCost, LandedCostAllocation, LandedCostCharge

_ZERO = Decimal("0")


class LandedCostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            LandedCost,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "document_date", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "shipment_id", "branch_id"}),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_children(self) -> tuple[Any, ...]:
        return (selectinload(LandedCost.charges), selectinload(LandedCost.allocations))

    async def get(
        self, tenant_id: UUID, landed_cost_id: UUID, *, for_update: bool = False
    ) -> LandedCost | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(LandedCost.id == landed_cost_id)
            .options(*self._with_children())
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
    ) -> tuple[Sequence[LandedCost], int]:
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
            .where(LandedCost.id.in_(ids))
            .options(*self._with_children())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    def has_goods_receipt_clause(self, goods_receipt_id: UUID) -> ColumnElement[bool]:
        return LandedCost.id.in_(
            select(LandedCostAllocation.landed_cost_id).where(
                LandedCostAllocation.tenant_id == LandedCost.tenant_id,
                LandedCostAllocation.goods_receipt_id == goods_receipt_id,
            )
        )

    def has_purchase_invoice_clause(self, purchase_invoice_id: UUID) -> ColumnElement[bool]:
        return LandedCost.id.in_(
            select(LandedCostCharge.landed_cost_id).where(
                LandedCostCharge.tenant_id == LandedCost.tenant_id,
                LandedCostCharge.purchase_invoice_id == purchase_invoice_id,
            )
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> LandedCost:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, landed_cost_id: UUID, values: Mapping[str, object]
    ) -> LandedCost | None:
        return await self._repo.update(tenant_id, landed_cost_id, values)

    async def soft_delete(self, tenant_id: UUID, landed_cost_id: UUID) -> LandedCost | None:
        return await self._repo.soft_delete(tenant_id, landed_cost_id)

    async def replace_children(
        self,
        tenant_id: UUID,
        landed_cost_id: UUID,
        *,
        charges: Sequence[Mapping[str, object]],
        allocations: Sequence[Mapping[str, object]],
    ) -> tuple[builtins.list[LandedCostCharge], builtins.list[LandedCostAllocation]]:
        await self.session.execute(
            delete(LandedCostCharge).where(
                LandedCostCharge.tenant_id == tenant_id,
                LandedCostCharge.landed_cost_id == landed_cost_id,
            )
        )
        await self.session.execute(
            delete(LandedCostAllocation).where(
                LandedCostAllocation.tenant_id == tenant_id,
                LandedCostAllocation.landed_cost_id == landed_cost_id,
            )
        )
        created_charges: builtins.list[LandedCostCharge] = []
        for values in charges:
            row = LandedCostCharge(tenant_id=tenant_id, landed_cost_id=landed_cost_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created_charges.append(row)
        created_allocations: builtins.list[LandedCostAllocation] = []
        for values in allocations:
            row = LandedCostAllocation(tenant_id=tenant_id, landed_cost_id=landed_cost_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created_allocations.append(row)
        await self.session.flush()
        return created_charges, created_allocations

    async def list_for_goods_receipt(
        self, tenant_id: UUID, goods_receipt_id: UUID
    ) -> Sequence[LandedCost]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(self.has_goods_receipt_clause(goods_receipt_id))
            .options(*self._with_children())
            .order_by(LandedCost.document_date, LandedCost.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_for_purchase_invoice(
        self, tenant_id: UUID, purchase_invoice_id: UUID
    ) -> Sequence[LandedCost]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(self.has_purchase_invoice_clause(purchase_invoice_id))
            .options(*self._with_children())
            .order_by(LandedCost.document_date, LandedCost.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def posted_allocated_by_bill_line(
        self,
        tenant_id: UUID,
        line_ids: Sequence[UUID],
        *,
        exclude_landed_cost_id: UUID | None = None,
    ) -> dict[UUID, Decimal]:
        if not line_ids:
            return {}
        statement = (
            select(
                LandedCostCharge.purchase_invoice_line_id,
                func.coalesce(func.sum(LandedCostCharge.amount), _ZERO),
            )
            .join(LandedCost, LandedCost.id == LandedCostCharge.landed_cost_id)
            .where(
                LandedCostCharge.tenant_id == tenant_id,
                LandedCost.tenant_id == tenant_id,
                LandedCost.deleted_at.is_(None),
                LandedCost.status == StockDocumentStatus.POSTED.value,
                LandedCostCharge.purchase_invoice_line_id.in_(list(line_ids)),
            )
            .group_by(LandedCostCharge.purchase_invoice_line_id)
        )
        if exclude_landed_cost_id is not None:
            statement = statement.where(LandedCost.id != exclude_landed_cost_id)
        rows = (await self.session.execute(statement)).all()
        return {
            line_id: value if isinstance(value, Decimal) else Decimal(str(value or 0))
            for line_id, value in rows
        }

    async def later_posted_touching_lines(
        self,
        tenant_id: UUID,
        *,
        goods_receipt_line_ids: Sequence[UUID],
        document_date: date,
        created_at,
        exclude_id: UUID,
    ) -> Sequence[LandedCost]:
        if not goods_receipt_line_ids:
            return []
        statement = (
            select(LandedCost)
            .join(LandedCostAllocation, LandedCostAllocation.landed_cost_id == LandedCost.id)
            .where(
                LandedCost.tenant_id == tenant_id,
                LandedCost.deleted_at.is_(None),
                LandedCost.status == StockDocumentStatus.POSTED.value,
                LandedCost.id != exclude_id,
                LandedCostAllocation.goods_receipt_line_id.in_(list(goods_receipt_line_ids)),
                or_(
                    LandedCost.document_date > document_date,
                    and_(
                        LandedCost.document_date == document_date,
                        LandedCost.created_at > created_at,
                    ),
                ),
            )
            .distinct()
        )
        result = await self.session.execute(statement)
        return result.scalars().all()
