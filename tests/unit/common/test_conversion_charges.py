"""Unit tests for header charge pro-rating on partial conversion."""

from decimal import Decimal
from types import SimpleNamespace

from app.common.utils.conversion_charges import prorate_header_charges


def test_prorate_header_charges_scales_shipping_and_adjustment() -> None:
    source = SimpleNamespace(
        shipping_amount=Decimal("100.0000"),
        adjustment_amount=Decimal("20.0000"),
    )
    shipping, adjustment = prorate_header_charges(
        source,
        converted_net=Decimal("50.0000"),
        source_net=Decimal("200.0000"),
    )
    assert shipping == Decimal("25.0000")
    assert adjustment == Decimal("5.0000")


def test_prorate_header_charges_returns_full_amounts_when_fully_converted() -> None:
    source = SimpleNamespace(
        shipping_amount=Decimal("30.0000"),
        adjustment_amount=Decimal("10.0000"),
    )
    shipping, adjustment = prorate_header_charges(
        source,
        converted_net=Decimal("200.0000"),
        source_net=Decimal("200.0000"),
    )
    assert shipping == Decimal("30.0000")
    assert adjustment == Decimal("10.0000")


def test_prorate_header_charges_zero_when_source_net_is_zero() -> None:
    source = SimpleNamespace(
        shipping_amount=Decimal("30.0000"),
        adjustment_amount=Decimal("10.0000"),
    )
    shipping, adjustment = prorate_header_charges(
        source,
        converted_net=Decimal("50.0000"),
        source_net=Decimal("0"),
    )
    assert shipping == Decimal("0.0000")
    assert adjustment == Decimal("0.0000")
