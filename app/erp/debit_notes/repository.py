"""Debit note queries."""

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
from app.erp.debit_notes.models import DebitNote, DebitNoteLine


class DebitNoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            DebitNote,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "debit_note_date",
                    "status",
                    "grand_total",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "supplier_id",
                    "purchase_invoice_id",
                    "purchase_return_id",
                    "currency_id",
                }
            ),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_children(self) -> tuple[Any, ...]:
        return (selectinload(DebitNote.lines),)

    async def get(
        self, tenant_id: UUID, debit_note_id: UUID, *, for_update: bool = False
    ) -> DebitNote | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(DebitNote.id == debit_note_id)
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
    ) -> tuple[Sequence[DebitNote], int]:
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
            .where(DebitNote.id.in_(ids))
            .options(*self._with_children())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> DebitNote:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, debit_note_id: UUID, values: Mapping[str, object]
    ) -> DebitNote | None:
        return await self._repo.update(tenant_id, debit_note_id, values)

    async def soft_delete(self, tenant_id: UUID, debit_note_id: UUID) -> DebitNote | None:
        return await self._repo.soft_delete(tenant_id, debit_note_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        debit_note_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[DebitNoteLine]:
        await self.session.execute(
            delete(DebitNoteLine).where(
                DebitNoteLine.tenant_id == tenant_id,
                DebitNoteLine.debit_note_id == debit_note_id,
            )
        )
        created: builtins.list[DebitNoteLine] = []
        for values in lines:
            row = DebitNoteLine(tenant_id=tenant_id, debit_note_id=debit_note_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    async def has_live_for_purchase_invoice(
        self, tenant_id: UUID, purchase_invoice_id: UUID
    ) -> bool:
        statement = (
            select(DebitNote.id)
            .where(
                DebitNote.tenant_id == tenant_id,
                DebitNote.purchase_invoice_id == purchase_invoice_id,
                DebitNote.deleted_at.is_(None),
                DebitNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def has_live_for_purchase_return(
        self, tenant_id: UUID, purchase_return_id: UUID
    ) -> bool:
        statement = (
            select(DebitNote.id)
            .where(
                DebitNote.tenant_id == tenant_id,
                DebitNote.purchase_return_id == purchase_return_id,
                DebitNote.deleted_at.is_(None),
                DebitNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def list_for_purchase_return(
        self, tenant_id: UUID, purchase_return_id: UUID
    ) -> builtins.list[DebitNote]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                DebitNote.purchase_return_id == purchase_return_id,
                DebitNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(DebitNote.debit_note_date, DebitNote.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_purchase_invoice(
        self, tenant_id: UUID, purchase_invoice_id: UUID
    ) -> builtins.list[DebitNote]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                DebitNote.purchase_invoice_id == purchase_invoice_id,
                DebitNote.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(DebitNote.debit_note_date, DebitNote.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())
