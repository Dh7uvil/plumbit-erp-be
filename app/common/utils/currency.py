"""Exact decimal helpers for money and quantities."""

from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.0001")
QUANTITY_QUANTUM = Decimal("0.000001")


def quantize_money(
    value: Decimal,
    *,
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Round a monetary value to the database's four-decimal scale."""

    return value.quantize(MONEY_QUANTUM, rounding=rounding)


def quantize_quantity(
    value: Decimal,
    *,
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Round a quantity to the database's six-decimal scale."""

    return value.quantize(QUANTITY_QUANTUM, rounding=rounding)
