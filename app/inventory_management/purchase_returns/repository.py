"""Purchase return queries."""

import builtins
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import StockDocumentStatus
from app.inventory_management.purchase_returns.models import PurchaseReturn, PurchaseReturnLine

_ZERO = Decimal("0")


class PurchaseReturnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            PurchaseReturn,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "document_date", "status"}
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "goods_receipt_id",
                    "purchase_order_id",
                    "supplier_id",
                    "warehouse_id",
                }
            ),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(PurchaseReturn.lines)

    async def get(
        self, tenant_id: UUID, return_id: UUID, *, for_update: bool = False
    ) -> PurchaseReturn | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(PurchaseReturn.id == return_id)
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
    ) -> tuple[Sequence[PurchaseReturn], int]:
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
            .where(PurchaseReturn.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def list_for_purchase_order(
        self, tenant_id: UUID, purchase_order_id: UUID
    ) -> Sequence[PurchaseReturn]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(PurchaseReturn.purchase_order_id == purchase_order_id)
            .options(self._with_lines())
            .order_by(PurchaseReturn.document_date, PurchaseReturn.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_for_goods_receipt(
        self, tenant_id: UUID, goods_receipt_id: UUID
    ) -> Sequence[PurchaseReturn]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(PurchaseReturn.goods_receipt_id == goods_receipt_id)
            .options(self._with_lines())
            .order_by(PurchaseReturn.document_date, PurchaseReturn.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def posted_qty_for_goods_receipt_line(
        self, tenant_id: UUID, goods_receipt_line_id: UUID, *, exclude_return_id: UUID | None = None
    ) -> Decimal:
        statement = (
            select(func.coalesce(func.sum(PurchaseReturnLine.quantity), _ZERO))
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnLine.purchase_return_id)
            .where(
                PurchaseReturnLine.tenant_id == tenant_id,
                PurchaseReturnLine.goods_receipt_line_id == goods_receipt_line_id,
                PurchaseReturn.tenant_id == tenant_id,
                PurchaseReturn.deleted_at.is_(None),
                PurchaseReturn.status == StockDocumentStatus.POSTED.value,
            )
        )
        if exclude_return_id is not None:
            statement = statement.where(PurchaseReturn.id != exclude_return_id)
        result = await self.session.execute(statement)
        value = result.scalar_one()
        return value if isinstance(value, Decimal) else Decimal(str(value or 0))

    async def has_live_for_goods_receipt(self, tenant_id: UUID, goods_receipt_id: UUID) -> bool:
        statement = (
            select(PurchaseReturn.id)
            .where(
                PurchaseReturn.tenant_id == tenant_id,
                PurchaseReturn.goods_receipt_id == goods_receipt_id,
                PurchaseReturn.deleted_at.is_(None),
                PurchaseReturn.status != StockDocumentStatus.CANCELLED.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> PurchaseReturn:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, return_id: UUID, values: Mapping[str, object]
    ) -> PurchaseReturn | None:
        return await self._repo.update(tenant_id, return_id, values)

    async def soft_delete(self, tenant_id: UUID, return_id: UUID) -> PurchaseReturn | None:
        return await self._repo.soft_delete(tenant_id, return_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        return_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[PurchaseReturnLine]:
        await self.session.execute(
            delete(PurchaseReturnLine).where(
                PurchaseReturnLine.tenant_id == tenant_id,
                PurchaseReturnLine.purchase_return_id == return_id,
            )
        )
        created: builtins.list[PurchaseReturnLine] = []
        for values in lines:
            row = PurchaseReturnLine(tenant_id=tenant_id, purchase_return_id=return_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
