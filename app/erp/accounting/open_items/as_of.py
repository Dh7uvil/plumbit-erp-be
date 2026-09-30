"""Historical open-item balances from allocations, credits, and write-offs dated on or before as-of."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import (
    InvoiceDocumentStatus,
    JournalEntryStatus,
    OpenItemType,
    PartyType,
    PaymentAllocationSource,
)
from app.erp.accounting.customer_payments.models import CustomerPayment
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.ledger.posting import SOURCE_OPENING_BALANCE
from app.erp.accounting.open_items.repository import PaymentAllocationRepository
from app.erp.accounting.open_items.schemas import OpenExposureItem, OpenItemRow
from app.erp.accounting.supplier_payments.models import SupplierPayment
from app.erp.accounting.write_offs.constants import (
    DOCUMENT_KIND_PURCHASE_INVOICE,
    DOCUMENT_KIND_SALES_INVOICE,
)
from app.erp.accounting.write_offs.models import InvoiceWriteOff
from app.erp.credit_notes.models import CreditNote
from app.erp.debit_notes.models import DebitNote
from app.erp.exchange_rates.service import CurrencyService
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.sales_invoices.models import SalesInvoice

_ZERO = Decimal("0")


@dataclass
class AsOfOpenItem:
    party_id: UUID
    item_type: OpenItemType
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None
    currency_id: UUID
    original_amount: Decimal
    balance: Decimal
    is_debit: bool
    exchange_rate: Decimal | None = None
    currency_code: str | None = None

    def to_open_item_row(self) -> OpenItemRow:
        return OpenItemRow(
            item_type=self.item_type,
            document_id=self.document_id,
            document_number=self.document_number,
            document_date=self.document_date,
            due_date=self.due_date,
            currency_id=self.currency_id,
            currency_code=self.currency_code,
            original_amount=self.original_amount,
            balance=self.balance,
            is_debit=self.is_debit,
            exchange_rate=self.exchange_rate,
        )

    def to_exposure_item(self, *, party_type: PartyType) -> OpenExposureItem:
        return OpenExposureItem(
            exposure_kind="AR" if party_type == PartyType.CUSTOMER else "AP",
            item_type=self.item_type,
            document_id=self.document_id,
            document_number=self.document_number,
            party_type=party_type,
            party_id=self.party_id,
            currency_id=self.currency_id,
            balance=self.balance,
            exchange_rate=self.exchange_rate,
            is_debit=self.is_debit,
        )


async def as_of_balances(
    session: AsyncSession,
    tenant_id: UUID,
    party_type: PartyType,
    as_of_date: date,
) -> list[AsOfOpenItem]:
    """Open amount per document as of ``as_of_date`` for all parties of ``party_type``."""

    allocations = PaymentAllocationRepository(session)
    currencies = CurrencyService(session)
    rows: list[AsOfOpenItem] = []
    if party_type == PartyType.CUSTOMER:
        rows.extend(await _sales_invoices(session, tenant_id, as_of_date, allocations))
        rows.extend(await _opening_ar(session, tenant_id, as_of_date, allocations))
        rows.extend(await _customer_advances(session, tenant_id, as_of_date, allocations))
        rows.extend(await _credit_notes(session, tenant_id, as_of_date, allocations))
    else:
        rows.extend(await _purchase_invoices(session, tenant_id, as_of_date, allocations))
        rows.extend(await _opening_ap(session, tenant_id, as_of_date, allocations))
        rows.extend(await _supplier_advances(session, tenant_id, as_of_date, allocations))
        rows.extend(await _debit_notes(session, tenant_id, as_of_date, allocations))
    rows = [row for row in rows if row.balance > _ZERO]
    rows.sort(key=lambda item: (item.document_date, item.document_number))
    codes = await currencies.codes_by_ids(tenant_id, [row.currency_id for row in rows])
    for row in rows:
        row.currency_code = codes.get(row.currency_id)
    return rows


async def _sales_invoices(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    invoices = list(
        (
            await session.execute(
                select(SalesInvoice).where(
                    SalesInvoice.tenant_id == tenant_id,
                    SalesInvoice.deleted_at.is_(None),
                    SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                    SalesInvoice.invoice_date <= as_of_date,
                )
            )
        )
        .scalars()
        .all()
    )
    if not invoices:
        return []
    invoice_ids = [row.id for row in invoices]
    allocated = await allocations.allocated_for_items_as_of(
        tenant_id, OpenItemType.SALES_INVOICE.value, invoice_ids, as_of_date
    )
    written_off = await _write_offs_for_invoices(
        session, tenant_id, DOCUMENT_KIND_SALES_INVOICE, invoice_ids, as_of_date
    )
    items: list[AsOfOpenItem] = []
    for row in invoices:
        balance = quantize_money(
            row.grand_total - allocated.get(row.id, _ZERO) - written_off.get(row.id, _ZERO)
        )
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=row.customer_id,
                item_type=OpenItemType.SALES_INVOICE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.invoice_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=balance,
                is_debit=True,
                exchange_rate=row.exchange_rate,
            )
        )
    return items


async def _purchase_invoices(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    invoices = list(
        (
            await session.execute(
                select(PurchaseInvoice).where(
                    PurchaseInvoice.tenant_id == tenant_id,
                    PurchaseInvoice.deleted_at.is_(None),
                    PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                    PurchaseInvoice.invoice_date <= as_of_date,
                )
            )
        )
        .scalars()
        .all()
    )
    if not invoices:
        return []
    invoice_ids = [row.id for row in invoices]
    allocated = await allocations.allocated_for_items_as_of(
        tenant_id, OpenItemType.PURCHASE_INVOICE.value, invoice_ids, as_of_date
    )
    written_off = await _write_offs_for_invoices(
        session, tenant_id, DOCUMENT_KIND_PURCHASE_INVOICE, invoice_ids, as_of_date
    )
    items: list[AsOfOpenItem] = []
    for row in invoices:
        balance = quantize_money(
            row.grand_total - allocated.get(row.id, _ZERO) - written_off.get(row.id, _ZERO)
        )
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=row.supplier_id,
                item_type=OpenItemType.PURCHASE_INVOICE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.invoice_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=balance,
                is_debit=False,
                exchange_rate=row.exchange_rate,
            )
        )
    return items


async def _opening_ar(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    return await _opening_lines(
        session,
        tenant_id,
        as_of_date,
        allocations,
        party_type=PartyType.CUSTOMER,
        item_type=OpenItemType.OPENING_AR,
        is_debit=True,
    )


async def _opening_ap(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    return await _opening_lines(
        session,
        tenant_id,
        as_of_date,
        allocations,
        party_type=PartyType.SUPPLIER,
        item_type=OpenItemType.OPENING_AP,
        is_debit=False,
    )


async def _opening_lines(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
    *,
    party_type: PartyType,
    item_type: OpenItemType,
    is_debit: bool,
) -> list[AsOfOpenItem]:
    statement = (
        select(JournalEntryLine, JournalEntry)
        .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalEntryLine.tenant_id == tenant_id,
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.source_type == SOURCE_OPENING_BALANCE,
            JournalEntry.status == JournalEntryStatus.POSTED.value,
            JournalEntry.deleted_at.is_(None),
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.party_type == party_type.value,
            JournalEntryLine.party_id.is_not(None),
        )
    )
    pairs = list((await session.execute(statement)).all())
    if not pairs:
        return []
    line_ids = [line.id for line, _entry in pairs]
    allocated = await allocations.allocated_for_items_as_of(
        tenant_id, item_type.value, line_ids, as_of_date
    )
    items: list[AsOfOpenItem] = []
    for line, entry in pairs:
        if line.party_id is None:
            continue
        original = line.debit if is_debit else line.credit
        if original <= _ZERO:
            continue
        balance = quantize_money(original - allocated.get(line.id, _ZERO))
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=line.party_id,
                item_type=item_type,
                document_id=line.id,
                document_number=entry.reference or entry.document_number,
                document_date=entry.entry_date,
                due_date=line.due_date,
                currency_id=line.currency_id,
                original_amount=original,
                balance=balance,
                is_debit=is_debit,
                exchange_rate=line.exchange_rate,
            )
        )
    return items


async def _customer_advances(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    payments = list(
        (
            await session.execute(
                select(CustomerPayment).where(
                    CustomerPayment.tenant_id == tenant_id,
                    CustomerPayment.deleted_at.is_(None),
                    CustomerPayment.status == InvoiceDocumentStatus.POSTED.value,
                    CustomerPayment.payment_date <= as_of_date,
                )
            )
        )
        .scalars()
        .all()
    )
    if not payments:
        return []
    payment_ids = [row.id for row in payments]
    allocated = await allocations.allocated_from_sources_as_of(
        tenant_id,
        PaymentAllocationSource.CUSTOMER_PAYMENT.value,
        payment_ids,
        as_of_date,
    )
    items: list[AsOfOpenItem] = []
    for row in payments:
        balance = quantize_money(row.amount_received - allocated.get(row.id, _ZERO))
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=row.customer_id,
                item_type=OpenItemType.CUSTOMER_PAYMENT,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.payment_date,
                due_date=None,
                currency_id=row.currency_id,
                original_amount=row.amount_received,
                balance=balance,
                is_debit=False,
                exchange_rate=row.exchange_rate,
            )
        )
    return items


async def _supplier_advances(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    payments = list(
        (
            await session.execute(
                select(SupplierPayment).where(
                    SupplierPayment.tenant_id == tenant_id,
                    SupplierPayment.deleted_at.is_(None),
                    SupplierPayment.status == InvoiceDocumentStatus.POSTED.value,
                    SupplierPayment.payment_date <= as_of_date,
                )
            )
        )
        .scalars()
        .all()
    )
    if not payments:
        return []
    payment_ids = [row.id for row in payments]
    allocated = await allocations.allocated_from_sources_as_of(
        tenant_id,
        PaymentAllocationSource.SUPPLIER_PAYMENT.value,
        payment_ids,
        as_of_date,
    )
    items: list[AsOfOpenItem] = []
    for row in payments:
        balance = quantize_money(row.amount_paid - allocated.get(row.id, _ZERO))
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=row.supplier_id,
                item_type=OpenItemType.SUPPLIER_PAYMENT,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.payment_date,
                due_date=None,
                currency_id=row.currency_id,
                original_amount=row.amount_paid,
                balance=balance,
                is_debit=True,
                exchange_rate=row.exchange_rate,
            )
        )
    return items


async def _credit_notes(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    notes = list(
        (
            await session.execute(
                select(CreditNote).where(
                    CreditNote.tenant_id == tenant_id,
                    CreditNote.deleted_at.is_(None),
                    CreditNote.status == InvoiceDocumentStatus.POSTED.value,
                    CreditNote.credit_note_date <= as_of_date,
                )
            )
        )
        .scalars()
        .all()
    )
    if not notes:
        return []
    note_ids = [row.id for row in notes]
    allocated = await allocations.allocated_from_sources_as_of(
        tenant_id,
        PaymentAllocationSource.CREDIT_NOTE.value,
        note_ids,
        as_of_date,
    )
    items: list[AsOfOpenItem] = []
    for row in notes:
        balance = quantize_money(row.grand_total - allocated.get(row.id, _ZERO))
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=row.customer_id,
                item_type=OpenItemType.CREDIT_NOTE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.credit_note_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=balance,
                is_debit=False,
                exchange_rate=row.exchange_rate,
            )
        )
    return items


async def _debit_notes(
    session: AsyncSession,
    tenant_id: UUID,
    as_of_date: date,
    allocations: PaymentAllocationRepository,
) -> list[AsOfOpenItem]:
    notes = list(
        (
            await session.execute(
                select(DebitNote).where(
                    DebitNote.tenant_id == tenant_id,
                    DebitNote.deleted_at.is_(None),
                    DebitNote.status == InvoiceDocumentStatus.POSTED.value,
                    DebitNote.debit_note_date <= as_of_date,
                )
            )
        )
        .scalars()
        .all()
    )
    if not notes:
        return []
    note_ids = [row.id for row in notes]
    allocated = await allocations.allocated_from_sources_as_of(
        tenant_id,
        PaymentAllocationSource.DEBIT_NOTE.value,
        note_ids,
        as_of_date,
    )
    items: list[AsOfOpenItem] = []
    for row in notes:
        balance = quantize_money(row.grand_total - allocated.get(row.id, _ZERO))
        if balance <= _ZERO:
            continue
        items.append(
            AsOfOpenItem(
                party_id=row.supplier_id,
                item_type=OpenItemType.DEBIT_NOTE,
                document_id=row.id,
                document_number=row.document_number,
                document_date=row.debit_note_date,
                due_date=row.due_date,
                currency_id=row.currency_id,
                original_amount=row.grand_total,
                balance=balance,
                is_debit=True,
                exchange_rate=row.exchange_rate,
            )
        )
    return items


async def _write_offs_for_invoices(
    session: AsyncSession,
    tenant_id: UUID,
    document_kind: str,
    invoice_ids: list[UUID],
    as_of_date: date,
) -> dict[UUID, Decimal]:
    if not invoice_ids:
        return {}
    statement = (
        select(InvoiceWriteOff.invoice_id, func.coalesce(func.sum(InvoiceWriteOff.amount), 0))
        .where(
            InvoiceWriteOff.tenant_id == tenant_id,
            InvoiceWriteOff.document_kind == document_kind,
            InvoiceWriteOff.invoice_id.in_(invoice_ids),
            InvoiceWriteOff.write_off_date <= as_of_date,
            InvoiceWriteOff.reversed_at.is_(None),
        )
        .group_by(InvoiceWriteOff.invoice_id)
    )
    rows = (await session.execute(statement)).all()
    return {invoice_id: Decimal(str(amount)) for invoice_id, amount in rows}
