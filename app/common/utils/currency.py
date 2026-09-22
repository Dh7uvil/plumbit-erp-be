"""Exact decimal helpers for money and quantities."""

from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.0001")
QUANTITY_QUANTUM = Decimal("0.000001")
RATE_QUANTUM = Decimal("0.000001")
DISPLAY_QUANTUM = Decimal("0.01")


def quantize_money(
    value: Decimal,
    *,
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Round a monetary value to the database's four-decimal scale."""

    return value.quantize(MONEY_QUANTUM, rounding=rounding)


def quantize_rate(
    value: Decimal,
    *,
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Round an exchange rate to the database's six-decimal scale."""

    return value.quantize(RATE_QUANTUM, rounding=rounding)


def document_fx_amounts(foreign_amount: Decimal, exchange_rate: Decimal) -> tuple[Decimal, Decimal]:
    """Return (foreign_amount, base_amount) quantized to money scale."""

    foreign = quantize_money(foreign_amount)
    return foreign, quantize_money(foreign * exchange_rate)


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
