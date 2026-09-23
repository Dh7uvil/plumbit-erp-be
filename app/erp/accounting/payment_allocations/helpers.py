"""Cross-currency and credit/debit note netting helpers for payment allocation."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.common.utils.datetime import utcnow
from app.core.enums import InvoiceDocumentStatus, OpenItemType, PartyType, PaymentAllocationSource
from app.core.exceptions import PaymentOverAllocatedError, ValidationError
from app.erp.accounting.open_items.repository import PaymentAllocationRepository
from app.erp.accounting.open_items.schemas import OpenItemRow, PaymentAllocationInput

_ZERO = Decimal("0")
_CASH_AR = frozenset({OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR})
_CASH_AP = frozenset({OpenItemType.PURCHASE_INVOICE, OpenItemType.OPENING_AP})
_CREDIT_AR = OpenItemType.CREDIT_NOTE
_DEBIT_AP = OpenItemType.DEBIT_NOTE


class _PaymentCurrencyRow(Protocol):
    currency_id: UUID
    exchange_rate: Decimal


def cash_allocation_types(*, receivable: bool) -> frozenset[OpenItemType]:
    return _CASH_AR if receivable else _CASH_AP


def note_allocation_type(*, receivable: bool) -> OpenItemType:
    return _CREDIT_AR if receivable else _DEBIT_AP


def split_payment_allocations(
    allocations: Sequence[PaymentAllocationInput],
    *,
    receivable: bool,
) -> tuple[list[PaymentAllocationInput], list[PaymentAllocationInput]]:
    cash_types = cash_allocation_types(receivable=receivable)
    note_type = note_allocation_type(receivable=receivable)
    cash: list[PaymentAllocationInput] = []
    notes: list[PaymentAllocationInput] = []
    for item in allocations:
        if item.item_type in cash_types:
            cash.append(item)
        elif item.item_type == note_type:
            notes.append(item)
        else:
            raise ValidationError("Invalid allocation item type")
    return cash, notes


def sum_cash_allocations(
    allocations: Sequence[PaymentAllocationInput],
    *,
    receivable: bool,
) -> Decimal:
    cash_types = cash_allocation_types(receivable=receivable)
    return quantize_money(
        sum((item.amount for item in allocations if item.item_type in cash_types), _ZERO)
    )


def allocation_base_amount(
    payment: _PaymentCurrencyRow,
    open_row: OpenItemRow | Any,
    amount_in_item_currency: Decimal,
) -> Decimal:
    """Base-currency equivalent of an allocation amount in open-item currency."""

    item_rate = open_row.exchange_rate or payment.exchange_rate
    return quantize_money(amount_in_item_currency * item_rate)


def open_item_amount_in_payment_currency(
    payment: _PaymentCurrencyRow,
    open_row: OpenItemRow | Any,
    amount_in_item_currency: Decimal,
) -> Decimal:
    if payment.currency_id == open_row.currency_id:
        return quantize_money(amount_in_item_currency)
    item_rate = open_row.exchange_rate
    payment_rate = payment.exchange_rate
    if item_rate is None or payment_rate is None or payment_rate == _ZERO:
        raise ValidationError("Exchange rate required for cross-currency allocation")
    base = quantize_money(amount_in_item_currency * item_rate)
    return quantize_money(base / payment_rate)


def realized_fx_on_allocation(
    payment: _PaymentCurrencyRow,
    open_row: OpenItemRow | Any,
    amount_in_item_currency: Decimal,
    *,
    payable: bool = False,
) -> Decimal:
    """Base-currency FX difference when payment and open-item currencies differ."""

    if payment.currency_id == open_row.currency_id:
        item_rate = open_row.exchange_rate or payment.exchange_rate
        fx = quantize_money(
            amount_in_item_currency * payment.exchange_rate - amount_in_item_currency * item_rate
        )
    else:
        item_rate = open_row.exchange_rate or payment.exchange_rate
        payment_slice = open_item_amount_in_payment_currency(
            payment, open_row, amount_in_item_currency
        )
        fx = quantize_money(
            payment_slice * payment.exchange_rate - amount_in_item_currency * item_rate
        )
    return -fx if payable else fx


async def open_item_row_for_allocation(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    receivable: bool,
    party_id: UUID,
    item: PaymentAllocationInput,
    open_rows: Sequence[OpenItemRow] | None = None,
) -> OpenItemRow:
    """Open-item row for allocate/unapply, including fully settled documents."""

    if open_rows is None:
        from app.erp.accounting.open_items.service import OpenItemsService

        service = OpenItemsService(session)
        open_rows = (
            await service.list_ar_open_items(tenant_id, party_id)
            if receivable
            else await service.list_ap_open_items(tenant_id, party_id)
        )
    for row in open_rows:
        if row.item_type == item.item_type and row.document_id == item.item_id:
            return row
    if item.item_type == OpenItemType.SALES_INVOICE:
        from app.erp.sales_invoices.repository import SalesInvoiceRepository

        invoice = await SalesInvoiceRepository(session).get(tenant_id, item.item_id)
        if (
            invoice is None
            or invoice.customer_id != party_id
            or InvoiceDocumentStatus(invoice.status) != InvoiceDocumentStatus.POSTED
        ):
            raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})
        return OpenItemRow(
            item_type=OpenItemType.SALES_INVOICE,
            document_id=invoice.id,
            document_number=invoice.document_number,
            document_date=invoice.invoice_date,
            due_date=invoice.due_date,
            currency_id=invoice.currency_id,
            original_amount=invoice.grand_total,
            balance=invoice.balance_due,
            is_debit=True,
            exchange_rate=invoice.exchange_rate,
        )
    if item.item_type == OpenItemType.PURCHASE_INVOICE:
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository

        bill = await PurchaseInvoiceRepository(session).get(tenant_id, item.item_id)
        if (
            bill is None
            or bill.supplier_id != party_id
            or InvoiceDocumentStatus(bill.status) != InvoiceDocumentStatus.POSTED
        ):
            raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})
        return OpenItemRow(
            item_type=OpenItemType.PURCHASE_INVOICE,
            document_id=bill.id,
            document_number=bill.document_number,
            document_date=bill.invoice_date,
            due_date=bill.due_date,
            currency_id=bill.currency_id,
            original_amount=bill.grand_total,
            balance=bill.balance_due,
            is_debit=True,
            exchange_rate=bill.exchange_rate,
        )
    if item.item_type in {OpenItemType.OPENING_AR, OpenItemType.OPENING_AP}:
        from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine

        line = await session.get(JournalEntryLine, item.item_id)
        if line is None or line.tenant_id != tenant_id:
            raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})
        entry = await session.get(JournalEntry, line.journal_entry_id)
        if entry is None or entry.tenant_id != tenant_id:
            raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})
        is_ar = item.item_type == OpenItemType.OPENING_AR
        expected_party = PartyType.CUSTOMER if receivable else PartyType.SUPPLIER
        if line.party_type != expected_party.value or line.party_id != party_id:
            raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})
        original = line.debit if is_ar else line.credit
        number = entry.reference or entry.document_number
        return OpenItemRow(
            item_type=item.item_type,
            document_id=line.id,
            document_number=number,
            document_date=entry.entry_date,
            due_date=line.due_date,
            currency_id=line.currency_id,
            original_amount=original,
            balance=original,
            is_debit=is_ar,
            exchange_rate=line.exchange_rate,
        )
    raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})


async def record_note_allocations_on_payment(
    allocations_repo: PaymentAllocationRepository,
    tenant_id: UUID,
    payment_type: str,
    payment_id: UUID,
    notes: Sequence[PaymentAllocationInput],
    *,
    receivable: bool,
    session: AsyncSession | None = None,
    party_id: UUID | None = None,
    payment: _PaymentCurrencyRow | None = None,
) -> None:
    """Persist credit/debit note rows on a payment for allocation history (subledger only)."""

    expected = note_allocation_type(receivable=receivable)
    for note in notes:
        if note.item_type != expected:
            continue
        base_amount: Decimal | None = None
        if session is not None and party_id is not None and payment is not None:
            open_row = await open_item_row_for_allocation(
                session,
                tenant_id,
                receivable=receivable,
                party_id=party_id,
                item=note,
            )
            base_amount = allocation_base_amount(payment, open_row, note.amount)
        await allocations_repo.create(
            tenant_id,
            payment_type=payment_type,
            payment_id=payment_id,
            item_type=note.item_type.value,
            item_id=note.item_id,
            amount=note.amount,
            base_amount=base_amount,
        )


async def reverse_note_netting_on_payment(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    receivable: bool,
    note_id: UUID,
    invoice_id: UUID,
    amount: Decimal,
) -> None:
    """Reverse subledger credit/debit note netting when a payment is cancelled."""

    amount = quantize_money(amount)
    repo = PaymentAllocationRepository(session)
    invoice_type = OpenItemType.SALES_INVOICE if receivable else OpenItemType.PURCHASE_INVOICE
    note_source = (
        PaymentAllocationSource.CREDIT_NOTE if receivable else PaymentAllocationSource.DEBIT_NOTE
    )
    if receivable:
        from app.erp.credit_notes.repository import CreditNoteRepository
        from app.erp.sales_invoices.service import SalesInvoiceService

        invoices = SalesInvoiceService(session)
        await invoices.apply_credit(tenant_id, invoice_id, -amount)
        note = await CreditNoteRepository(session).get(tenant_id, note_id)
        if note is not None:
            note.amount_applied = quantize_money(note.amount_applied - amount)
            note.amount_unapplied = quantize_money(note.amount_unapplied + amount)
    else:
        from app.erp.debit_notes.repository import DebitNoteRepository
        from app.erp.purchase_invoices.service import PurchaseInvoiceService

        invoices = PurchaseInvoiceService(session)
        await invoices.apply_debit(tenant_id, invoice_id, -amount)
        note = await DebitNoteRepository(session).get(tenant_id, note_id)
        if note is not None:
            note.amount_applied = quantize_money(note.amount_applied - amount)
            note.amount_unapplied = quantize_money(note.amount_unapplied + amount)

    for alloc in await repo.list_live_for_payment(tenant_id, note_source.value, note_id):
        if (
            alloc.item_type == invoice_type.value
            and alloc.item_id == invoice_id
            and alloc.amount == amount
        ):
            alloc.reversed_at = utcnow()
            break


def require_single_invoice_target(
    cash: Sequence[PaymentAllocationInput],
    *,
    receivable: bool,
) -> UUID | None:
    invoice_type = OpenItemType.SALES_INVOICE if receivable else OpenItemType.PURCHASE_INVOICE
    targets = [item for item in cash if item.item_type == invoice_type]
    if len(targets) == 1:
        return targets[0].item_id
    if len(targets) > 1:
        raise ValidationError(
            "Credit or debit notes on a payment must be paired with exactly one invoice or bill"
        )
    return None
