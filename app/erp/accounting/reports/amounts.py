"""Convert document and open-item amounts to tenant base currency for reports."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.common.utils.currency import quantize_money

_ZERO = Decimal("0")


class _CommercialDoc(Protocol):
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    exchange_rate: Decimal
    base_amount: Decimal | None


def open_item_base_amount(item) -> Decimal | None:
    """Resolve an open item balance in base currency, or None when FX is missing."""

    if item.base_balance is not None:
        return item.base_balance
    if item.exchange_rate is not None:
        return quantize_money(item.balance * item.exchange_rate)
    return None


def document_base_grand(doc: _CommercialDoc, *, sign: Decimal = Decimal("1")) -> Decimal:
    """Grand total in base currency from stored base_amount or document rate."""

    if doc.base_amount is not None:
        return quantize_money(doc.base_amount * sign)
    return quantize_money(doc.grand_total * doc.exchange_rate * sign)


def document_base_net_tax(
    doc: _CommercialDoc,
    *,
    sign: Decimal = Decimal("1"),
    net_amount: Decimal | None = None,
    tax_amount: Decimal | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Net, tax, and grand in base currency."""

    rate = doc.exchange_rate
    net = (
        net_amount
        if net_amount is not None
        else quantize_money(doc.subtotal - doc.discount_amount)
    )
    tax = tax_amount if tax_amount is not None else doc.tax_amount
    net_base = quantize_money(net * rate * sign)
    tax_base = quantize_money(tax * rate * sign)
    grand_base = document_base_grand(doc, sign=sign)
    return net_base, tax_base, grand_base


def payment_base_amount(
    amount: Decimal,
    exchange_rate: Decimal,
    *,
    sign: Decimal = Decimal("1"),
) -> Decimal:
    return quantize_money(amount * exchange_rate * sign)
