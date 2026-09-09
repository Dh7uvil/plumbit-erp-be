"""Proforma invoice queries."""

import builtins
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import ProformaInvoiceStatus
from app.erp.proforma_invoices.models import (
    ProformaInvoice,
    ProformaInvoiceLine,
    ProformaInvoiceMilestone,
)

_LIVE_STATUSES = frozenset(
    {
        ProformaInvoiceStatus.DRAFT.value,
        ProformaInvoiceStatus.SENT.value,
        ProformaInvoiceStatus.CONFIRMED.value,
        ProformaInvoiceStatus.CONVERTED.value,
        ProformaInvoiceStatus.EXPIRED.value,
    }
)


class ProformaInvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            ProformaInvoice,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "proforma_date",
                    "status",
                    "grand_total",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "customer_id",
                    "branch_id",
                    "currency_id",
                    "source_quotation_id",
                }
            ),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_children(self) -> tuple[Any, Any]:
        return (
            selectinload(ProformaInvoice.lines),
            selectinload(ProformaInvoice.milestones),
        )

    def _effective_status_criteria(
        self, status: str | None, today: date
    ) -> tuple[dict[str, object], list[ColumnElement[bool]]]:
        extra: list[ColumnElement[bool]] = []
        filters: dict[str, object] = {}
        if status == ProformaInvoiceStatus.EXPIRED.value:
            extra.extend(
                [
                    ProformaInvoice.status == ProformaInvoiceStatus.SENT.value,
                    ProformaInvoice.valid_until.is_not(None),
                    ProformaInvoice.valid_until < today,
                ]
            )
        elif status == ProformaInvoiceStatus.SENT.value:
            extra.extend(
                [
                    ProformaInvoice.status == ProformaInvoiceStatus.SENT.value,
                    or_(
                        ProformaInvoice.valid_until.is_(None),
                        ProformaInvoice.valid_until >= today,
                    ),
                ]
            )
        elif status is not None:
            filters["status"] = status
        return filters, extra

    async def get(
        self, tenant_id: UUID, proforma_invoice_id: UUID, *, for_update: bool = False
    ) -> ProformaInvoice | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(ProformaInvoice.id == proforma_invoice_id)
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
        status: str | None = None,
        today: date | None = None,
    ) -> tuple[Sequence[ProformaInvoice], int]:
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
            .where(ProformaInvoice.id.in_(ids))
            .options(*self._with_children())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> ProformaInvoice:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, proforma_invoice_id: UUID, values: Mapping[str, object]
    ) -> ProformaInvoice | None:
        return await self._repo.update(tenant_id, proforma_invoice_id, values)

    async def soft_delete(
        self, tenant_id: UUID, proforma_invoice_id: UUID
    ) -> ProformaInvoice | None:
        return await self._repo.soft_delete(tenant_id, proforma_invoice_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[ProformaInvoiceLine]:
        await self.session.execute(
            delete(ProformaInvoiceLine).where(
                ProformaInvoiceLine.tenant_id == tenant_id,
                ProformaInvoiceLine.proforma_invoice_id == proforma_invoice_id,
            )
        )
        created: builtins.list[ProformaInvoiceLine] = []
        for values in lines:
            row = ProformaInvoiceLine(tenant_id=tenant_id, proforma_invoice_id=proforma_invoice_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    async def replace_milestones(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        milestones: Sequence[Mapping[str, object]],
    ) -> builtins.list[ProformaInvoiceMilestone]:
        await self.session.execute(
            delete(ProformaInvoiceMilestone).where(
                ProformaInvoiceMilestone.tenant_id == tenant_id,
                ProformaInvoiceMilestone.proforma_invoice_id == proforma_invoice_id,
            )
        )
        created: builtins.list[ProformaInvoiceMilestone] = []
        for values in milestones:
            row = ProformaInvoiceMilestone(
                tenant_id=tenant_id, proforma_invoice_id=proforma_invoice_id
            )
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    async def has_live_for_quotation(self, tenant_id: UUID, quotation_id: UUID) -> bool:
        statement = (
            select(ProformaInvoice.id)
            .where(
                ProformaInvoice.tenant_id == tenant_id,
                ProformaInvoice.source_quotation_id == quotation_id,
                ProformaInvoice.deleted_at.is_(None),
                ProformaInvoice.status.in_(_LIVE_STATUSES),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None
