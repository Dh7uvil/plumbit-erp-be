"""Purchase order queries."""

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
from app.erp.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

_SORT_FIELDS = frozenset(
    {
        "created_at",
        "updated_at",
        "document_number",
        "order_date",
        "status",
        "grand_total",
    }
)
_FILTER_FIELDS = frozenset(
    {
        "status",
        "receipt_status",
        "billing_status",
        "supplier_id",
        "branch_id",
        "warehouse_id",
        "currency_id",
    }
)


class PurchaseOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            PurchaseOrder,
            allowed_sort_fields=_SORT_FIELDS,
            allowed_filter_fields=_FILTER_FIELDS,
            search_fields=frozenset({"document_number", "reference_number", "notes"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(PurchaseOrder.lines)

    async def get(
        self, tenant_id: UUID, purchase_order_id: UUID, *, for_update: bool = False
    ) -> PurchaseOrder | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(PurchaseOrder.id == purchase_order_id)
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
    ) -> tuple[Sequence[PurchaseOrder], int]:
        rows, total = await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = (
            self._repo.base_query(tenant_id)
            .where(PurchaseOrder.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> PurchaseOrder:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, purchase_order_id: UUID, values: Mapping[str, object]
    ) -> PurchaseOrder | None:
        return await self._repo.update(tenant_id, purchase_order_id, values)

    async def soft_delete(self, tenant_id: UUID, purchase_order_id: UUID) -> PurchaseOrder | None:
        return await self._repo.soft_delete(tenant_id, purchase_order_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[PurchaseOrderLine]:
        await self.session.execute(
            delete(PurchaseOrderLine).where(
                PurchaseOrderLine.tenant_id == tenant_id,
                PurchaseOrderLine.purchase_order_id == purchase_order_id,
            )
        )
        created: builtins.list[PurchaseOrderLine] = []
        for values in lines:
            row = PurchaseOrderLine(tenant_id=tenant_id, purchase_order_id=purchase_order_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
