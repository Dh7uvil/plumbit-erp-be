"""Pro-rate document header charges on partial conversion."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.common.utils.currency import quantize_money

_ZERO = Decimal("0")
_ONE = Decimal("1")


class HeaderChargesSource(Protocol):
    shipping_amount: Decimal
    adjustment_amount: Decimal


def prorate_header_charges(
    source_header: HeaderChargesSource,
    converted_net: Decimal,
    source_net: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return (shipping_amount, adjustment_amount) scaled by converted_net / source_net."""

    shipping = quantize_money(source_header.shipping_amount)
    adjustment = quantize_money(source_header.adjustment_amount)
    if shipping == _ZERO and adjustment == _ZERO:
        return shipping, adjustment
    converted_net = quantize_money(converted_net)
    source_net = quantize_money(source_net)
    if source_net <= _ZERO:
        return _ZERO, _ZERO
    ratio = converted_net / source_net
    if ratio >= _ONE:
        return shipping, adjustment
    return quantize_money(shipping * ratio), quantize_money(adjustment * ratio)
