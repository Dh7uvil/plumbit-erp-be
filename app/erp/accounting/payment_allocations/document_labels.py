"""Resolve open-item document numbers for allocation history (including settled rows)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OpenItemType


async def allocation_item_document_number(
    session: AsyncSession,
    tenant_id: UUID,
    item_type: OpenItemType,
    item_id: UUID,
) -> str | None:
    if item_type == OpenItemType.SALES_INVOICE:
        from app.erp.sales_invoices.repository import SalesInvoiceRepository

        row = await SalesInvoiceRepository(session).get(tenant_id, item_id)
        return row.document_number if row is not None else None
    if item_type == OpenItemType.CREDIT_NOTE:
        from app.erp.credit_notes.repository import CreditNoteRepository

        row = await CreditNoteRepository(session).get(tenant_id, item_id)
        return row.document_number if row is not None else None
    if item_type == OpenItemType.PURCHASE_INVOICE:
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository

        row = await PurchaseInvoiceRepository(session).get(tenant_id, item_id)
        return row.document_number if row is not None else None
    if item_type == OpenItemType.DEBIT_NOTE:
        from app.erp.debit_notes.repository import DebitNoteRepository

        row = await DebitNoteRepository(session).get(tenant_id, item_id)
        return row.document_number if row is not None else None
    if item_type in {OpenItemType.OPENING_AR, OpenItemType.OPENING_AP}:
        from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine

        line = await session.get(JournalEntryLine, item_id)
        if line is None or line.tenant_id != tenant_id:
            return None
        entry = await session.get(JournalEntry, line.journal_entry_id)
        if entry is None or entry.tenant_id != tenant_id:
            return None
        return entry.reference or entry.document_number
    return None
