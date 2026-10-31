"""Derived display fields for sales commercial documents."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.core.enums import BillingStatus, QuotationStatus, TaxTreatment


class _TaxableLine(Protocol):
    amount: Decimal
    tax_rate: Decimal


def registration_type_label(treatment: TaxTreatment) -> str:
    if treatment in {TaxTreatment.REGISTERED, TaxTreatment.UNREGISTERED}:
        return treatment.value
    return treatment.value


def taxable_amount_from_lines(lines: list[_TaxableLine]) -> Decimal:
    total = Decimal("0")
    for line in lines:
        if line.tax_rate and line.tax_rate > 0:
            total += line.amount
    return total


def quotation_is_invoiced(*, converted_document_id: object | None, status: str) -> bool:
    if converted_document_id is not None:
        return True
    return status in {
        QuotationStatus.CONVERTED.value,
        QuotationStatus.PARTIALLY_CONVERTED.value,
    }


def sales_order_is_invoiced(billing_status: str) -> bool:
    return billing_status != BillingStatus.NOT_INVOICED.value
