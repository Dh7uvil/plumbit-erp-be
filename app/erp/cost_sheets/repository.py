"""Cost sheet queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.cost_sheets.models import CostSheet, CostSheetCharge, CostSheetLine


class CostSheetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            CostSheet,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "document_date",
                    "status",
                    "sheet_type",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "sheet_type",
                    "shipment_id",
                    "purchase_order_id",
                    "supplier_id",
                    "customer_id",
                    "currency_id",
                }
            ),
            search_fields=frozenset({"document_number", "notes", "incoterm"}),
        )

    def _with_children(self) -> tuple[Any, ...]:
        return (selectinload(CostSheet.lines), selectinload(CostSheet.charges))

    async def get(
        self, tenant_id: UUID, cost_sheet_id: UUID, *, for_update: bool = False
    ) -> CostSheet | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(CostSheet.id == cost_sheet_id)
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
    ) -> tuple[Sequence[CostSheet], int]:
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
            .where(CostSheet.id.in_(ids))
            .options(*self._with_children())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> CostSheet:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, cost_sheet_id: UUID, values: Mapping[str, object]
    ) -> CostSheet | None:
        return await self._repo.update(tenant_id, cost_sheet_id, values)

    async def soft_delete(self, tenant_id: UUID, cost_sheet_id: UUID) -> CostSheet | None:
        return await self._repo.soft_delete(tenant_id, cost_sheet_id)

    async def replace_children(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        lines: Sequence[Mapping[str, object]],
        charges: Sequence[Mapping[str, object]],
    ) -> tuple[builtins.list[CostSheetLine], builtins.list[CostSheetCharge]]:
        await self.session.execute(
            delete(CostSheetLine).where(
                CostSheetLine.tenant_id == tenant_id,
                CostSheetLine.cost_sheet_id == cost_sheet_id,
            )
        )
        await self.session.execute(
            delete(CostSheetCharge).where(
                CostSheetCharge.tenant_id == tenant_id,
                CostSheetCharge.cost_sheet_id == cost_sheet_id,
            )
        )
        created_lines: builtins.list[CostSheetLine] = []
        for values in lines:
            line_row = CostSheetLine(tenant_id=tenant_id, cost_sheet_id=cost_sheet_id)
            for name, value in values.items():
                setattr(line_row, name, value)
            self.session.add(line_row)
            created_lines.append(line_row)
        created_charges: builtins.list[CostSheetCharge] = []
        for values in charges:
            charge_row = CostSheetCharge(tenant_id=tenant_id, cost_sheet_id=cost_sheet_id)
            for name, value in values.items():
                setattr(charge_row, name, value)
            self.session.add(charge_row)
            created_charges.append(charge_row)
        await self.session.flush()
        return created_lines, created_charges
