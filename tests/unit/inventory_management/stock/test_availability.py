"""Unit tests for available quantity."""

from decimal import Decimal

from app.inventory_management.stock.availability import available_qty


def test_available_subtracts_reserved_and_quality_hold() -> None:
    assert available_qty(Decimal("10"), Decimal("3"), Decimal("2")) == Decimal("5")


def test_available_is_on_hand_when_buckets_are_zero() -> None:
    assert available_qty(Decimal("8")) == Decimal("8")


def test_available_can_be_negative() -> None:
    assert available_qty(Decimal("1"), Decimal("0"), Decimal("4")) == Decimal("-3")
