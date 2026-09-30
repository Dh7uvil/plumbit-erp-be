"""GRN charge adjustment queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.goods_receipt_charge_adjustments.models import (
    GoodsReceiptChargeAdjustment,
    GoodsReceiptChargeAdjustmentLine,
)


class GoodsReceiptChargeAdjustmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            GoodsReceiptChargeAdjustment,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "document_date", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "goods_receipt_id", "branch_id"}),
            search_fields=frozenset({"document_number", "notes", "cancel_reason"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(GoodsReceiptChargeAdjustment.lines)

    async def get(
        self, tenant_id: UUID, adjustment_id: UUID, *, for_update: bool = False
    ) -> GoodsReceiptChargeAdjustment | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(GoodsReceiptChargeAdjustment.id == adjustment_id)
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
        extra_criteria: Sequence[Any] | None = None,
    ) -> tuple[Sequence[GoodsReceiptChargeAdjustment], int]:
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
            .where(GoodsReceiptChargeAdjustment.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(
        self, tenant_id: UUID, values: Mapping[str, object]
    ) -> GoodsReceiptChargeAdjustment:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, adjustment_id: UUID, values: Mapping[str, object]
    ) -> GoodsReceiptChargeAdjustment | None:
        return await self._repo.update(tenant_id, adjustment_id, values)

    async def soft_delete(
        self, tenant_id: UUID, adjustment_id: UUID
    ) -> GoodsReceiptChargeAdjustment | None:
        return await self._repo.soft_delete(tenant_id, adjustment_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[GoodsReceiptChargeAdjustmentLine]:
        await self.session.execute(
            delete(GoodsReceiptChargeAdjustmentLine).where(
                GoodsReceiptChargeAdjustmentLine.tenant_id == tenant_id,
                GoodsReceiptChargeAdjustmentLine.goods_receipt_charge_adjustment_id
                == adjustment_id,
            )
        )
        created: builtins.list[GoodsReceiptChargeAdjustmentLine] = []
        for values in lines:
            row = GoodsReceiptChargeAdjustmentLine(
                tenant_id=tenant_id,
                goods_receipt_charge_adjustment_id=adjustment_id,
            )
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
