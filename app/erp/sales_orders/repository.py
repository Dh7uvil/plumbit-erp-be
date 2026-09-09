"""Sales order queries."""

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
from app.erp.sales_orders.models import SalesOrder, SalesOrderLine

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
        "fulfillment_status",
        "billing_status",
        "customer_id",
        "branch_id",
        "warehouse_id",
        "currency_id",
        "salesperson_id",
        "source_quotation_id",
        "source_proforma_invoice_id",
    }
)


class SalesOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            SalesOrder,
            allowed_sort_fields=_SORT_FIELDS,
            allowed_filter_fields=_FILTER_FIELDS,
            search_fields=frozenset({"document_number", "reference_number", "notes"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(SalesOrder.lines)

    async def get(
        self, tenant_id: UUID, sales_order_id: UUID, *, for_update: bool = False
    ) -> SalesOrder | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(SalesOrder.id == sales_order_id)
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
    ) -> tuple[Sequence[SalesOrder], int]:
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
            .where(SalesOrder.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> SalesOrder:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, sales_order_id: UUID, values: Mapping[str, object]
    ) -> SalesOrder | None:
        return await self._repo.update(tenant_id, sales_order_id, values)

    async def soft_delete(self, tenant_id: UUID, sales_order_id: UUID) -> SalesOrder | None:
        return await self._repo.soft_delete(tenant_id, sales_order_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[SalesOrderLine]:
        await self.session.execute(
            delete(SalesOrderLine).where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.sales_order_id == sales_order_id,
            )
        )
        created: builtins.list[SalesOrderLine] = []
        for values in lines:
            row = SalesOrderLine(tenant_id=tenant_id, sales_order_id=sales_order_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    async def find_by_customer_po(
        self,
        tenant_id: UUID,
        *,
        customer_id: UUID,
        customer_po_number: str,
        exclude_id: UUID | None = None,
    ) -> builtins.list[SalesOrder]:
        statement = self._repo.base_query(tenant_id).where(
            SalesOrder.customer_id == customer_id,
            SalesOrder.customer_po_number == customer_po_number,
        )
        if exclude_id is not None:
            statement = statement.where(SalesOrder.id != exclude_id)
        statement = statement.order_by(SalesOrder.created_at.desc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())
