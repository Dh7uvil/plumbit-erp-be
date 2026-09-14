"""Exact decimal helpers for money and quantities."""

from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.0001")
QUANTITY_QUANTUM = Decimal("0.000001")
DISPLAY_QUANTUM = Decimal("0.01")


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


def format_money_display(
    value: Decimal,
    *,
    rounding: str = ROUND_HALF_UP,
) -> str:
    """Format money for CSV/print: two fraction digits, no grouping."""

    return _format_display(value, rounding=rounding)


def format_quantity_display(
    value: Decimal,
    *,
    rounding: str = ROUND_HALF_UP,
) -> str:
    """Format quantity for CSV/print: two fraction digits, no grouping."""

    return _format_display(value, rounding=rounding)


def _format_display(value: Decimal, *, rounding: str) -> str:
    return format(value.quantize(DISPLAY_QUANTUM, rounding=rounding), "f")
