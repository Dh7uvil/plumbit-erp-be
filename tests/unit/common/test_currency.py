"""Unit tests for storage quantization vs display-only 2dp formatting."""

from decimal import Decimal

from app.common.utils.currency import (
    format_money_display,
    format_quantity_display,
    quantize_money,
    quantize_quantity,
)


def test_quantize_money_keeps_four_places() -> None:
    assert quantize_money(Decimal("100.55555")) == Decimal("100.5556")
    assert quantize_money(Decimal("100")) == Decimal("100.0000")


def test_quantize_quantity_keeps_six_places() -> None:
    assert quantize_quantity(Decimal("4.1234567")) == Decimal("4.123457")
    assert quantize_quantity(Decimal("4")) == Decimal("4.000000")


def test_format_money_display_pads_and_rounds_half_up() -> None:
    assert format_money_display(Decimal("100")) == "100.00"
    assert format_money_display(Decimal("100.5")) == "100.50"
    assert format_money_display(Decimal("100.555")) == "100.56"
    assert format_money_display(Decimal("-1.2")) == "-1.20"
    assert format_money_display(Decimal("320.0000")) == "320.00"


def test_format_quantity_display_pads_and_rounds_half_up() -> None:
    assert format_quantity_display(Decimal("4")) == "4.00"
    assert format_quantity_display(Decimal("4.5")) == "4.50"
    assert format_quantity_display(Decimal("4.000000")) == "4.00"
    assert format_quantity_display(Decimal("1.235")) == "1.24"
    assert format_quantity_display(Decimal("50000.000000")) == "50000.00"
