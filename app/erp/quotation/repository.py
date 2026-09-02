"""Quotation queries."""

import builtins
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import QuotationStatus
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

    def _effective_status_criteria(
        self, status: str | None, today: date
    ) -> tuple[dict[str, object], list[ColumnElement[bool]]]:
        """Map effective SENT/EXPIRED onto stored SENT + valid_until."""

        extra: list[ColumnElement[bool]] = []
        filters: dict[str, object] = {}
        if status == QuotationStatus.EXPIRED.value:
            extra.extend(
                [
                    Quotation.status == QuotationStatus.SENT.value,
                    Quotation.valid_until.is_not(None),
                    Quotation.valid_until < today,
                ]
            )
        elif status == QuotationStatus.SENT.value:
            extra.extend(
                [
                    Quotation.status == QuotationStatus.SENT.value,
                    or_(Quotation.valid_until.is_(None), Quotation.valid_until >= today),
                ]
            )
        elif status is not None:
            filters["status"] = status
        return filters, extra

    async def get(
        self, tenant_id: UUID, quotation_id: UUID, *, for_update: bool = False
    ) -> Quotation | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(Quotation.id == quotation_id)
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
        status: str | None = None,
        today: date | None = None,
    ) -> tuple[Sequence[Quotation], int]:
        merged: dict[str, object] = dict(filters or {})
        extra: list[ColumnElement[bool]] = []
        effective_status = status if status is not None else merged.pop("status", None)
        if isinstance(effective_status, str) and today is not None:
            status_filters, extra = self._effective_status_criteria(effective_status, today)
            merged.update(status_filters)
        elif isinstance(effective_status, str):
            merged["status"] = effective_status
        rows, total = await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=merged or None,
            extra_criteria=extra or None,
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = (
            self._repo.base_query(tenant_id)
            .where(Quotation.id.in_(ids))
            .options(self._with_lines())
        )
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
