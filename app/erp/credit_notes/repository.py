"""Credit note queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import InvoiceDocumentStatus
from app.erp.credit_notes.models import CreditNote, CreditNoteLine


class CreditNoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            CreditNote,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "credit_note_date",
                    "status",
                    "grand_total",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "customer_id",
                    "sales_invoice_id",
                    "sales_return_id",
                    "currency_id",
                }
            ),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_children(self) -> tuple[Any, ...]:
        return (selectinload(CreditNote.lines),)

    async def get(
        self, tenant_id: UUID, credit_note_id: UUID, *, for_update: bool = False
    ) -> CreditNote | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(CreditNote.id == credit_note_id)
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
    ) -> tuple[Sequence[CreditNote], int]:
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
            .where(CreditNote.id.in_(ids))
            .options(*self._with_children())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> CreditNote:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, credit_note_id: UUID, values: Mapping[str, object]
    ) -> CreditNote | None:
        return await self._repo.update(tenant_id, credit_note_id, values)

    async def soft_delete(self, tenant_id: UUID, credit_note_id: UUID) -> CreditNote | None:
        return await self._repo.soft_delete(tenant_id, credit_note_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        credit_note_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[CreditNoteLine]:
        await self.session.execute(
            delete(CreditNoteLine).where(
                CreditNoteLine.tenant_id == tenant_id,
                CreditNoteLine.credit_note_id == credit_note_id,
            )
        )
        created: builtins.list[CreditNoteLine] = []
        for values in lines:
            row = CreditNoteLine(tenant_id=tenant_id, credit_note_id=credit_note_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    async def has_live_for_sales_invoice(self, tenant_id: UUID, sales_invoice_id: UUID) -> bool:
        statement = (
            select(CreditNote.id)
            .where(
                CreditNote.tenant_id == tenant_id,
                CreditNote.sales_invoice_id == sales_invoice_id,
                CreditNote.deleted_at.is_(None),
                CreditNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def list_for_sales_invoice(
        self, tenant_id: UUID, sales_invoice_id: UUID
    ) -> builtins.list[CreditNote]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                CreditNote.sales_invoice_id == sales_invoice_id,
                CreditNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(CreditNote.credit_note_date, CreditNote.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_sales_return(
        self, tenant_id: UUID, sales_return_id: UUID
    ) -> builtins.list[CreditNote]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                CreditNote.sales_return_id == sales_return_id,
                CreditNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(CreditNote.credit_note_date, CreditNote.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())
