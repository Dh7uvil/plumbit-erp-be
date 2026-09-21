"""Persistence for invoice write-offs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.erp.accounting.write_offs.models import InvoiceWriteOff


class InvoiceWriteOffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, tenant_id: UUID, values: dict[str, object]) -> InvoiceWriteOff:
        row = InvoiceWriteOff(tenant_id=tenant_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(
        self,
        tenant_id: UUID,
        write_off_id: UUID,
        *,
        for_update: bool = False,
    ) -> InvoiceWriteOff | None:
        stmt = select(InvoiceWriteOff).where(
            InvoiceWriteOff.tenant_id == tenant_id,
            InvoiceWriteOff.id == write_off_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_live_for_invoice(
        self, tenant_id: UUID, *, document_kind: str, invoice_id: UUID
    ) -> bool:
        stmt = (
            select(InvoiceWriteOff.id)
            .where(
                InvoiceWriteOff.tenant_id == tenant_id,
                InvoiceWriteOff.document_kind == document_kind,
                InvoiceWriteOff.invoice_id == invoice_id,
                InvoiceWriteOff.reversed_at.is_(None),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None
