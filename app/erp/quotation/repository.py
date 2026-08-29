"""Quotation queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.quotation.models import Quotation, QuotationLine


class QuotationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Quotation,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "quote_number",
                    "quote_date",
                    "status",
                    "grand_total",
                }
            ),
            allowed_filter_fields=frozenset({"status", "customer_id", "branch_id", "currency_id"}),
            search_fields=frozenset({"quote_number", "notes"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(Quotation.lines)

    async def get(self, tenant_id: UUID, quotation_id: UUID) -> Quotation | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(Quotation.id == quotation_id)
            .options(self._with_lines())
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
    ) -> tuple[Sequence[Quotation], int]:
        rows, total = await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = select(Quotation).where(Quotation.id.in_(ids)).options(self._with_lines())
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Quotation:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, quotation_id: UUID, values: Mapping[str, object]
    ) -> Quotation | None:
        return await self._repo.update(tenant_id, quotation_id, values)

    async def soft_delete(self, tenant_id: UUID, quotation_id: UUID) -> Quotation | None:
        return await self._repo.soft_delete(tenant_id, quotation_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[QuotationLine]:
        await self.session.execute(
            delete(QuotationLine).where(
                QuotationLine.tenant_id == tenant_id,
                QuotationLine.quotation_id == quotation_id,
            )
        )
        created: builtins.list[QuotationLine] = []
        for values in lines:
            row = QuotationLine(tenant_id=tenant_id, quotation_id=quotation_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
