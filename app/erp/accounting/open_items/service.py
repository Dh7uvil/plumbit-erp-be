"""AR/AP open-item set used by allocation pickers, aging, and credit exposure."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import InvoiceDocumentStatus, JournalEntryStatus, OpenItemType, PartyType
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.ledger.posting import SOURCE_OPENING_BALANCE
from app.erp.accounting.open_items.repository import PaymentAllocationRepository
from app.erp.accounting.open_items.schemas import OpenItemRow
from app.erp.credit_notes.models import CreditNote
from app.erp.customer_payments.models import CustomerPayment
from app.erp.debit_notes.models import DebitNote
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.supplier_payments.models import SupplierPayment

_ZERO = Decimal("0")


class OpenItemsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.allocations = PaymentAllocationRepository(session)

    async def list_ar_open_items(self, tenant_id: UUID, customer_id: UUID) -> list[OpenItemRow]:
        rows: list[OpenItemRow] = []
        rows.extend(await self._sales_invoices(tenant_id, customer_id))
        rows.extend(await self._opening_lines(tenant_id, customer_id, PartyType.CUSTOMER))
        rows.extend(await self._customer_advances(tenant_id, customer_id))
        rows.extend(await self._unapplied_credit_notes(tenant_id, customer_id))
        rows.sort(key=lambda item: (item.document_date, item.document_number))
        return rows

    async def list_ap_open_items(self, tenant_id: UUID, supplier_id: UUID) -> list[OpenItemRow]:
        rows: list[OpenItemRow] = []
        rows.extend(await self._purchase_invoices(tenant_id, supplier_id))
        rows.extend(await self._opening_lines(tenant_id, supplier_id, PartyType.SUPPLIER))
        rows.extend(await self._supplier_advances(tenant_id, supplier_id))
        rows.extend(await self._unapplied_debit_notes(tenant_id, supplier_id))
        rows.sort(key=lambda item: (item.document_date, item.document_number))
        return rows

    async def _sales_invoices(self, tenant_id: UUID, customer_id: UUID) -> list[OpenItemRow]:
        statement = select(SalesInvoice).where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
            SalesInvoice.balance_due > _ZERO,
        )
        invoices = list((await self.session.execute(statement)).scalars().all())
        return [
            OpenItemRow(
                item_type=OpenItemType.SALES_INVOICE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.invoice_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=row.balance_due,
                is_debit=True,
                exchange_rate=row.exchange_rate,
            )
            for row in invoices
        ]

    async def _purchase_invoices(self, tenant_id: UUID, supplier_id: UUID) -> list[OpenItemRow]:
        statement = select(PurchaseInvoice).where(
            PurchaseInvoice.tenant_id == tenant_id,
            PurchaseInvoice.supplier_id == supplier_id,
            PurchaseInvoice.deleted_at.is_(None),
            PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
            PurchaseInvoice.balance_due > _ZERO,
        )
        invoices = list((await self.session.execute(statement)).scalars().all())
        return [
            OpenItemRow(
                item_type=OpenItemType.PURCHASE_INVOICE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.invoice_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=row.balance_due,
                is_debit=False,
                exchange_rate=row.exchange_rate,
            )
            for row in invoices
        ]

    async def _opening_lines(
        self, tenant_id: UUID, party_id: UUID, party_type: PartyType
    ) -> list[OpenItemRow]:
        is_ar = party_type == PartyType.CUSTOMER
        item_type = OpenItemType.OPENING_AR if is_ar else OpenItemType.OPENING_AP
        statement = (
            select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.source_type == SOURCE_OPENING_BALANCE,
                JournalEntry.status == JournalEntryStatus.POSTED.value,
                JournalEntry.deleted_at.is_(None),
                JournalEntryLine.party_type == party_type.value,
                JournalEntryLine.party_id == party_id,
            )
        )
        pairs = list((await self.session.execute(statement)).all())
        if not pairs:
            return []
        allocated = await self.allocations.allocated_for_items(
            tenant_id, item_type.value, [line.id for line, _entry in pairs]
        )
        items: list[OpenItemRow] = []
        for line, entry in pairs:
            original = line.debit if is_ar else line.credit
            if original <= _ZERO:
                continue
            remaining = quantize_money(original - allocated.get(line.id, _ZERO))
            if remaining <= _ZERO:
                continue
            number = entry.reference or entry.document_number
            items.append(
                OpenItemRow(
                    item_type=item_type,
                    document_id=line.id,
                    document_number=number,
                    document_date=entry.entry_date,
                    due_date=line.due_date,
                    currency_id=line.currency_id,
                    original_amount=original,
                    balance=remaining,
                    is_debit=is_ar,
                    exchange_rate=line.exchange_rate,
                )
            )
        return items

    async def _customer_advances(self, tenant_id: UUID, customer_id: UUID) -> list[OpenItemRow]:
        statement = select(CustomerPayment).where(
            CustomerPayment.tenant_id == tenant_id,
            CustomerPayment.customer_id == customer_id,
            CustomerPayment.deleted_at.is_(None),
            CustomerPayment.status == InvoiceDocumentStatus.POSTED.value,
            CustomerPayment.amount_unapplied > _ZERO,
        )
        payments = list((await self.session.execute(statement)).scalars().all())
        return [
            OpenItemRow(
                item_type=OpenItemType.CUSTOMER_PAYMENT,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.payment_date,
                due_date=None,
                currency_id=row.currency_id,
                original_amount=row.amount_received,
                balance=row.amount_unapplied,
                is_debit=False,
                exchange_rate=row.exchange_rate,
            )
            for row in payments
        ]

    async def _supplier_advances(self, tenant_id: UUID, supplier_id: UUID) -> list[OpenItemRow]:
        statement = select(SupplierPayment).where(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.supplier_id == supplier_id,
            SupplierPayment.deleted_at.is_(None),
            SupplierPayment.status == InvoiceDocumentStatus.POSTED.value,
            SupplierPayment.amount_unapplied > _ZERO,
        )
        payments = list((await self.session.execute(statement)).scalars().all())
        return [
            OpenItemRow(
                item_type=OpenItemType.SUPPLIER_PAYMENT,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.payment_date,
                due_date=None,
                currency_id=row.currency_id,
                original_amount=row.amount_paid,
                balance=row.amount_unapplied,
                is_debit=True,
                exchange_rate=row.exchange_rate,
            )
            for row in payments
        ]

    async def _unapplied_credit_notes(
        self, tenant_id: UUID, customer_id: UUID
    ) -> list[OpenItemRow]:
        statement = select(CreditNote).where(
            CreditNote.tenant_id == tenant_id,
            CreditNote.customer_id == customer_id,
            CreditNote.deleted_at.is_(None),
            CreditNote.status == InvoiceDocumentStatus.POSTED.value,
            CreditNote.amount_unapplied > _ZERO,
        )
        notes = list((await self.session.execute(statement)).scalars().all())
        return [
            OpenItemRow(
                item_type=OpenItemType.CREDIT_NOTE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.credit_note_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=row.amount_unapplied,
                is_debit=False,
                exchange_rate=row.exchange_rate,
            )
            for row in notes
        ]

    async def _unapplied_debit_notes(
        self, tenant_id: UUID, supplier_id: UUID
    ) -> list[OpenItemRow]:
        statement = select(DebitNote).where(
            DebitNote.tenant_id == tenant_id,
            DebitNote.supplier_id == supplier_id,
            DebitNote.deleted_at.is_(None),
            DebitNote.status == InvoiceDocumentStatus.POSTED.value,
            DebitNote.amount_unapplied > _ZERO,
        )
        notes = list((await self.session.execute(statement)).scalars().all())
        return [
            OpenItemRow(
                item_type=OpenItemType.DEBIT_NOTE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.debit_note_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=row.amount_unapplied,
                is_debit=True,
                exchange_rate=row.exchange_rate,
            )
            for row in notes
        ]
