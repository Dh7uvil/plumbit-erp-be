"""Assemble document-level party statement events (orders, openings, write-offs, refunds)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import (
    InvoiceDocumentStatus,
    JournalEntryStatus,
    PartyType,
    PurchaseOrderStatus,
    SalesOrderStatus,
)
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.ledger.posting import SOURCE_OPENING_BALANCE
from app.erp.accounting.reports.amounts import document_base_grand, payment_base_amount
from app.erp.accounting.write_offs.constants import (
    DOCUMENT_KIND_PURCHASE_INVOICE,
    DOCUMENT_KIND_SALES_INVOICE,
)
from app.erp.accounting.write_offs.models import InvoiceWriteOff
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.purchase_orders.models import PurchaseOrder
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.sales_orders.models import SalesOrder

_ZERO = Decimal("0")

PartyEvent = tuple[
    date,
    str,
    UUID,
    str,
    Decimal,
    Decimal,
    date | None,
    str | None,
    UUID,
    Decimal,
    str,
    str | None,
    date | None,
]


def _event(
    doc_date: date,
    doc_type: str,
    doc_id: UUID,
    number: str,
    debit: Decimal,
    credit: Decimal,
    *,
    due: date | None = None,
    description: str | None = None,
    currency_id: UUID,
    exchange_rate: Decimal,
    type_code: str,
    cheque_number: str | None = None,
    cheque_date: date | None = None,
) -> PartyEvent:
    return (
        doc_date,
        doc_type,
        doc_id,
        number,
        debit,
        credit,
        due,
        description,
        currency_id,
        exchange_rate,
        type_code,
        cheque_number,
        cheque_date,
    )


async def append_party_order_events(
    session: AsyncSession,
    tenant_id: UUID,
    party_id: UUID,
    party_type: PartyType,
    events: list[PartyEvent],
) -> None:
    if party_type == PartyType.SUPPLIER:
        rows = (
            (
                await session.execute(
                    select(PurchaseOrder).where(
                        PurchaseOrder.tenant_id == tenant_id,
                        PurchaseOrder.supplier_id == party_id,
                        PurchaseOrder.deleted_at.is_(None),
                        PurchaseOrder.status.in_(
                            {
                                PurchaseOrderStatus.ISSUED.value,
                                PurchaseOrderStatus.CLOSED.value,
                            }
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            amount = document_base_grand(row)
            events.append(
                _event(
                    row.order_date,
                    "PURCHASE_ORDER",
                    row.id,
                    row.document_number,
                    _ZERO,
                    amount,
                    due=row.expected_delivery_date,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    type_code="PO",
                )
            )
        return

    rows = (
        (
            await session.execute(
                select(SalesOrder).where(
                    SalesOrder.tenant_id == tenant_id,
                    SalesOrder.customer_id == party_id,
                    SalesOrder.deleted_at.is_(None),
                    SalesOrder.status.in_(
                        {
                            SalesOrderStatus.CONFIRMED.value,
                            SalesOrderStatus.CLOSED.value,
                        }
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        amount = document_base_grand(row)
        events.append(
            _event(
                row.order_date,
                "SALES_ORDER",
                row.id,
                row.document_number,
                amount,
                _ZERO,
                due=row.expected_shipment_date,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                type_code="SO",
            )
        )


async def append_party_invoice_events(
    session: AsyncSession,
    tenant_id: UUID,
    party_id: UUID,
    party_type: PartyType,
    events: list[PartyEvent],
) -> None:
    if party_type == PartyType.CUSTOMER:
        invoices = (
            (
                await session.execute(
                    select(SalesInvoice).where(
                        SalesInvoice.tenant_id == tenant_id,
                        SalesInvoice.customer_id == party_id,
                        SalesInvoice.deleted_at.is_(None),
                        SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in invoices:
            if row.sales_order_id is not None:
                continue
            amount = document_base_grand(row)
            events.append(
                _event(
                    row.invoice_date,
                    "SALES_INVOICE",
                    row.id,
                    row.document_number,
                    amount,
                    _ZERO,
                    due=row.due_date,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    type_code="SI",
                )
            )
        return

    invoices = (
        (
            await session.execute(
                select(PurchaseInvoice).where(
                    PurchaseInvoice.tenant_id == tenant_id,
                    PurchaseInvoice.supplier_id == party_id,
                    PurchaseInvoice.deleted_at.is_(None),
                    PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in invoices:
        if row.purchase_order_id is not None:
            continue
        amount = document_base_grand(row)
        events.append(
            _event(
                row.invoice_date,
                "PURCHASE_INVOICE",
                row.id,
                row.document_number,
                _ZERO,
                amount,
                due=row.due_date,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                type_code="PI",
            )
        )


async def append_party_opening_events(
    session: AsyncSession,
    tenant_id: UUID,
    party_id: UUID,
    party_type: PartyType,
    events: list[PartyEvent],
) -> None:
    is_ar = party_type == PartyType.CUSTOMER
    doc_type = "OPENING_AR" if is_ar else "OPENING_AP"
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
    pairs = list((await session.execute(statement)).all())
    for line, entry in pairs:
        original = line.debit if is_ar else line.credit
        if original <= _ZERO:
            continue
        amount = quantize_money(original)
        debit = amount if is_ar else _ZERO
        credit = _ZERO if is_ar else amount
        number = entry.reference or entry.document_number
        events.append(
            _event(
                entry.entry_date,
                doc_type,
                line.id,
                number,
                debit,
                credit,
                due=line.due_date,
                description=line.description,
                currency_id=line.currency_id,
                exchange_rate=line.exchange_rate,
                type_code="OB",
            )
        )


async def append_party_write_off_events(
    session: AsyncSession,
    tenant_id: UUID,
    party_id: UUID,
    party_type: PartyType,
    events: list[PartyEvent],
) -> None:
    if party_type == PartyType.CUSTOMER:
        invoice_kind = DOCUMENT_KIND_SALES_INVOICE
        doc_type = "SALES_INVOICE_WRITE_OFF"
    else:
        invoice_kind = DOCUMENT_KIND_PURCHASE_INVOICE
        doc_type = "PURCHASE_INVOICE_WRITE_OFF"

    write_offs = (
        (
            await session.execute(
                select(InvoiceWriteOff).where(
                    InvoiceWriteOff.tenant_id == tenant_id,
                    InvoiceWriteOff.document_kind == invoice_kind,
                    InvoiceWriteOff.reversed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not write_offs:
        return

    if party_type == PartyType.CUSTOMER:
        invoices = (
            (
                await session.execute(
                    select(SalesInvoice).where(
                        SalesInvoice.tenant_id == tenant_id,
                        SalesInvoice.customer_id == party_id,
                        SalesInvoice.deleted_at.is_(None),
                        SalesInvoice.id.in_({row.invoice_id for row in write_offs}),
                    )
                )
            )
            .scalars()
            .all()
        )
        invoice_by_id = {row.id: row for row in invoices}
    else:
        invoices = (
            (
                await session.execute(
                    select(PurchaseInvoice).where(
                        PurchaseInvoice.tenant_id == tenant_id,
                        PurchaseInvoice.supplier_id == party_id,
                        PurchaseInvoice.deleted_at.is_(None),
                        PurchaseInvoice.id.in_({row.invoice_id for row in write_offs}),
                    )
                )
            )
            .scalars()
            .all()
        )
        invoice_by_id = {row.id: row for row in invoices}

    for write_off in write_offs:
        invoice = invoice_by_id.get(write_off.invoice_id)
        if invoice is None:
            continue
        amount = quantize_money(write_off.base_amount or write_off.amount)
        if party_type == PartyType.CUSTOMER:
            debit, credit = _ZERO, amount
        else:
            debit, credit = amount, _ZERO
        events.append(
            _event(
                write_off.write_off_date,
                doc_type,
                invoice.id,
                invoice.document_number,
                debit,
                credit,
                description=write_off.reason,
                currency_id=invoice.currency_id,
                exchange_rate=invoice.exchange_rate,
                type_code="WO",
            )
        )


async def append_party_payment_refund_events(
    session: AsyncSession,
    tenant_id: UUID,
    party_id: UUID,
    party_type: PartyType,
    events: list[PartyEvent],
) -> None:
    if party_type == PartyType.CUSTOMER:
        from app.erp.accounting.customer_payments.models import CustomerPayment

        payments = (
            (
                await session.execute(
                    select(CustomerPayment).where(
                        CustomerPayment.tenant_id == tenant_id,
                        CustomerPayment.customer_id == party_id,
                        CustomerPayment.deleted_at.is_(None),
                        CustomerPayment.refund_journal_entry_id.is_not(None),
                        CustomerPayment.refunded_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in payments:
            if row.amount_refunded <= _ZERO:
                continue
            amount = payment_base_amount(row.amount_refunded, row.exchange_rate)
            events.append(
                _event(
                    row.refunded_at.date(),
                    "CUSTOMER_PAYMENT_REFUND",
                    row.id,
                    row.document_number,
                    amount,
                    _ZERO,
                    description=row.reference,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    type_code="RR",
                )
            )
        return

    from app.erp.accounting.supplier_payments.models import SupplierPayment

    payments = (
        (
            await session.execute(
                select(SupplierPayment).where(
                    SupplierPayment.tenant_id == tenant_id,
                    SupplierPayment.supplier_id == party_id,
                    SupplierPayment.deleted_at.is_(None),
                    SupplierPayment.refund_journal_entry_id.is_not(None),
                    SupplierPayment.refunded_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in payments:
        if row.amount_refunded <= _ZERO:
            continue
        amount = payment_base_amount(row.amount_refunded, row.exchange_rate)
        events.append(
            _event(
                row.refunded_at.date(),
                "SUPPLIER_PAYMENT_REFUND",
                row.id,
                row.document_number,
                _ZERO,
                amount,
                description=row.reference,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                type_code="SR",
            )
        )
