"""Sales invoice queries."""

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
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine


class SalesInvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            SalesInvoice,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "invoice_date",
                    "status",
                    "grand_total",
                    "due_date",
                    "payment_status",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "customer_id",
                    "sales_order_id",
                    "source_quotation_id",
                    "source_proforma_invoice_id",
                    "branch_id",
                    "currency_id",
                    "payment_status",
                }
            ),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_children(self) -> tuple[Any, ...]:
        return (selectinload(SalesInvoice.lines),)

    async def get(
        self, tenant_id: UUID, sales_invoice_id: UUID, *, for_update: bool = False
    ) -> SalesInvoice | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(SalesInvoice.id == sales_invoice_id)
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
    ) -> tuple[Sequence[SalesInvoice], int]:
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
            .where(SalesInvoice.id.in_(ids))
            .options(*self._with_children())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def list_for_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> builtins.list[SalesInvoice]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                SalesInvoice.sales_order_id == sales_order_id,
                SalesInvoice.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(SalesInvoice.invoice_date, SalesInvoice.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_quotation(
        self, tenant_id: UUID, quotation_id: UUID
    ) -> builtins.list[SalesInvoice]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                SalesInvoice.source_quotation_id == quotation_id,
                SalesInvoice.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(SalesInvoice.invoice_date, SalesInvoice.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_proforma_invoice(
        self, tenant_id: UUID, proforma_invoice_id: UUID
    ) -> builtins.list[SalesInvoice]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                SalesInvoice.source_proforma_invoice_id == proforma_invoice_id,
                SalesInvoice.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(SalesInvoice.invoice_date, SalesInvoice.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_delivery_note(
        self, tenant_id: UUID, delivery_note_id: UUID
    ) -> builtins.list[SalesInvoice]:
        statement = (
            self._repo.base_query(tenant_id)
            .join(SalesInvoiceLine, SalesInvoiceLine.sales_invoice_id == SalesInvoice.id)
            .where(
                SalesInvoiceLine.delivery_note_id == delivery_note_id,
                SalesInvoice.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .options(*self._with_children())
            .order_by(SalesInvoice.invoice_date, SalesInvoice.created_at)
            .distinct()
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> SalesInvoice:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, sales_invoice_id: UUID, values: Mapping[str, object]
    ) -> SalesInvoice | None:
        return await self._repo.update(tenant_id, sales_invoice_id, values)

    async def soft_delete(self, tenant_id: UUID, sales_invoice_id: UUID) -> SalesInvoice | None:
        return await self._repo.soft_delete(tenant_id, sales_invoice_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        sales_invoice_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[SalesInvoiceLine]:
        await self.session.execute(
            delete(SalesInvoiceLine).where(
                SalesInvoiceLine.tenant_id == tenant_id,
                SalesInvoiceLine.sales_invoice_id == sales_invoice_id,
            )
        )
        created: builtins.list[SalesInvoiceLine] = []
        for values in lines:
            row = SalesInvoiceLine(tenant_id=tenant_id, sales_invoice_id=sales_invoice_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    async def has_unposted(self, tenant_id: UUID) -> bool:
        statement = (
            select(SalesInvoice.id)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.DRAFT.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def has_live_for_delivery_note(self, tenant_id: UUID, delivery_note_id: UUID) -> bool:
        statement = (
            select(SalesInvoiceLine.id)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoiceLine.tenant_id == tenant_id,
                SalesInvoiceLine.delivery_note_id == delivery_note_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None
