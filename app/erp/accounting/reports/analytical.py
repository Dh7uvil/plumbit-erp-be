"""Query-time sales and purchase analysis reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.common.utils.currency import quantize_money
from app.core.enums import InvoiceDocumentStatus
from app.core.exceptions import ValidationError
from app.crm.customers.models import Customer
from app.erp.accounting.reports.amounts import document_base_net_tax
from app.erp.accounting.reports.schemas import (
    SalesPurchaseAnalysisLine,
    SalesPurchaseAnalysisResponse,
)
from app.erp.credit_notes.models import CreditNote
from app.erp.debit_notes.models import DebitNote
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.sales_invoices.models import SalesInvoice

_ZERO = Decimal("0")
_SALES_GROUPS = frozenset({"summary", "customer", "product", "date", "salesperson"})
_PURCHASE_GROUPS = frozenset({"summary", "supplier", "product", "date"})


def _document_rate(document: object) -> Decimal | None:
    rate = getattr(document, "exchange_rate", None)
    if rate is None:
        return None
    return Decimal(rate)


def _document_number(document: object) -> str:
    number = getattr(document, "document_number", None)
    return str(number) if number else "document"


def _converted_amounts(
    document: object, *, sign: Decimal, warnings: list[str]
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Return (net, tax, rate) in base currency, or None when the rate is missing."""

    rate = _document_rate(document)
    if rate is None:
        warnings.append(f"Excluded {_document_number(document)}: exchange rate missing")
        return None
    base = getattr(document, "base_amount", None)
    if base is not None:
        net = quantize_money(Decimal(base) * sign)
    else:
        grand = getattr(document, "grand_total", None)
        if grand is None:
            warnings.append(f"Excluded {_document_number(document)}: amount missing")
            return None
        net = quantize_money(Decimal(grand) * rate * sign)
    tax_amount = getattr(document, "tax_amount", _ZERO) or _ZERO
    tax = quantize_money(Decimal(tax_amount) * rate * sign)
    return net, tax, rate


class AnalyticalReports:
    async def sales_analysis(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        group_by: str = "summary",
    ) -> SalesPurchaseAnalysisResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        if group_by not in _SALES_GROUPS:
            raise ValidationError("Invalid sales analysis grouping", details={"group_by": group_by})
        invoices = await self._posted_sales(tenant_id, from_date, to_date)
        notes = await self._analysis_credit_notes(tenant_id, from_date, to_date)
        buckets: dict[str, list] = defaultdict(
            lambda: [_ZERO, _ZERO, _ZERO, 0, "", None, None, None]
        )
        warnings: list[str] = []
        names = await self._party_names(
            tenant_id, {row.customer_id for row in invoices} | {row.customer_id for row in notes}
        )
        product_names = await self._product_names(
            tenant_id,
            {
                line.product_id
                for row in invoices + notes
                for line in row.lines
                if line.product_id is not None
            },
        )
        for invoice in invoices:
            self._accumulate_sales_invoice(
                buckets,
                invoice,
                group_by=group_by,
                names=names,
                product_names=product_names,
                sign=Decimal("1"),
                warnings=warnings,
            )
        for note in notes:
            self._accumulate_credit_note(
                buckets,
                note,
                group_by=group_by,
                names=names,
                product_names=product_names,
                warnings=warnings,
            )
        return await self._analysis_response(
            tenant_id, from_date, to_date, group_by, buckets, warnings=warnings
        )

    async def purchase_analysis(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        group_by: str = "summary",
    ) -> SalesPurchaseAnalysisResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        if group_by not in _PURCHASE_GROUPS:
            raise ValidationError(
                "Invalid purchase analysis grouping", details={"group_by": group_by}
            )
        invoices = await self._posted_purchases(tenant_id, from_date, to_date)
        notes = await self._posted_debit_notes(tenant_id, from_date, to_date)
        buckets: dict[str, list] = defaultdict(
            lambda: [_ZERO, _ZERO, _ZERO, 0, "", None, None, None]
        )
        warnings: list[str] = []
        names = await self._party_names(
            tenant_id, {row.supplier_id for row in invoices} | {row.supplier_id for row in notes}
        )
        product_names = await self._product_names(
            tenant_id,
            {
                line.product_id
                for row in invoices + notes
                for line in row.lines
                if getattr(line, "product_id", None) is not None
            },
        )
        for invoice in invoices:
            self._accumulate_purchase_invoice(
                buckets,
                invoice,
                group_by=group_by,
                names=names,
                product_names=product_names,
                sign=Decimal("1"),
                warnings=warnings,
            )
        for note in notes:
            self._accumulate_debit_note(
                buckets,
                note,
                group_by=group_by,
                names=names,
                product_names=product_names,
                warnings=warnings,
            )
        return await self._analysis_response(
            tenant_id, from_date, to_date, group_by, buckets, warnings=warnings
        )

    def _accumulate_sales_invoice(
        self,
        buckets,
        invoice: SalesInvoice,
        *,
        group_by: str,
        names,
        product_names,
        sign: Decimal,
        warnings: list[str],
    ) -> None:
        net, tax, grand = document_base_net_tax(invoice, sign=sign)
        rate = invoice.exchange_rate
        if group_by == "product":
            for line in invoice.lines:
                line_net = quantize_money(line.amount * rate * sign)
                line_tax = quantize_money(line.tax_amount * rate * sign)
                key = str(line.product_id) if line.product_id else "unmapped"
                label = product_names.get(line.product_id, line.description or "Unmapped")
                self._add_bucket(
                    buckets,
                    key,
                    label,
                    net=line_net,
                    tax=line_tax,
                    grand=quantize_money(line_net + line_tax),
                    product_id=line.product_id,
                )
            return
        key, label, party_id, product_id, salesperson_id = self._sales_group(
            invoice, group_by=group_by, names=names
        )
        self._add_bucket(
            buckets,
            key,
            label,
            net=net,
            tax=tax,
            grand=grand,
            party_id=party_id,
            product_id=product_id,
            salesperson_id=salesperson_id,
        )

    def _accumulate_credit_note(
        self, buckets, note: CreditNote, *, group_by: str, names, product_names, warnings: list[str]
    ) -> None:
        sign = Decimal("-1")
        net, tax, grand = document_base_net_tax(note, sign=sign)
        rate = note.exchange_rate
        if group_by == "product":
            for line in note.lines:
                line_net = quantize_money(line.amount * rate * sign)
                line_tax = quantize_money(line.tax_amount * rate * sign)
                key = str(line.product_id) if line.product_id else "unmapped"
                label = product_names.get(line.product_id, line.description or "Unmapped")
                self._add_bucket(
                    buckets,
                    key,
                    label,
                    net=line_net,
                    tax=line_tax,
                    grand=quantize_money(line_net + line_tax),
                    product_id=line.product_id,
                )
            return
        key = (
            str(note.customer_id)
            if group_by == "customer"
            else (
                note.credit_note_date.isoformat()
                if group_by == "date"
                else (
                    str(note.salesperson_id)
                    if group_by == "salesperson" and getattr(note, "salesperson_id", None)
                    else "summary"
                )
            )
        )
        if group_by == "customer":
            label = names.get(note.customer_id, "")
            party_id = note.customer_id
            salesperson_id = None
        elif group_by == "date":
            label = note.credit_note_date.isoformat()
            party_id = None
            salesperson_id = None
        elif group_by == "salesperson":
            label = "Unassigned"
            party_id = None
            salesperson_id = getattr(note, "salesperson_id", None)
            key = str(salesperson_id) if salesperson_id else "unassigned"
        else:
            label = "All sales"
            party_id = None
            salesperson_id = None
            key = "summary"
        self._add_bucket(
            buckets,
            key,
            label,
            net=net,
            tax=tax,
            grand=grand,
            party_id=party_id,
            salesperson_id=salesperson_id,
        )

    def _accumulate_purchase_invoice(
        self,
        buckets,
        invoice: PurchaseInvoice,
        *,
        group_by: str,
        names,
        product_names,
        sign: Decimal,
        warnings: list[str],
    ) -> None:
        net, tax, grand = document_base_net_tax(invoice, sign=sign)
        rate = invoice.exchange_rate
        if group_by == "product":
            for line in invoice.lines:
                line_net = quantize_money(line.amount * rate * sign)
                line_tax = quantize_money(line.tax_amount * rate * sign)
                key = str(line.product_id) if getattr(line, "product_id", None) else "unmapped"
                label = product_names.get(
                    getattr(line, "product_id", None),
                    getattr(line, "description", None) or "Unmapped",
                )
                self._add_bucket(
                    buckets,
                    key,
                    label,
                    net=line_net,
                    tax=line_tax,
                    grand=quantize_money(line_net + line_tax),
                    product_id=getattr(line, "product_id", None),
                )
            return
        if group_by == "supplier":
            key = str(invoice.supplier_id)
            label = names.get(invoice.supplier_id, "")
            party_id = invoice.supplier_id
        elif group_by == "date":
            key = invoice.invoice_date.isoformat()
            label = key
            party_id = None
        else:
            key = "summary"
            label = "All purchases"
            party_id = None
        self._add_bucket(
            buckets,
            key,
            label,
            net=net,
            tax=tax,
            grand=grand,
            party_id=party_id,
        )

    def _accumulate_debit_note(
        self, buckets, note: DebitNote, *, group_by: str, names, product_names, warnings: list[str]
    ) -> None:
        sign = Decimal("-1")
        net, tax, grand = document_base_net_tax(note, sign=sign)
        rate = note.exchange_rate
        if group_by == "product":
            for line in note.lines:
                line_net = quantize_money(line.amount * rate * sign)
                line_tax = quantize_money(line.tax_amount * rate * sign)
                key = str(line.product_id) if getattr(line, "product_id", None) else "unmapped"
                label = product_names.get(
                    getattr(line, "product_id", None),
                    getattr(line, "description", None) or "Unmapped",
                )
                self._add_bucket(
                    buckets,
                    key,
                    label,
                    net=line_net,
                    tax=line_tax,
                    grand=quantize_money(line_net + line_tax),
                    product_id=getattr(line, "product_id", None),
                )
            return
        if group_by == "supplier":
            key = str(note.supplier_id)
            label = names.get(note.supplier_id, "")
            party_id = note.supplier_id
        elif group_by == "date":
            key = note.debit_note_date.isoformat()
            label = key
            party_id = None
        else:
            key = "summary"
            label = "All purchases"
            party_id = None
        self._add_bucket(buckets, key, label, net=net, tax=tax, grand=grand, party_id=party_id)

    def _sales_group(self, invoice: SalesInvoice, *, group_by: str, names) -> tuple:
        if group_by == "customer":
            return (
                str(invoice.customer_id),
                names.get(invoice.customer_id, ""),
                invoice.customer_id,
                None,
                None,
            )
        if group_by == "date":
            key = invoice.invoice_date.isoformat()
            return key, key, None, None, None
        if group_by == "salesperson":
            salesperson_id = invoice.salesperson_id
            key = str(salesperson_id) if salesperson_id else "unassigned"
            label = "Unassigned" if salesperson_id is None else key
            return key, label, None, None, salesperson_id
        return "summary", "All sales", None, None, None

    def _add_bucket(
        self,
        buckets,
        key: str,
        label: str,
        *,
        net: Decimal,
        tax: Decimal,
        grand: Decimal,
        party_id: UUID | None = None,
        product_id: UUID | None = None,
        salesperson_id: UUID | None = None,
    ) -> None:
        row = buckets[key]
        row[0] = quantize_money(row[0] + net)
        row[1] = quantize_money(row[1] + tax)
        row[2] = quantize_money(row[2] + grand)
        row[3] += 1
        row[4] = label
        row[5] = party_id if party_id is not None else row[5]
        row[6] = product_id if product_id is not None else row[6]
        row[7] = salesperson_id if salesperson_id is not None else row[7]

    async def _analysis_response(
        self,
        tenant_id: UUID,
        from_date: date,
        to_date: date,
        group_by: str,
        buckets,
        *,
        warnings: list[str],
    ) -> SalesPurchaseAnalysisResponse:
        lines = [
            SalesPurchaseAnalysisLine(
                group_key=key,
                group_label=values[4],
                document_count=values[3],
                net_amount=values[0],
                tax_amount=values[1],
                grand_total=values[2],
                party_id=values[5],
                product_id=values[6],
                salesperson_id=values[7],
            )
            for key, values in buckets.items()
        ]
        lines.sort(key=lambda line: line.group_label)
        return SalesPurchaseAnalysisResponse(
            currency_code=await self._report_currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            group_by=group_by,
            document_count=sum(line.document_count for line in lines),
            total_net=quantize_money(sum((line.net_amount for line in lines), _ZERO)),
            total_tax=quantize_money(sum((line.tax_amount for line in lines), _ZERO)),
            total_grand=quantize_money(sum((line.grand_total for line in lines), _ZERO)),
            warnings=warnings,
            lines=lines,
        )

    async def _posted_sales(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[SalesInvoice]:
        statement = (
            select(SalesInvoice)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoice.invoice_date >= from_date,
                SalesInvoice.invoice_date <= to_date,
            )
            .options(selectinload(SalesInvoice.lines))
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _analysis_credit_notes(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[CreditNote]:
        statement = (
            select(CreditNote)
            .where(
                CreditNote.tenant_id == tenant_id,
                CreditNote.deleted_at.is_(None),
                CreditNote.status == InvoiceDocumentStatus.POSTED.value,
                CreditNote.credit_note_date >= from_date,
                CreditNote.credit_note_date <= to_date,
            )
            .options(selectinload(CreditNote.lines))
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _posted_purchases(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[PurchaseInvoice]:
        statement = (
            select(PurchaseInvoice)
            .where(
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoice.invoice_date >= from_date,
                PurchaseInvoice.invoice_date <= to_date,
            )
            .options(selectinload(PurchaseInvoice.lines))
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _posted_debit_notes(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[DebitNote]:
        statement = (
            select(DebitNote)
            .where(
                DebitNote.tenant_id == tenant_id,
                DebitNote.deleted_at.is_(None),
                DebitNote.status == InvoiceDocumentStatus.POSTED.value,
                DebitNote.debit_note_date >= from_date,
                DebitNote.debit_note_date <= to_date,
            )
            .options(selectinload(DebitNote.lines))
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _party_names(self, tenant_id: UUID, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(Customer.id, Customer.name).where(
                    Customer.tenant_id == tenant_id, Customer.id.in_(ids)
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    async def _product_names(self, tenant_id: UUID, ids: set[UUID]) -> dict[UUID, str]:
        from app.inventory_management.products.models import Product

        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(Product.id, Product.name).where(
                    Product.tenant_id == tenant_id, Product.id.in_(ids)
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}
